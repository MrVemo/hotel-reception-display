#!/usr/bin/env python3
"""
Hotel Reception Display — Auto-Update-Mechanismus (Phase 5)

Prüft alle 6h (via systemd-Timer) ob auf dem Docker-PC (Tailscale-VPN) eine
neue Version vorliegt, und installiert sie im Wartungs-Window 03:00–05:00 Uhr.

Ablauf:
    1. Manifest holen + GPG-Signatur verifizieren
    2. Lokale Version mit Remote vergleichen
    3. Wenn neuer: Backup → Tarball downloaden → Apply → Service restart
    4. Health-Check (GET /items muss 200 + JSON liefern)
    5. Bei Fehler: Auto-Rollback aus Backup, Service restart
    6. Audit-Log-Eintrag (in lokale SQLite-DB)

Update-Quelle (Docker-PC):
    https://<docker-pc-tailscale-host>/updates/manifest.json
    https://<docker-pc-tailscale-host>/updates/manifest.json.asc
    https://<docker-pc-tailscale-host>/updates/<version>.tar.gz
    https://<docker-pc-tailscale-host>/updates/<version>.tar.gz.sha256

Manifest-Format (JSON):
    {
        "version": "1.1.0",
        "released_at": "2026-09-08T03:00:00+00:00",
        "min_compatible_from": "1.0.0",
        "tarball": "v1.1.0.tar.gz",
        "tarball_sha256": "abc123...",
        "size_bytes": 12345,
        "changelog_url": "https://.../CHANGELOG.md",
        "gpg_key_id": "ABCD1234EF567890"
    }

Signatur: `gpg --detach-sign --armor manifest.json` → `manifest.json.asc` (im Server-Setup
abgelegt). RPI verifiziert gegen importierten Public-Key via `gpg --verify`.

Konfiguration (env, gesetzt in /etc/default/hotel-display):
    HOTEL_DISPLAY_UPDATE_URL   z.B. https://100.64.1.5/updates (Tailscale-IP!)
    HOTEL_DISPLAY_UPDATE_KEY   GPG-Key-ID oder FPR (z.B. ABCD1234EF567890)
    HOTEL_DISPLAY_UPDATE_WINDOW_START  Default: 3
    HOTEL_DISPLAY_UPDATE_WINDOW_END    Default: 5
    HOTEL_DISPLAY_UPDATE_FORCE         "1" = Window ignorieren (manueller Start)
    HOTEL_DISPLAY_UPDATE_CHANNEL       "stable" (Default) | "beta" (für später)
    HOTEL_DISPLAY_VERSION_FILE         Pfad zur lokalen VERSION-Datei (Default: REPO/VERSION)

Manueller Aufruf:
    sudo -u pi /home/pi/hotel-reception-display/venv/bin/python3 \\
        /home/pi/hotel-reception-display/src/updater.py [--check-only] [--force]

Exit-Codes:
    0 = Update erfolgreich (oder kein Update nötig)
    1 = Update verfügbar, aber nicht im Wartungs-Window (nur Check)
    2 = Update-Fehler (Rollback wurde ausgeführt)
    3 = Konfigurations-/Netzwerk-Fehler (kein Update-Versuch)
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

# UTF-8 für stdout/stderr erzwingen (sonst crash bei Umlauten auf Systemen mit
# LC_ALL=C / latin-1 default wie Raspberry Pi OS)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    # Python < 3.7 oder kein reconfigure — best-effort, nichts tun
    pass

try:
    import urllib.request
    import urllib.error
except ImportError:
    print("FATAL: urllib fehlt (sollte ab Python 3.3 dabei sein)", file=sys.stderr)
    sys.exit(3)


# --- Pfade ---
REPO_DIR = Path(os.environ.get(
    "HOTEL_DISPLAY_REPO_DIR",
    "/home/pi/hotel-reception-display"
))
DATA_DIR = REPO_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups" / "updates"
VERSION_FILE = Path(os.environ.get(
    "HOTEL_DISPLAY_VERSION_FILE",
    REPO_DIR / "VERSION"
))
DB_PATH = DATA_DIR / "hotel-display.db"
LOG_PREFIX = "[hotel-updater]"
SERVICE_NAME = "hotel-display"
SERVICE_URL = os.environ.get("HOTEL_DISPLAY_UPDATE_HEALTH_URL", "http://127.0.0.1:5000/items")
HEALTH_TIMEOUT_S = 10

# Backup-Komponenten (was beim Apply überschrieben wird)
BACKUP_TARGETS = ["src", "systemd", "installer", "requirements.txt", "VERSION"]
# NICHT in Backup: data/ (DB bleibt — sonst Datenverlust), venv/, .git/

# Maximale Backups die aufbewahrt werden
MAX_BACKUPS = 5


# ============================================================================
# Hilfs-Funktionen
# ============================================================================

def log(level, msg):
    """Logausgabe mit Timestamp + Level. Geht nach stdout (journald sammelt)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{LOG_PREFIX} {ts} [{level}] {msg}", flush=True)


def read_local_version():
    """Liest die lokale VERSION-Datei. Fallback: 'unknown'."""
    try:
        return VERSION_FILE.read_text().strip()
    except FileNotFoundError:
        return "0.0.0+unknown"


def write_local_version(version):
    """Schreibt die lokale VERSION-Datei."""
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(f"{version}\n")


def parse_version(v):
    """Sehr einfache Semver-Parser für 'X.Y.Z' / 'X.Y.Z-rc1' / 'X.Y.Z+meta'.
    Gibt Tuple (major, minor, patch, pre) zurück, vergleichbar mit sort()."""
    s = str(v).strip()
    # Pre-Release (-rc1, -beta2) abtrennen
    if "+" in s:
        s = s.split("+", 1)[0]
    pre = ""
    if "-" in s:
        s, pre = s.split("-", 1)
    parts = s.split(".")
    nums = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    # pre-release: leer ist "höher" als jeder pre-release-String
    return (nums[0], nums[1], nums[2], pre)


def is_newer(remote, local):
    """True wenn remote > local."""
    return parse_version(remote) > parse_version(local)


def is_compatible(remote_manifest, local):
    """True wenn local >= manifest.min_compatible_from."""
    min_v = remote_manifest.get("min_compatible_from", "0.0.0")
    return parse_version(local) >= parse_version(min_v)


def download(url, dest_path, timeout=30):
    """Lädt URL nach dest_path. Wirft urllib.error bei Problemen."""
    req = urllib.request.Request(url, headers={"User-Agent": "hotel-display-updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f)


def verify_sha256(path, expected):
    """Prüft SHA256 einer Datei. expected = hex string."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    return actual.lower() == expected.lower(), actual


def verify_gpg_signature(sig_path, data_path, key_id):
    """Verifiziert GPG-Clearsign-Signatur mit `gpg --verify`."""
    # gpg gibt 0 = gültig zurück. Wir prüfen auch stderr auf WARNINGS.
    proc = subprocess.run(
        ["gpg", "--verify", str(sig_path), str(data_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False, f"gpg exit {proc.returncode}: {proc.stderr.strip()}"
    # Optional: prüfen dass der richtige Key benutzt wurde
    if key_id:
        out = proc.stderr + proc.stdout
        if key_id not in out:
            return False, f"signiert mit anderem Key (erwartet {key_id})"
    return True, "ok"


def in_maintenance_window(now=None):
    """True wenn aktuelle Stunde im Wartungs-Window [start, end) liegt.
    Default 03:00–05:00. End ist exklusiv (05:00 = außerhalb)."""
    if os.environ.get("HOTEL_DISPLAY_UPDATE_FORCE") == "1":
        return True, "force"
    start = int(os.environ.get("HOTEL_DISPLAY_UPDATE_WINDOW_START", "3"))
    end = int(os.environ.get("HOTEL_DISPLAY_UPDATE_WINDOW_END", "5"))
    h = (now or datetime.now()).hour
    if start <= h < end:
        return True, f"{start:02d}-{end:02d}h"
    return False, f"{h:02d}h (außerhalb {start:02d}-{end:02d}h)"


def audit_log(action, version, details=""):
    """Schreibt einen Eintrag ins lokale audit_log (SQLite)."""
    try:
        import sqlite3
        db = sqlite3.connect(str(DB_PATH), timeout=5)
        db.execute("""
            CREATE TABLE IF NOT EXISTS updater_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                action TEXT NOT NULL,
                version TEXT,
                details TEXT
            )
        """)
        db.execute(
            "INSERT INTO updater_log (action, version, details) VALUES (?, ?, ?)",
            (action, version, details),
        )
        db.commit()
        db.close()
    except Exception as e:
        log("WARN", f"audit_log fehlgeschlagen: {e}")


def systemctl(*args):
    """Wrapper für systemctl-Aufruf, gibt (rc, stdout, stderr) zurück."""
    proc = subprocess.run(
        ["systemctl", *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ============================================================================
# Backup / Rollback
# ============================================================================

def make_backup(reason):
    """Erstellt ein Backup der überschreibbaren Komponenten. Gibt Backup-Pfad zurück."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = BACKUP_DIR / f"backup-{ts}"
    backup_root.mkdir(parents=True, exist_ok=True)

    for target in BACKUP_TARGETS:
        src = REPO_DIR / target
        if src.exists():
            dst = backup_root / target
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    # Marker-File mit Grund (immer UTF-8, auch wenn das System default latin-1 ist)
    (backup_root / "REASON.txt").write_text(f"{reason}\n", encoding="utf-8")
    log("INFO", f"Backup erstellt: {backup_root.relative_to(REPO_DIR)}")
    return backup_root


def restore_backup(backup_root):
    """Stellt ein Backup wieder her."""
    if not backup_root or not backup_root.exists():
        log("ERROR", f"Backup-Pfad existiert nicht: {backup_root}")
        return False
    log("INFO", f"Rollback aus {backup_root.relative_to(REPO_DIR)} ...")
    for target in BACKUP_TARGETS:
        src = backup_root / target
        if not src.exists():
            continue
        dst = REPO_DIR / target
        # Bestehende Version erst entfernen
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    log("INFO", "Rollback abgeschlossen")
    return True


def cleanup_old_backups():
    """Behält nur die letzten MAX_BACKUPS Verzeichnisse."""
    if not BACKUP_DIR.exists():
        return
    backups = sorted(
        [p for p in BACKUP_DIR.iterdir() if p.is_dir() and p.name.startswith("backup-")],
        key=lambda p: p.name,
        reverse=True,
    )
    for old in backups[MAX_BACKUPS:]:
        log("INFO", f"Entferne altes Backup: {old.name}")
        shutil.rmtree(old)


# ============================================================================
# Apply + Health-Check
# ============================================================================

def apply_update(tarball_path, version):
    """Entpackt Tarball über das Repo (überschreibt BACKUP_TARGETS)."""
    log("INFO", f"Entpacke {tarball_path.name} nach {REPO_DIR} ...")
    # --strip-components=0: Tarball enthält bereits Repo-Struktur ODER ist flach.
    # Wir prüfen beides und passen an.
    proc = subprocess.run(
        ["tar", "-tzf", str(tarball_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tarball listing fehlgeschlagen: {proc.stderr}")
    entries = proc.stdout.splitlines()
    has_top_dir = any("/" in e and e.split("/", 1)[0] not in BACKUP_TARGETS + ["requirements.txt", "VERSION"] for e in entries if e)

    # Wenn die oberste Ebene ein Verzeichnis ist (z.B. hotel-reception-display-1.1.0/),
    # entpacken wir nach tmp und kopieren dann manuell — vermeidet dass .git überschrieben wird.
    if has_top_dir and len(set(e.split("/", 1)[0] for e in entries if e)) == 1:
        log("INFO", "Tarball hat Top-Level-Verzeichnis — entpacke nach tmp und kopiere selektiv")
        with tempfile.TemporaryDirectory(prefix="hotel-update-") as tmp:
            tmp_path = Path(tmp)
            subprocess.run(
                ["tar", "-xzf", str(tarball_path), "-C", str(tmp_path)],
                check=True,
            )
            top_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
            src_root = top_dirs[0] if top_dirs else tmp_path
            for target in BACKUP_TARGETS:
                src = src_root / target
                if src.exists():
                    dst = REPO_DIR / target
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    elif dst.exists():
                        dst.unlink()
                    if src.is_dir():
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
    else:
        # Flacher Tarball — direkt nach REPO_DIR entpacken
        # Sicherheits-Check: KEIN ".." oder "/etc" etc. in Pfaden
        for e in entries:
            if e.startswith("/") or ".." in Path(e).parts:
                raise RuntimeError(f"unsicherer Pfad im Tarball: {e}")
        subprocess.run(
            ["tar", "-xzf", str(tarball_path), "-C", str(REPO_DIR)],
            check=True,
        )

    write_local_version(version)
    log("INFO", f"Apply abgeschlossen — VERSION={version}")


def reinstall_dependencies():
    """Pip install --upgrade -r requirements.txt im venv (idempotent)."""
    venv_pip = REPO_DIR / "venv" / "bin" / "pip"
    req_file = REPO_DIR / "requirements.txt"
    if not venv_pip.exists():
        log("WARN", "venv nicht gefunden — überspringe pip install")
        return
    if not req_file.exists():
        log("WARN", "requirements.txt nicht gefunden — überspringe pip install")
        return
    log("INFO", "Aktualisiere Python-Dependencies...")
    proc = subprocess.run(
        [str(venv_pip), "install", "-q", "-r", str(req_file)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pip install fehlgeschlagen: {proc.stderr}")
    log("INFO", "Python-Dependencies aktualisiert")


def restart_service():
    """Restartet den hotel-display Service."""
    log("INFO", f"Restarte {SERVICE_NAME}...")
    rc, out, err = systemctl("restart", SERVICE_NAME)
    if rc != 0:
        raise RuntimeError(f"systemctl restart failed: {err}")
    # Kurz warten
    time.sleep(2)
    rc, _, _ = systemctl("is-active", SERVICE_NAME)
    if rc != 0:
        raise RuntimeError(f"Service ist nach Restart nicht aktiv (rc={rc})")
    log("INFO", f"{SERVICE_NAME} ist aktiv")


def health_check(retries=5, delay=2):
    """Prüft ob der Service nach Update korrekt antwortet."""
    url = SERVICE_URL
    for i in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hotel-display-updater/1.0"})
            with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT_S) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                # JSON parsen
                body = resp.read()
                data = json.loads(body)
                if "items" not in data:
                    raise RuntimeError("Response fehlt 'items' Key")
                log("INFO", f"Health-Check OK ({len(data['items'])} items, Versuch {i}/{retries})")
                return True
        except Exception as e:
            log("WARN", f"Health-Check fehlgeschlagen (Versuch {i}/{retries}): {e}")
            if i < retries:
                time.sleep(delay)
    return False


# ============================================================================
# Hauptlogik
# ============================================================================

def fetch_and_verify_manifest(base_url, key_id):
    """Holt Manifest + Signatur und verifiziert beides. Gibt manifest dict zurück."""
    manifest_url = urljoin(base_url.rstrip("/") + "/", "manifest.json")
    sig_url = manifest_url + ".asc"

    log("INFO", f"Hole Manifest von {manifest_url}")
    with tempfile.TemporaryDirectory(prefix="hotel-manifest-") as tmp:
        tmp_path = Path(tmp)
        manifest_file = tmp_path / "manifest.json"
        sig_file = tmp_path / "manifest.json.asc"
        download(manifest_url, manifest_file, timeout=20)
        download(sig_url, sig_file, timeout=20)

        ok, msg = verify_gpg_signature(sig_file, manifest_file, key_id)
        if not ok:
            raise RuntimeError(f"GPG-Signatur ungültig: {msg}")

        try:
            manifest = json.loads(manifest_file.read_text())
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Manifest ist kein gültiges JSON: {e}")

    required = ["version", "tarball", "tarball_sha256"]
    for k in required:
        if k not in manifest:
            raise RuntimeError(f"Manifest fehlt Pflichtfeld: {k}")
    return manifest


def download_and_verify_tarball(manifest, base_url, target_path):
    """Lädt Tarball herunter und prüft SHA256."""
    url = urljoin(base_url.rstrip("/") + "/", manifest["tarball"])
    log("INFO", f"Lade Tarball von {url} ({manifest.get('size_bytes', '?')} bytes)")
    download(url, target_path, timeout=120)

    ok, actual = verify_sha256(target_path, manifest["tarball_sha256"])
    if not ok:
        target_path.unlink(missing_ok=True)
        raise RuntimeError(f"SHA256 mismatch: erwartet {manifest['tarball_sha256']}, erhalten {actual}")
    log("INFO", "SHA256 OK")


def main():
    parser = argparse.ArgumentParser(description="Hotel Display Updater")
    parser.add_argument("--check-only", action="store_true",
                        help="Nur prüfen ob Update verfügbar, nicht installieren")
    parser.add_argument("--force", action="store_true",
                        help="Wartungs-Window ignorieren")
    args = parser.parse_args()

    if args.force:
        os.environ["HOTEL_DISPLAY_UPDATE_FORCE"] = "1"

    base_url = os.environ.get("HOTEL_DISPLAY_UPDATE_URL", "").strip()
    key_id = os.environ.get("HOTEL_DISPLAY_UPDATE_KEY", "").strip()

    if not base_url:
        log("ERROR", "HOTEL_DISPLAY_UPDATE_URL ist nicht gesetzt — Update-Quelle unbekannt")
        audit_log("config_error", "-", "HOTEL_DISPLAY_UPDATE_URL fehlt")
        return 3
    if not key_id:
        log("ERROR", "HOTEL_DISPLAY_UPDATE_KEY ist nicht gesetzt — kann Manifest nicht verifizieren")
        audit_log("config_error", "-", "HOTEL_DISPLAY_UPDATE_KEY fehlt")
        return 3

    local_version = read_local_version()
    log("INFO", f"Lokale Version: {local_version}")

    # 1) Manifest holen + verifizieren
    try:
        manifest = fetch_and_verify_manifest(base_url, key_id)
    except Exception as e:
        log("ERROR", f"Manifest-Fetch fehlgeschlagen: {e}")
        audit_log("manifest_fetch_failed", "-", str(e)[:200])
        return 3

    remote_version = manifest["version"]
    log("INFO", f"Remote Version: {remote_version}")

    # 2) Versionsvergleich
    if not is_newer(remote_version, local_version):
        log("INFO", f"Bereits aktuell ({local_version}) — nichts zu tun")
        audit_log("up_to_date", local_version, f"remote={remote_version}")
        return 0

    log("INFO", f"Update verfügbar: {local_version} → {remote_version}")

    # 3) Kompatibilitäts-Check
    if not is_compatible(manifest, local_version):
        log("ERROR", f"Lokale Version {local_version} ist zu alt für Update auf {remote_version} (min: {manifest.get('min_compatible_from')})")
        audit_log("incompatible", local_version, f"remote={remote_version} min={manifest.get('min_compatible_from')}")
        return 3

    # 4) Wartungs-Window
    in_window, window_info = in_maintenance_window()
    if not in_window:
        log("INFO", f"Update gefunden, aber Wartungs-Window nicht aktiv ({window_info}) — später erneut prüfen")
        audit_log("deferred", local_version, f"window={window_info} remote={remote_version}")
        return 1

    log("INFO", f"Wartungs-Window aktiv ({window_info}) — starte Update")

    # 5) Backup
    backup = make_backup(reason=f"pre-update {local_version} → {remote_version}")

    # 6) Tarball laden + verifizieren
    with tempfile.TemporaryDirectory(prefix="hotel-tarball-") as tmp:
        tarball_path = Path(tmp) / manifest["tarball"]
        try:
            download_and_verify_tarball(manifest, base_url, tarball_path)
        except Exception as e:
            log("ERROR", f"Tarball-Download fehlgeschlagen: {e}")
            audit_log("download_failed", remote_version, str(e)[:200])
            return 3

        # 7) Apply
        try:
            apply_update(tarball_path, remote_version)
            reinstall_dependencies()
        except Exception as e:
            log("ERROR", f"Apply fehlgeschlagen: {e} — Rollback!")
            restore_backup(backup)
            reinstall_dependencies()
            try:
                restart_service()
            except Exception as e2:
                log("ERROR", f"Service-Restart nach Rollback fehlgeschlagen: {e2}")
            audit_log("apply_failed_rollback", remote_version, str(e)[:200])
            return 2

    # 8) Service-Restart + Health-Check
    try:
        restart_service()
    except Exception as e:
        log("ERROR", f"Service-Restart fehlgeschlagen: {e} — Rollback!")
        restore_backup(backup)
        try:
            restart_service()
        except Exception as e2:
            log("ERROR", f"Service-Restart nach Rollback fehlgeschlagen: {e2}")
        audit_log("restart_failed_rollback", remote_version, str(e)[:200])
        return 2

    if not health_check():
        log("ERROR", "Health-Check fehlgeschlagen — Rollback!")
        restore_backup(backup)
        try:
            restart_service()
        except Exception as e2:
            log("ERROR", f"Service-Restart nach Rollback fehlgeschlagen: {e2}")
        audit_log("health_failed_rollback", remote_version, "GET /items lieferte kein valides JSON")
        return 2

    # 9) Cleanup + Erfolgs-Log
    cleanup_old_backups()
    log("INFO", f"✅ Update erfolgreich: {local_version} → {remote_version}")
    audit_log("updated", remote_version, f"from={local_version}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("WARN", "Abbruch durch Signal")
        sys.exit(130)
    except Exception as e:
        log("ERROR", f"Unbehandelte Exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(3)
