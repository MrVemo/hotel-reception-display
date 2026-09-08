# Update-Mechanismus (Phase 5)

Auto-Update vom Hotel-RPI zum Docker-PC (Heim) über Tailscale-VPN. Signiertes
Manifest + Tarball-Download + Auto-Rollback bei Fehler.

## Überblick

| Komponente | Wo | Aufgabe |
|---|---|---|
| **Updater** | Hotel-RPI (`src/updater.py`) | Holt Manifest, prüft Signatur, lädt Tarball, apply + health-check |
| **systemd-Timer** | Hotel-RPI (`systemd/hotel-update.timer`) | Startet alle 6h; Installation nur 03:00–05:00 |
| **Update-Quelle** | Docker-PC (nginx + `/opt/hotel-display-updates/`) | Stellt signiertes Manifest + Tarballs bereit |
| **VPN** | Tailscale | RPI ↔ Docker-PC, kein offenes Port-Forwarding |

```
┌──────────────────────────┐         Tailscale-VPN          ┌────────────────────────┐
│  Hotel-RPI               │  ◄─────────────────────────►  │  Docker-PC (Heim)      │
│                          │   https://100.x.y.z/updates    │                        │
│  systemd-Timer (6h)      │                                │  nginx                 │
│    └─► updater.py        │   GET /manifest.json           │    └─ /updates/        │
│         ├ Manifest holen │   GET /manifest.json.asc       │       ├ manifest.json  │
│         ├ GPG prüfen     │   GET /v1.1.0.tar.gz           │       ├ manifest.asc   │
│         ├ Backup machen  │   GET /v1.1.0.tar.gz.sha256    │       └ v1.1.0.tar.gz  │
│         ├ Tarball holen  │                                │                        │
│         ├ Apply          │                                │  GPG-Signatur (clearsign)
│         ├ pip install    │                                │    manifest.json.asc   │
│         ├ Restart        │                                │                        │
│         └ Health-Check   │                                │  Build-Script:         │
│             │            │                                │  build-update.sh       │
│             ▼            │                                │                        │
│        OK / Rollback     │                                │                        │
└──────────────────────────┘                                └────────────────────────┘
```

## Wartungs-Window

- **Check alle 6h** (Timer): `OnBootSec=10min` + `OnUnitActiveSec=6h`
- **Installation nur 03:00–05:00 Uhr** (Default, in `/etc/default/hotel-display-updater` änderbar)
- **Manueller Override:** `HOTEL_DISPLAY_UPDATE_FORCE=1 systemctl start hotel-update.service`
- **Wartungs-Window prüfen:** `systemctl list-timers hotel-update.timer`

## Sicherheitsmodell

| Angriffsvektor | Mitigation |
|---|---|
| **Man-in-the-Middle** (Manifest wird auf dem Weg manipuliert) | GPG-Clearsign-Signatur über Manifest, RPI verifiziert mit importiertem Public-Key |
| **Gefälschter Tarball** | SHA256-Hash im (signierten!) Manifest, vor Apply verifiziert |
| **Tarball mit Schadcode** (z.B. `../../../etc/passwd`) | Tar-Pfade werden vor dem Entpacken auf `/` und `..` geprüft |
| **Böswilliges Update das Service kaputt macht** | Auto-Rollback: Backup vor Apply, bei Health-Check-Fehler zurückrollen |
| **Verlust von Datenbank** | Backup schließt `data/*.db` AUS (DB bleibt!), nur Code + Config + VERSION |
| **Offener Port im Hotel-Router** | Keiner — RPI ist nur Client, Tailscale macht outbound-Wireguard-Tunnel |
| **DNS-Spoofing auf Tailscale-IP** | Tailscale-PublicKey + Wireguard-KEX; nginx nutzt HTTPS mit eigenem Cert |

## Rollback-Strategie

Vor jedem Update:

1. Backup von `src/`, `systemd/`, `installer/`, `requirements.txt`, `VERSION` → `data/backups/updates/backup-YYYYMMDD-HHMMSS/`
2. Maximal **5 Backups** werden aufbewahrt, ältere automatisch gelöscht
3. `data/*.db` ist **nie** im Backup (Datensicherheit — Datenverlust wäre schlimmer als ein Rollback-Fail)

Bei Fehler (Apply, pip, Restart, Health-Check):

1. `rsync` Backup zurück über Repo-Pfade
2. `pip install -r requirements.txt` (idempotent)
3. `systemctl restart hotel-display`
4. Audit-Log-Eintrag `*_rollback`

**Manuelles Rollback:** einfach `data/backups/updates/backup-XXX/` auswählen und:

```bash
sudo systemctl stop hotel-display
sudo rsync -a /home/pi/hotel-reception-display/data/backups/updates/backup-20260908-1530/src/ \
              /home/pi/hotel-reception-display/src/
echo "0.9.0" | sudo tee /home/pi/hotel-reception-display/VERSION
sudo /home/pi/hotel-reception-display/venv/bin/pip install -r /home/pi/hotel-reception-display/requirements.txt
sudo systemctl start hotel-display
```

---

# RPI-Seite (Hotel)

## Voraussetzungen

- Phase 1–4 installiert (`install.sh` ist durchgelaufen)
- `systemctl status hotel-display` → active (running)
- Tailscale läuft (`tailscale status` zeigt eine 100.x.y.z IP)

## Setup

`install.sh` installiert Phase 5 automatisch mit — Timer wird aktiviert, systemd-units werden registriert. Du musst nur noch:

### 1. GPG-Public-Key vom Docker-PC importieren

```bash
# Auf dem Docker-PC: Public-Key exportieren (einmalig)
gpg --armor --export <KEY-ID> > docker-pc-update-key.pub
# Auf den RPI bringen (z.B. scp) und importieren:
gpg --import docker-pc-update-key.pub
# KEY-ID (letzte 16 Hex-Stellen der FPR) notieren
gpg --list-keys --with-colons | grep -E '^fpr:' | awk -F: '{print $10}' | tail -1
```

### 2. `/etc/default/hotel-display-updater` ausfüllen

```bash
sudo nano /etc/default/hotel-display-updater
```

Inhalt:

```bash
HOTEL_DISPLAY_UPDATE_URL=https://100.x.y.z/updates
HOTEL_DISPLAY_UPDATE_KEY=ABCD1234EF567890
HOTEL_DISPLAY_UPDATE_WINDOW_START=3
HOTEL_DISPLAY_UPDATE_WINDOW_END=5
HOTEL_DISPLAY_UPDATE_FORCE=0
```

(`100.x.y.z` = Tailscale-IP des Docker-PC, `ABCD1234EF567890` = GPG-Key-ID vom Docker-PC)

### 3. Timer manuell anstoßen zum Testen

```bash
# Status prüfen
systemctl list-timers hotel-update.timer
systemctl status hotel-update.timer
systemctl status hotel-update.service

# Manuell starten (wartet auf Wartungs-Window)
sudo systemctl start hotel-update.service

# Wartungs-Window ignorieren (force)
HOTEL_DISPLAY_UPDATE_FORCE=1 sudo systemctl start hotel-update.service

# Logs ansehen
sudo journalctl -u hotel-update -f
```

## Logs

```bash
# Live-Logs
sudo journalctl -u hotel-update -f

# Letzte 50 Zeilen
sudo journalctl -u hotel-update -n 50

# Nur Errors
sudo journalctl -u hotel-update -p err

# Audit-Log (in SQLite-DB)
sqlite3 /home/pi/hotel-reception-display/data/hotel-display.db \
    "SELECT ts, action, version, substr(details, 1, 60) FROM updater_log ORDER BY id DESC LIMIT 20;"
```

---

# Docker-PC-Seite (Heim)

## Verzeichnisstruktur

```
/opt/hotel-display-updates/
├── manifest.json              # aktuell (signiert)
├── manifest.json.asc          # GPG-Detached-Signatur (armored)
├── v1.0.0.tar.gz              # historische Versionen (für Rollback-Logs nicht nötig, aber nice-to-have)
├── v1.1.0.tar.gz
└── build-update.sh            # Build-Script (von dir manuell ausgeführt)
```

## nginx-vHost

```nginx
server {
    listen 443 ssl;
    server_name 100.x.y.z;  # Tailscale-IP

    ssl_certificate     /etc/nginx/ssl/tailscale-selfsigned.pem;
    ssl_certificate_key /etc/nginx/ssl/tailscale-selfsigned.key;

    # Nur GET, keine Uploads, keine Scripts
    location /updates/ {
        alias /opt/hotel-display-updates/;
        autoindex off;

        # Manifest darf nicht gecached werden (Tarballs schon)
        location ~* /updates/manifest\.json {
            add_header Cache-Control "no-store, max-age=0";
        }

        # Tarballs dürfen 1h gecached werden
        location ~* /updates/.*\.tar\.gz {
            add_header Cache-Control "public, max-age=3600";
        }
    }

    # Optional: Basic-Auth als zweite Schicht
    # auth_basic "Hotel Display Updates";
    # auth_basic_user_file /etc/nginx/.hotel-update-htpasswd;
}
```

## Build-Script (`/opt/hotel-display-updates/build-update.sh`)

```bash
#!/bin/bash
# ============================================================
# Hotel Display Update Builder — auf Docker-PC ausführen
# ============================================================
# Erzeugt ein Release-Tarball + signiertes Manifest für den Hotel-RPI.
#
# Voraussetzungen:
#   - GPG-Key für Updates vorhanden (gpg --list-keys)
#   - Repo lokal unter /home/claude/hotel-reception-display
#
# Aufruf:
#   ./build-update.sh 1.1.0
#
# ============================================================

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <version>"
    exit 1
fi

VERSION="$1"
REPO_DIR="/home/claude/hotel-reception-display"
OUT_DIR="/opt/hotel-display-updates"
KEY_ID="${HOTEL_UPDATE_GPG_KEY:-$(gpg --list-keys --with-colons | grep -E '^fpr:' | awk -F: '{print $10}' | tail -1)}"
WORK_DIR=$(mktemp -d)

echo "==> Version: $VERSION"
echo "==> GPG-Key: $KEY_ID"

# --- 1. Repo klonen in Work-Dir (clean, ohne dev-Files) ---
git clone --depth 1 "$REPO_DIR" "$WORK_DIR/hotel-reception-display-$VERSION"
cd "$WORK_DIR/hotel-reception-display-$VERSION"

# --- 2. Aufräumen: keine .git, keine venv, keine DBs ---
rm -rf .git venv __pycache__ src/__pycache__ data/*.db
echo "$VERSION" > VERSION

# --- 3. Tarball bauen ---
TARFILE="$OUT_DIR/v$VERSION.tar.gz"
tar -czf "$TARFILE" -C "$WORK_DIR" "hotel-reception-display-$VERSION"
echo "==> Tarball: $TARFILE ($(stat -c%s "$TARFILE") bytes)"

# --- 4. SHA256 berechnen ---
SHA=$(sha256sum "$TARFILE" | awk '{print $1}')

# --- 5. Manifest bauen ---
MANIFEST="$OUT_DIR/manifest.json"
cat > "$MANIFEST" <<EOF
{
    "version": "$VERSION",
    "released_at": "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)",
    "min_compatible_from": "1.0.0",
    "tarball": "v$VERSION.tar.gz",
    "tarball_sha256": "$SHA",
    "size_bytes": $(stat -c%s "$TARFILE"),
    "changelog_url": "https://github.com/MrVemo/hotel-reception-display/blob/v$VERSION/CHANGELOG.md",
    "gpg_key_id": "$KEY_ID"
}
EOF
echo "==> Manifest: $MANIFEST"
cat "$MANIFEST"

# --- 6. Manifest signieren (GPG-Detached-Signatur) ---
gpg --batch --yes --local-user "$KEY_ID" --armor --detach-sign --output "$MANIFEST.asc" "$MANIFEST"
mv "$MANIFEST.asc" "$OUT_DIR/manifest.json.asc"
echo "==> Signatur: $OUT_DIR/manifest.json.asc"

# --- 7. Aufräumen ---
rm -rf "$WORK_DIR"

echo ""
echo "✅ Release v$VERSION bereit."
echo "   RPI holt sich Manifest beim nächsten Timer-Lauf (max 6h) oder manuell:"
echo "     sudo systemctl start hotel-update.service"
```

**Wichtig:** Das Script exportiert `HOTEL_UPDATE_GPG_KEY=<KEY_ID>` in die Shell-Umgebung, oder es sucht sich den ersten verfügbaren Key.

## Update veröffentlichen — kompletter Workflow

```bash
# Auf Docker-PC
cd /home/claude/hotel-reception-display

# 1. Änderungen machen, committen, pushen
git commit -am "Phase 5: Auto-Updater"
git push

# 2. Version bumpen
echo "1.1.0" > VERSION
git add VERSION && git commit -m "Bump version to 1.1.0"
git tag v1.1.0
git push --tags

# 3. Tarball + Manifest bauen + signieren
HOTEL_UPDATE_GPG_KEY=<KEY-ID> /opt/hotel-display-updates/build-update.sh 1.1.0

# 4. RPI holt automatisch im Wartungs-Window (03–05 Uhr)
#    oder manuell:
#    ssh pi@<hotel-rpi-tailscale-ip> "sudo systemctl start hotel-update.service"

# 5. Logs prüfen
ssh pi@<hotel-rpi-tailscale-ip> "sudo journalctl -u hotel-update -n 30 --no-pager"
```

## Tailscale einrichten (einmalig)

```bash
# Auf Docker-PC (falls noch nicht)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Tailscale-Auth-Key generieren (in Tailscale-Admin-Console)
# https://login.tailscale.com/admin/settings/keys

# Auf Hotel-RPI:
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey=<TAILSCALE-AUTH-KEY>
sudo tailscale status  # sollte Docker-PC sehen
```

## Fehlerbehebung

| Symptom | Ursache | Fix |
|---|---|---|
| `HOTEL_DISPLAY_UPDATE_URL ist nicht gesetzt` | `/etc/default/hotel-display-updater` nicht ausgefüllt | URL + Key eintragen |
| `GPG-Signatur ungültig` | Public-Key nicht importiert ODER Manifest falsch signiert | `gpg --import docker-pc-update-key.pub`; auf Docker-PC Signatur prüfen |
| `SHA256 mismatch` | Tarball auf Server korrupt ODER Hash im Manifest falsch | `build-update.sh` neu laufen lassen |
| `Health-Check fehlgeschlagen` → Rollback | Service startet nicht ODER antwortet nicht | Logs: `journalctl -u hotel-display -n 50` |
| `Backup-Pfad existiert nicht` beim manuellen Rollback | Backup wurde aufgeräumt (MAX_BACKUPS=5) | Auf Git-Tag der gewünschten Version zurückrollen + neu deployen |
| `tar: unsicherer Pfad` | Tarball enthält absolute Pfade oder `..` | Build-Script prüfen; niemals beliebige Tarballs akzeptieren |
