#!/bin/bash
# ============================================================
# Hotel Reception Display — Status / Wartung
# ============================================================
# Quick-Health-Check + nützliche Wartungs-Kommandos.
# ============================================================

SERVICE_NAME="hotel-display"
REPO_DIR="/home/pi/hotel-reception-display"
DB_PATH="$REPO_DIR/data/hotel-display.db"

# --- Farben ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $1${NC}"; }
fail() { echo -e "${RED}❌ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  Hotel Reception Display — Status              ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# --- Service ---
if systemctl is-active --quiet $SERVICE_NAME; then
    ok "Service $SERVICE_NAME läuft"
else
    fail "Service $SERVICE_NAME läuft NICHT"
    echo "        → sudo systemctl start $SERVICE_NAME"
fi

if systemctl is-enabled --quiet $SERVICE_NAME; then
    echo "       Auto-Start: enabled"
else
    warn "Auto-Start: disabled → sudo systemctl enable $SERVICE_NAME"
fi

# --- DB ---
if [ -f "$DB_PATH" ]; then
    SIZE=$(du -h "$DB_PATH" | awk '{print $1}')
    ITEMS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM items" 2>/dev/null || echo "?")
    USERS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM employees" 2>/dev/null || echo "?")
    AUDITS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM audit_log" 2>/dev/null || echo "?")
    ok "DB gefunden: $SIZE"
    echo "       Items: $ITEMS | Mitarbeiter: $USERS | Audit-Log-Einträge: $AUDITS"
else
    warn "DB nicht gefunden: $DB_PATH"
fi

# --- Disk-Space ---
DISK_FREE=$(df -h "$REPO_DIR" | tail -1 | awk '{print $4}')
echo "       Freier Speicher: $DISK_FREE"

# --- Memory ---
MEM_TOTAL=$(free -h | awk '/Mem:/ {print $2}')
MEM_USED=$(free -h | awk '/Mem:/ {print $3}')
echo "       RAM: $MEM_USED / $MEM_TOTAL"

# --- Netzwerk ---
IP=$(hostname -I | awk '{print $1}')
PORT=5000
if ss -tln | grep -q ":$PORT "; then
    ok "Port $PORT offen — http://$IP:$PORT/"
else
    fail "Port $PORT nicht offen"
fi

# --- Letzte Logs ---
echo ""
echo "─── Letzte Logs (letzte 5 Zeilen): ───"
journalctl -u $SERVICE_NAME -n 5 --no-pager 2>/dev/null | tail -5 || echo "  (keine Logs)"

# --- Audit-Statistik ---
if [ -f "$DB_PATH" ] && command -v sqlite3 &> /dev/null; then
    echo ""
    echo "─── Letzte 10 Audit-Einträge: ───"
    sqlite3 "$DB_PATH" "SELECT datetime(ts, 'localtime') || ' | ' || (SELECT name FROM employees WHERE id = a.employee_id) || ' | ' || action || ' | ' || IFNULL(details,'') FROM audit_log a ORDER BY ts DESC LIMIT 10" 2>/dev/null | head -10
fi

echo ""
echo "─── Quick-Commands: ───"
echo "  systemctl restart $SERVICE_NAME   # Service neustarten"
echo "  systemctl stop $SERVICE_NAME       # Service stoppen"
echo "  journalctl -u $SERVICE_NAME -f     # Live-Logs"
echo "  tail -f $REPO_DIR/data/*.log       # App-Logs"
echo ""
