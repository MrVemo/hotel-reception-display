#!/bin/bash
# ============================================================
# Hotel Reception Display — Uninstaller
# ============================================================
# Stoppt, deaktiviert und entfernt den Service. Datenbank und
# Installation bleiben erhalten (manuell zu löschen).
# ============================================================

set -e

SERVICE_NAME="hotel-display"

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Bitte als root ausführen (sudo bash $0)"
    exit 1
fi

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  Hotel Reception Display — Uninstaller         ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# --- Service stoppen + deaktivieren ---
if systemctl list-unit-files | grep -q "^$SERVICE_NAME.service"; then
    echo "[1/3] Stoppe Service..."
    systemctl stop $SERVICE_NAME 2>/dev/null || true
    systemctl disable $SERVICE_NAME 2>/dev/null || true
fi

# --- Service-File löschen ---
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
if [ -f "$SERVICE_FILE" ]; then
    echo "[2/3] Lösche $SERVICE_FILE..."
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
fi

# --- Env-File behalten (Backups sicher) ---
ENV_FILE="/etc/default/hotel-display"
echo "[3/3] Behalte $ENV_FILE (manuell löschen falls nicht mehr benötigt)"

# --- Pfad zur DB/Logs anzeigen falls Komplett-Löschung gewünscht ---
REPO_DIR="/home/pi/hotel-reception-display"
if [ -d "$REPO_DIR" ]; then
    echo ""
    echo "Um alles rückstandslos zu entfernen:"
    echo "  sudo rm -rf $REPO_DIR"
    echo "  sudo rm -f $ENV_FILE"
    echo "  sudo rm -rf /var/log/hotel-display  # falls Log-Dir existiert"
fi

echo ""
echo "✅ Uninstallation abgeschlossen"
