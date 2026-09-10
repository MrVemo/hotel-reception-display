#!/usr/bin/env python3
"""
Manifest-Generator für Hotel-Display Updates.

Erzeugt signiertes Manifest + Tarball-Build für den Auto-Update-Mechanismus
(Phase 5). Läuft auf dem Docker-PC zuhause.

Was es macht:
    1. Repo klonen (oder nutzen wenn vorhanden)
    2. Git-Tag/Version bestimmen
    3. Tarball bauen (.tar.gz mit src/, systemd/, installer/, docs/)
    4. SHA256-Hash berechnen
    5. manifest.json schreiben (matched updater.py-Format)
    6. manifest.json.asc signieren (gpg --detach-sign --armor)

Output:
    /opt/hotel-display-updates/
        manifest.json
        manifest.json.asc
        v1.1.0.tar.gz

Aufruf:
    python3 docker-pc/manifest-gen.py [VERSION]   # default: latest git tag
    python3 docker-pc/manifest-gen.py 1.1.0

Env-Vars:
    HOTEL_DISPLAY_REPO     Repo-Pfad          Default: /opt/hotel-display-source
    HOTEL_DISPLAY_OUTPUT   Output-Verzeichnis Default: /opt/hotel-display-updates
    HOTEL_DISPLAY_GPG_KEY  GPG-Key-ID         Default: hotel-display@yourdomain.de
    HOTEL_DISPLAY_BASE_URL Public-URL (für changelog_url)
"""

import os
import sys
import json
import shutil
import hashlib
import tarfile
import subprocess
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# --- Config ---
REPO_DIR = Path(os.environ.get('HOTEL_DISPLAY_REPO', '/opt/hotel-display-source'))
OUTPUT_DIR = Path(os.environ.get('HOTEL_DISPLAY_OUTPUT', '/opt/hotel-display-updates'))
GPG_KEY = os.environ.get('HOTEL_DISPLAY_GPG_KEY', 'hotel-display@yourdomain.de')
BASE_URL = os.environ.get('HOTEL_DISPLAY_BASE_URL', 'https://hotel-display.tail12345.ts.net/updates')

# Welche Pfade werden ins Tarball gepackt (relativ zu REPO_DIR)
TARBALL_TARGETS = [
    'src/',
    'systemd/',
    'installer/',
    'docs/SETUP.md',
    'docs/UPDATER.md',
    'docs/HARDWARE.md',
    'docs/API.md',
    'requirements.txt',
    'README.md',
    'CHANGELOG.md',
    'LICENSE',
    'VERSION',
]

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('manifest-gen')


def get_version(arg_version=None):
    """Bestimmt die zu bauende Version."""
    if arg_version:
        return arg_version.lstrip('v')
    # Letzten Git-Tag
    result = subprocess.run(
        ['git', 'describe', '--tags', '--abbrev=0'],
        cwd=REPO_DIR, capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0:
        return result.stdout.strip().lstrip('v')
    # Fallback: Datum
    return datetime.now().strftime('1.0.0-%Y%m%d')


def get_min_compatible():
    """Minimale Client-Version, die dieses Update akzeptiert."""
    return "1.0.0"


def build_tarball(version):
    """Baut v<version>.tar.gz mit den relevanten Pfaden."""
    tarball_name = f"v{version}.tar.gz"
    tarball_path = OUTPUT_DIR / tarball_name

    log.info(f"Baue Tarball: {tarball_path}")

    # Sicheres Tar schreiben (kein path-traversal möglich weil controlled)
    with tarfile.open(tarball_path, "w:gz") as tar:
        for target in TARBALL_TARGETS:
            src = REPO_DIR / target
            if not src.exists():
                log.warning(f"Überspringe fehlenden Pfad: {target}")
                continue
            # Mit arcname=target bleibt die Repo-Struktur erhalten
            tar.add(str(src), arcname=target)

    return tarball_path


def sha256_file(path):
    """Berechnet SHA256-Hash einer Datei."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(version, tarball_path, sha256):
    """Schreibt manifest.json im updater.py-Format."""
    manifest = {
        "version": version,
        "released_at": datetime.now(timezone.utc).isoformat(timespec='seconds'),
        "min_compatible_from": get_min_compatible(),
        "tarball": f"v{version}.tar.gz",
        "tarball_sha256": sha256,
        "size_bytes": tarball_path.stat().st_size,
        "changelog_url": f"{BASE_URL}/CHANGELOG.md",
        "gpg_key_id": GPG_KEY,
    }
    manifest_path = OUTPUT_DIR / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    log.info(f"Manifest geschrieben: {manifest_path}")
    return manifest_path


def sign_manifest(manifest_path):
    """Erstellt GPG-Detached-Signatur (.asc, ASCII-Armored)."""
    sig_path = manifest_path.with_suffix('.json.asc')
    try:
        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--armor',
             '--local-user', GPG_KEY,
             '--output', str(sig_path),
             '--detach-sign', str(manifest_path)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            log.error(f"GPG-Signatur fehlgeschlagen: {result.stderr}")
            return False
        log.info(f"Signatur geschrieben: {sig_path}")
        return True
    except FileNotFoundError:
        log.error("gpg nicht installiert — bitte 'sudo apt install gnupg'")
        return False


def cleanup_old_releases(keep=5):
    """Löscht alte Tarballs, behält die letzten N."""
    tarballs = sorted(OUTPUT_DIR.glob('v*.tar.gz'), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in tarballs[keep:]:
        log.info(f"Lösche altes Release: {old.name}")
        old.unlink()


def main():
    log.info("=== Hotel-Display Manifest-Generator ===")

    if not REPO_DIR.exists():
        log.error(f"Repo nicht gefunden: {REPO_DIR}")
        log.error("Bitte zuerst klonen: git clone <repo-url> " + str(REPO_DIR))
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    version = get_version(sys.argv[1] if len(sys.argv) > 1 else None)
    log.info(f"Version: {version}")

    # 1. Tarball bauen
    tarball_path = build_tarball(version)
    size = tarball_path.stat().st_size
    log.info(f"Tarball-Größe: {size:,} bytes")

    # 2. SHA256
    sha = sha256_file(tarball_path)
    log.info(f"SHA256: {sha}")

    # 3. Manifest schreiben
    manifest_path = write_manifest(version, tarball_path, sha)

    # 4. Signieren
    if not sign_manifest(manifest_path):
        return 2

    # 5. Aufräumen (behalte letzte 5)
    cleanup_old_releases(keep=5)

    log.info("=== Fertig ===")
    log.info(f"Pi-Updater holt automatisch alle 6h von:")
    log.info(f"  {BASE_URL}/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
