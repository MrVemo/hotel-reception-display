#!/bin/bash
# ============================================================
# Hotel Reception Display — WiFi-Setup-Fallback Installer
# ============================================================
#
# Installiert die System-Komponenten fuer den WLAN-Setup-Modus
# (Captive-Portal ueber die App, kein comitup/RaspAP noetig).
#
# WAS WIRD INSTALLIERT:
#   1. hostapd (Access-Point-Daemon)
#   2. dnsmasq (DHCP + DNS-Intercept fuer Captive-Portal)
#   3. /etc/hostapd/hostapd.conf — AP-Konfiguration (SSID, Kanal, Passwort)
#   4. /etc/dnsmasq.d/hotel-display.conf — DHCP-Range + DNS-Intercept
#   5. /usr/local/bin/hotel-display-wifi-fallback.sh — Logik-Skript
#   6. /etc/systemd/system/hotel-display-wifi-fallback.service — systemd-Service
#   7. /etc/hotel-display/wifi.json — persistente WLAN-Config (mode 0600)
#
# WIE ES FUNKTIONIERT:
#   Beim Boot laeuft hotel-display-wifi-fallback.service:
#     - Wenn wlan0 mit einem bekannten WLAN verbunden ist: AP bleibt aus,
#       Marker-File /run/hotel-display-setup-mode wird geloescht (falls da)
#     - Wenn KEIN bekanntes WLAN: AP geht an (ssid="hotel-display-setup"),
#       DHCP verteilt 192.168.50.2-30, DNS-Intercept leitet alle Domains
#       auf 192.168.50.1 → Captive-Portal /setup-wifi im Flask-Backend
#     - Wenn der User im Captive-Portal WLAN + Passwort eingibt: Flask
#       ruft nmcli, das Script loescht den Marker → App rendert wieder
#       den Kiosk-Display
#
# AUFZURUFEN ALS:
#   sudo bash installer/hotel-display-wifi-fallback-setup.sh
#
# BRAUCHT ROOT (apt install + systemweite Configs)
#
# HINWEIS FUER COMMANDER:
#   - Aktuell fest auf Commanders Heim-WLAN gepinnt — diese Aenderung
#     AENDERTS das nicht. Der Pi kommt erst ins Hotel-WLAN wenn dort
#     der Fallback-Modus zum ersten Mal zuschlaegt (kein bekanntes WLAN).
#   - Erweiterung der festen Paketliste in
#     /usr/local/bin/kiko-display-install-packages.sh ist optional
#     (kann spaeter passieren damit das Setup per kiko ausgefuehrt
#     werden kann — siehe TODO am Ende).
#
# ============================================================

set -e

# --- Root-Check ---
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Bitte als root ausfuehren (sudo bash $0)"
    exit 1
fi

# --- Konfiguration (anpassbar falls Hotel andere SSID/Kanaele will) ---
AP_SSID="hotel-display-setup"
AP_CHANNEL=7                  # 2.4 GHz, Kanal 7 (ueberlappungsfrei zu Kanal 1)
AP_IP="192.168.50.1"
AP_DHCP_START="192.168.50.10"
AP_DHCP_END="192.168.50.50"
AP_DHCP_LEASE="12h"
FALLBACK_SCRIPT="/usr/local/bin/hotel-display-wifi-fallback.sh"
SERVICE_FILE="/etc/systemd/system/hotel-display-wifi-fallback.service"
WIFI_CONFIG_DIR="/etc/hotel-display"
WIFI_CONFIG_FILE="$WIFI_CONFIG_DIR/wifi.json"

# User unter dem hotel-display.service laeuft (schreibt wifi.json zur Laufzeit).
# Default: 'willmersdorferhof' (auf dem produktiven Display-Pi).
# Ueberschreibbar per env: SERVICE_USER=pi sudo bash hotel-display-wifi-fallback-setup.sh
SERVICE_USER="${SERVICE_USER:-willmersdorferhof}"

# WPA2-Passphrase wird weiter UNTEN idempotent generiert — nur wenn
# /etc/hostapd/hostapd.conf noch NICHT existiert. Wenn doch, wird die
# bestehende Config (und damit das bestehende Passwort) unangetastet
# gelassen. Muster wie install.sh (ENV_FILE-Existenz-Check). Ueberschreibbar
# per env fuer reproduzierbare Erstinstallationen:
#   AP_PASSPHRASE=mein-test-passwort sudo bash hotel-display-wifi-fallback-setup.sh

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  Hotel Reception Display — WiFi-Fallback Installer     ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Konfiguration:"
echo "  AP-SSID:    $AP_SSID"
echo "  AP-Kanal:   $AP_CHANNEL (2.4 GHz)"
echo "  AP-IP:      $AP_IP"
echo "  DHCP-Range: $AP_DHCP_START - $AP_DHCP_END"
echo ""

# --- 1. Pakete installieren ---
echo "[1/5] Installiere hostapd + dnsmasq..."
apt-get update -qq
apt-get install -y --no-install-recommends hostapd dnsmasq

# --- 2. hostapd-Config (Access-Point) — IDEMPOTENT ---
# Wenn die Config schon existiert (Re-Run, Wartung, versehentliches
# Doppel-Ausfuehren): nicht ueberschreiben. Sonst riskieren wir dass
# das bestehende Passwort (das sich das Hotel-Personal notiert hat)
# ploetzlich nicht mehr stimmt → niemand kommt mehr in den Setup-AP.
# Muster analog zu install.sh ENV_FILE-Existenz-Check.
HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
if [ ! -f "$HOSTAPD_CONF" ]; then
    # Erstinstallation: Passphrase generieren falls env nicht ueberschreibt
    if [ -z "${AP_PASSPHRASE:-}" ]; then
        if command -v openssl >/dev/null 2>&1; then
            AP_PASSPHRASE=$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 12)
        else
            # Fallback falls openssl nicht da ist (z.B. minimal-Container)
            AP_PASSPHRASE=$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 12)
        fi
    fi
    echo "[2/5] Schreibe $HOSTAPD_CONF (neues Passwort generiert)..."
    cat > "$HOSTAPD_CONF" <<EOF
# Hotel Reception Display — Access-Point-Config
# Generiert von $(basename $0) am $(date '+%Y-%m-%d %H:%M:%S')

interface=wlan0
driver=nl80211
ssid=$AP_SSID
hw_mode=g
channel=$AP_CHANNEL
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0

# WPA2-PSK fuer den Setup-AP (sonst koennte jeder ohne Einwilligung mitmachen).
# Passphrase wird beim Installer-Lauf zufaellig generiert (siehe oben)
# — Repo ist public, kein hartcodiertes Default erlaubt.
wpa=2
wpa_passphrase=$AP_PASSPHRASE
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF
else
    # Bestehende Config → Passphrase NICHT ueberschreiben. Wir versuchen
    # das aktuelle Passwort aus der Config zu extrahieren damit die
    # Erfolgsmeldung am Ende den richtigen Wert zeigt — das ist nur
    # ein Lese-Zugriff, schreibt nichts.
    EXISTING_PASSPHRASE=$(grep '^wpa_passphrase=' "$HOSTAPD_CONF" | head -1 | cut -d'=' -f2-)
    if [ -n "$EXISTING_PASSPHRASE" ]; then
        AP_PASSPHRASE="$EXISTING_PASSPHRASE"
    fi
    echo "[2/5] $HOSTAPD_CONF existiert bereits, wird nicht ueberschrieben"
    echo "      (bestehendes Passwort bleibt aktiv — bitte notiert halten)"
fi
chmod 600 "$HOSTAPD_CONF"

# hostapd muss wissen wo seine Config liegt
if ! grep -q "^DAEMON_CONF" /etc/default/hostapd 2>/dev/null; then
    echo "DAEMON_CONF=/etc/hostapd/hostapd.conf" >> /etc/default/hostapd
fi
# Falls schon ein Eintrag da war, ueberschreiben
sed -i "s|^#DAEMON_CONF=.*|DAEMON_CONF=/etc/hostapd/hostapd.conf|" /etc/default/hostapd 2>/dev/null || true
sed -i "s|^DAEMON_CONF=.*|DAEMON_CONF=/etc/hostapd/hostapd.conf|" /etc/default/hostapd 2>/dev/null || true

# --- 3. dnsmasq-Config (DHCP + DNS-Intercept) ---
echo "[3/5] Schreibe /etc/dnsmasq.d/hotel-display.conf..."
# Falls dnsmasq standardmaessig laeuft, erstmal deaktivieren (wir starten
# es nur bei Bedarf aus dem Fallback-Service heraus, nicht dauerhaft).
systemctl stop dnsmasq 2>/dev/null || true
systemctl disable dnsmasq 2>/dev/null || true

cat > /etc/dnsmasq.d/hotel-display.conf <<EOF
# Hotel Reception Display — DHCP + DNS-Intercept
# Generiert von $(basename $0) am $(date '+%Y-%m-%d %H:%M:%S')

# DHCP-Server nur fuer wlan0 im AP-Modus
interface=wlan0
bind-interfaces
dhcp-range=$AP_DHCP_START,$AP_DHCP_END,$AP_DHCP_LEASE
dhcp-option=3,$AP_IP           # Gateway
dhcp-option=6,$AP_IP           # DNS (zeigt auf uns selbst)
domain-needed
bogus-priv
no-resolv

# Captive-Portal: alles auf unsere IP umleiten
# (Browser connecten sich nach Verbindung mit einem "WLAN"-HTTP-Endpoint,
#  wir antworten mit 200 auf /generate_204 wie Android es erwartet, ODER
#  wir leiten per DNS-Intercept ALLES auf unsere Flask-App um — wir machen
#  Variante 2, weil Flask eh /setup-wifi ausliefert)
address=/#/$AP_IP
EOF
chmod 644 /etc/dnsmasq.d/hotel-display.conf

# --- 4. Fallback-Script ---
echo "[4/5] Schreibe $FALLBACK_SCRIPT..."
cat > "$FALLBACK_SCRIPT" <<'FALLBACK_EOF'
#!/bin/bash
# Hotel Reception Display — WiFi-Fallback-Logik
# Wird vom hotel-display-wifi-fallback.service aufgerufen.
#
# Entscheidungslogik:
#   1. Wenn wlan0 mit einem bekannten WLAN verbunden (SSID in wifi.json ODER
#      aktuell verbunden mit nmcli-general.state activated): AP aus, Marker weg.
#   2. Sonst: AP an, DHCP/DNS an, Marker an.
#
# Bewusst KEIN endloser Loop — Service wird nach Boot EINMAL ausgefuehrt.

set -e

MARKER_FILE="/run/hotel-display-setup-mode"
WIFI_CONFIG="/etc/hotel-display/wifi.json"

is_connected() {
    # nmcli -t (terse) -f ACTIVE,SSID device wifi | grep -q '^yes:'
    # ACTIVE=yes heisst: verbunden mit irgendeinem WLAN
    nmcli -t -f ACTIVE,SSID device wifi 2>/dev/null | grep -q '^yes:'
}

# Marker-File sauber starten (alte Files loeschen)
rm -f "$MARKER_FILE"

if is_connected; then
    # Normal-Modus: AP aus
    echo "[wifi-fallback] WLAN aktiv — AP bleibt aus"
    systemctl stop hostapd 2>/dev/null || true
    systemctl stop dnsmasq 2>/dev/null || true
    exit 0
fi

# Setup-Modus: AP starten
echo "[wifi-fallback] Kein WLAN gefunden — starte Setup-AP '$AP_SSID'"

# IP auf wlan0 setzen (falls noch nicht da)
ip addr flush dev wlan0 2>/dev/null || true
ip addr add $AP_IP/24 dev wlan0 2>/dev/null || true
ip link set wlan0 up

# dnsmasq + hostapd starten
systemctl start dnsmasq 2>&1 || echo "(dnsmasq start fehlgeschlagen — vermutlich nicht installiert?)"
systemctl unmask hostapd 2>/dev/null || true
systemctl start hostapd 2>&1 || echo "(hostapd start fehlgeschlagen — siehe journal)"

# Marker setzen
touch "$MARKER_FILE"
chmod 644 "$MARKER_FILE"

echo "[wifi-fallback] Setup-Modus aktiv. Captive-Portal: $AP_IP"
FALLBACK_EOF
chmod 755 "$FALLBACK_SCRIPT"

# --- 5. systemd-Service ---
echo "[5/5] Schreibe $SERVICE_FILE..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Hotel Reception Display — WiFi-Setup-Fallback
# Hotel-Display-Service muss laufen damit Captive-Portal ausgeliefert wird
After=hotel-display.service
Wants=hotel-display.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$FALLBACK_SCRIPT

[Install]
WantedBy=multi-user.target
EOF
chmod 644 "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable hotel-display-wifi-fallback.service

# --- 6. WiFi-Config-Verzeichnis anlegen (fuer wifi.json) ---
mkdir -p "$WIFI_CONFIG_DIR"
if [ ! -f "$WIFI_CONFIG_FILE" ]; then
    echo '{"networks": []}' > "$WIFI_CONFIG_FILE"
fi
chmod 700 "$WIFI_CONFIG_DIR"
chmod 600 "$WIFI_CONFIG_FILE"

# WICHTIG: hotel-display.service laeuft NICHT als root, sondern als
# $SERVICE_USER. Ohne chown kriegt der Service beim /setup-wifi POST
# ein PermissionError und antwortet mit HTTP 500 (Bug vom 16.09.2026 —
# Commander hat den manuellen chown als Sofort-Fix auf dem aktuellen Pi
# gemacht, das hier verhindert dass es bei Neuinstallationen wieder
# passiert). Wir machen es BEVOR chmod, damit ein etwaiger 'chmod nach
# chown'-Fall klar bleibt.
if id "$SERVICE_USER" &>/dev/null; then
    chown -R "$SERVICE_USER:$SERVICE_USER" "$WIFI_CONFIG_DIR"
    echo "[6/6] Ownership gesetzt: $SERVICE_USER:$SERVICE_USER auf $WIFI_CONFIG_DIR"
else
    echo "⚠️  WARNUNG: User '$SERVICE_USER' existiert nicht auf diesem System."
    echo "    hotel-display.service wird beim /setup-wifi POST einen PermissionError"
    echo "    kriegen. Bitte manuell ausfuehren:"
    echo "      sudo chown -R <dein-service-user>: <$WIFI_CONFIG_DIR>"
    echo "    Oder Installer nochmal mit SERVICE_USER=<name> aufrufen."
fi

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ Installation erfolgreich                            ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Was JETZT passiert:"
echo "  • Der Service ist aktiviert aber noch NICHT gestartet"
echo "  • Beim naechsten Boot: wenn wlan0 mit WLAN verbunden → nichts passiert"
echo "  • Beim naechsten Boot: wenn wlan0 KEIN WLAN findet → AP '$AP_SSID' geht an"
echo ""
echo "Captive-Portal-WLAN-Passwort: $AP_PASSPHRASE"
echo "  ⚠️  BITTE NOTIEREN — Passwort steht in /etc/hostapd/hostapd.conf (chmod 600)"
echo "     und wird NUR hier einmalig angezeigt. Hotel-Mitarbeiter braucht es zum"
echo "     Verbinden mit dem Setup-AP '$AP_SSID' (oeffnen, PW eingeben, Captive-Portal)."
echo ""
echo "Manuell testen (vor Ort beim Hotel-Umzug):"
echo "  sudo systemctl start hotel-display-wifi-fallback.service"
echo "  # danach sollte 'nmcli device wifi' zeigen: AP '$AP_SSID' ist aktiv"
echo ""
echo "WLAN-PIN wieder loesen (= wieder Captive-Portal erzwingen):"
echo "  sudo systemctl stop hotel-display-wifi-fallback.service"
echo "  sudo nmcli connection down 'Heim-WLAN-SSID'    # Commanders aktuelles WLAN"
echo "  sudo systemctl start hotel-display-wifi-fallback.service"
echo ""
echo "TODO (fuer spaeter, nicht Teil dieses Setups):"
echo "  • /usr/local/bin/kiko-display-install-packages.sh erweitern um hostapd+dnsmasq"
echo "    damit der kiko-User das Setup remote ausfuehren kann"
echo "  • Erste WLAN-SSID nach Hotel-Umzug eintragen (siehe wifi.json)"
