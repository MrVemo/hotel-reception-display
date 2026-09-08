#!/bin/bash
# ============================================================
# Hotel Reception Display — Installer
# ============================================================
#
# Installiert das Display-Backend auf einem frischen Raspberry Pi
# OS Lite 64-bit. Setzt voraus:
#   - RPI ist im WLAN/LAN (SSH-Zugriff)
#   - User 'pi' existiert (oder per ROOT_USER konfigurierbar)
#   - Repository wurde geklont nach $INSTALL_DIR
#
# Aufruf:
#   curl -sL https://raw.githubusercontent.com/MrVemo/hotel-reception-display/main/installer/install.sh | bash
#
#   ODER lokal:
#   sudo bash installer/install.sh
#
# Umgebungsvariablen (optional):
#   HOTEL_DISPLAY_HOST     Default: 0.0.0.0
#   HOTEL_DISPLAY_PORT     Default: 5000
#   HOTEL_DISPLAY_SECRET   Session-Secret (default: zufälliger String)
#   HOTEL_DISPLAY_HTTPS    "true" für HTTPS-Cookies (nur hinter Reverse-Proxy)
#
# ============================================================

set -e

# --- Config-Defaults ---
REPO_DIR_DEFAULT="/home/pi/hotel-reception-display"
SERVICE_NAME="hotel-display"
SERVICE_USER="pi"
REQUIRED_PACKAGES="python3 python3-pip python3-venv"
PYTHON_MIN_VERSION="3.9"

# --- Root-Check ---
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Bitte als root ausführen (sudo bash $0)"
    exit 1
fi

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  Hotel Reception Display — Installer v1.0      ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# --- 1. Repo-Pfad bestimmen ---
if [ -n "$1" ]; then
    INSTALL_DIR="$1"
elif [ -d "$REPO_DIR_DEFAULT" ]; then
    INSTALL_DIR="$REPO_DIR_DEFAULT"
else
    echo "❌ Repository nicht gefunden in $REPO_DIR_DEFAULT"
    echo "   Bitte zuerst klonen: git clone https://github.com/MrVemo/hotel-reception-display.git"
    echo "   ODER Pfad als Argument: sudo $0 /pfad/zum/repo"
    exit 1
fi

echo "[1/7] Install-Verzeichnis: $INSTALL_DIR"

# --- 2. Python-Version prüfen ---
PYTHON_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ "$(printf '%s\n' "$PYTHON_VERSION" "$PYTHON_MIN_VERSION" | sort -V | head -1)" != "$PYTHON_MIN_VERSION" ]; then
    echo "❌ Python $PYTHON_MIN_VERSION+ erforderlich, gefunden: $PYTHON_VERSION"
    exit 1
fi
echo "[2/7] Python-Version OK: $PYTHON_VERSION"

# --- 3. System-Pakete installieren ---
echo "[3/7] Installiere System-Pakete..."
apt-get update -qq
apt-get install -y --no-install-recommends $REQUIRED_PACKAGES

# --- 4. Venv anlegen + Dependencies installieren ---
VENV_DIR="$INSTALL_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "[4/7] Erstelle Python venv in $VENV_DIR..."
    sudo -u $SERVICE_USER python3 -m venv "$VENV_DIR"
else
    echo "[4/7] venv existiert bereits: $VENV_DIR"
fi

echo "       Installiere Python-Pakete..."
sudo -u $SERVICE_USER "$VENV_DIR/bin/pip" install --upgrade pip -q
sudo -u $SERVICE_USER "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

# --- 5. Secret-Key generieren falls nicht gesetzt ---
ENV_FILE="/etc/default/hotel-display"
if [ ! -f "$ENV_FILE" ]; then
    echo "[5/7] Erstelle $ENV_FILE mit zufälligem Secret..."
    SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    cat > "$ENV_FILE" <<EOF
# Hotel Reception Display — Environment-Konfiguration
# Generiert von installer $(date '+%Y-%m-%d %H:%M:%S')

HOTEL_DISPLAY_HOST=0.0.0.0
HOTEL_DISPLAY_PORT=5000
HOTEL_DISPLAY_SECRET=$SECRET
HOTEL_DISPLAY_DB=$INSTALL_DIR/data/hotel-display.db
# HOTEL_DISPLAY_DEBUG=true
EOF
    chmod 600 "$ENV_FILE"
else
    echo "[5/7] $ENV_FILE existiert bereits, wird nicht überschrieben"
fi

# --- 6. systemd-Service installieren ---
echo "[6/7] Installiere systemd-Service..."
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
cp "$INSTALL_DIR/systemd/hotel-display.service" "$SERVICE_FILE"
chmod 644 "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME

# --- 6b. Updater-Service + Timer installieren (Phase 5) ---
UPDATER_ENV="/etc/default/hotel-display-updater"
if [ ! -f "$UPDATER_ENV" ]; then
    echo "       Erstelle $UPDATER_ENV (Updater-Konfiguration)"
    cat > "$UPDATER_ENV" <<EOF
# Hotel Reception Display — Updater-Konfiguration (Phase 5)
# Generiert von installer $(date '+%Y-%m-%d %H:%M:%S')
#
# HOTEL_DISPLAY_UPDATE_URL muss auf die Tailscale-URL des Docker-PC zeigen
# (z.B. https://100.64.1.5/updates). HOTEL_DISPLAY_UPDATE_KEY ist die GPG-Key-ID
# mit der das Manifest signiert wird — vor Inbetriebnahme den Public-Key
# importieren: gpg --import docker-pc-update-key.pub
#
# Wartungs-Window: 03:00–05:00 Uhr (Default). HOTEL_DISPLAY_UPDATE_FORCE=1
# überschreibt das Window (nur für manuelle Tests).
#
# HOTEL_DISPLAY_UPDATE_URL=https://100.x.y.z/updates
# HOTEL_DISPLAY_UPDATE_KEY=ABCD1234EF567890
# HOTEL_DISPLAY_UPDATE_WINDOW_START=3
# HOTEL_DISPLAY_UPDATE_WINDOW_END=5
# HOTEL_DISPLAY_UPDATE_FORCE=0
EOF
    chmod 600 "$UPDATER_ENV"
    echo "       ⚠️  $UPDATER_ENV angelegt — BITTE URL + GPG-Key eintragen!"
fi

UPDATE_SERVICE="/etc/systemd/system/hotel-update.service"
UPDATE_TIMER="/etc/systemd/system/hotel-update.timer"
cp "$INSTALL_DIR/systemd/hotel-update.service" "$UPDATE_SERVICE"
cp "$INSTALL_DIR/systemd/hotel-update.timer" "$UPDATE_TIMER"
chmod 644 "$UPDATE_SERVICE" "$UPDATE_TIMER"

systemctl daemon-reload
systemctl enable hotel-update.timer
systemctl start hotel-update.timer

echo "       Updater-Timer aktiv (alle 6h)"
echo ""

# --- 7. Service-Status prüfen ---
sleep 2
echo "[7/7] Service-Status:"
if systemctl is-active --quiet $SERVICE_NAME; then
    echo "       ✅ Service läuft"
else
    echo "       ❌ Service läuft NICHT — Logs:"
    journalctl -u $SERVICE_NAME -n 20 --no-pager
    exit 1
fi

# --- Abschluss ---
echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  ✅ Installation erfolgreich abgeschlossen       ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "📍 Installation:    $INSTALL_DIR"
echo "📍 Service-File:    $SERVICE_FILE"
echo "📍 Environment:     $ENV_FILE"
echo "📍 Logs:            sudo journalctl -u $SERVICE_NAME -f"
echo "📍 Display:         http://$(hostname -I | awk '{print $1}'):5000/"
echo ""
echo "🔑 Default-Login:   Code 0000 (Admin) — BITTE ÄNDERN unter /admin"
echo ""
echo "🔄 Updater (Phase 5):"
echo "   - Timer aktiv:    systemctl status hotel-update.timer"
echo "   - Manual-Check:   sudo systemctl start hotel-update.service"
echo "   - Force-Update:   HOTEL_DISPLAY_UPDATE_FORCE=1 sudo -E systemctl start hotel-update.service"
echo "   - Logs:           sudo journalctl -u hotel-update -f"
echo ""
echo "Nächste Schritte:"
echo "  1. Im Browser http://<Pi-IP>:5000/ öffnen"
echo "  2. Auf /admin neuen Admin mit eigenem Code anlegen"
echo "  3. Code 0000 deaktivieren"
echo "  4. Mitarbeiter-Codes verteilen"
echo "  5. (Phase 5) GPG-Public-Key vom Docker-PC importieren + $UPDATER_ENV ausfüllen"
echo ""
