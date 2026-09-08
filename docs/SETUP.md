# Setup & Deployment — Hotel Reception Display

Vollständige Anleitung zur Installation auf einem Raspberry Pi 4B.

## Inhaltsverzeichnis

1. [Voraussetzungen](#voraussetzungen)
2. [Pi-OS vorbereiten](#pi-os-vorbereiten)
3. [Hardware zusammenbauen](#hardware-zusammenbauen)
4. [Software installieren](#software-installieren)
5. [Display-Konfiguration (Chromium-Kiosk)](#display-konfiguration-chromium-kiosk)
6. [Tailscale für Updates](#tailscale-für-updates)
7. [Erstkonfiguration](#erstkonfiguration)
8. [Wartung & Updates](#wartung--updates)
9. [Troubleshooting](#troubleshooting)

## Voraussetzungen

- Raspberry Pi 4B (2GB RAM reicht)
- Raspberry Pi OS Lite 64-bit auf microSD geflasht
- SSH-Zugang (im Raspberry Pi Imager aktivieren)
- Tailscale-Account (für Update-Mechanismus — siehe Phase 5)
- Netzwerk im Hotel (WLAN oder LAN)
- Optional: Docker-PC als Update-Server

## Pi-OS vorbereiten

### Image flashen

Mit [Raspberry Pi Imager](https://www.raspberrypi.com/software/):

1. **OS:** `Raspberry Pi OS Lite (64-bit)` wählen
2. **Advanced Options** (Strg+Shift+X):
   - ✅ SSH aktivieren mit Passwort-Auth
   - ✅ WLAN konfigurieren (Hotel-WLAN-SSID + Passwort)
   - ✅ Username `pi` + eigenes Passwort setzen
   - ✅ Timezone: `Europe/Berlin`
3. Auf microSD-Karte schreiben

### Erster Boot & Update

```bash
ssh pi@<PI-IP>
sudo apt update && sudo apt upgrade -y
sudo reboot
```

Nach Reboot:

```bash
# Tailscale installieren (für späteren Update-Mechanismus)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

## Hardware zusammenbauen

1. **Kühlkörper** auf Pi-Chips kleben (CPU, RAM, USB-C, Ethernet)
2. **Pi** ins Display-Gehäuse einsetzen (offizielles 7" Case)
3. **Display-Flexkabel** an Pi-Display-Anschluss anschließen
4. **USB-C Netzteil** anschließen (5,1V/3,0A minimum)
5. Booten — wenn grüne LED blinkt und Display leuchtet, läuft's

> **Stromverbrauch:** ~6W kontinuierlich (Pi 4 + 7" Display im Idle)

## Software installieren

### Repository klonen

```bash
cd ~
git clone https://github.com/MrVemo/hotel-reception-display.git
cd hotel-reception-display
```

### Installer ausführen

```bash
sudo bash installer/install.sh
```

Der Installer führt automatisch aus:

1. ✅ System-Pakete (`python3`, `pip`, `venv`)
2. ✅ Python-virtuelle Umgebung anlegen
3. ✅ Dependencies installieren (`Flask` etc.)
4. ✅ `/etc/default/hotel-display` mit zufälligem Secret anlegen
5. ✅ systemd-Service installieren + aktivieren
6. ✅ Service-Neustart + Status-Check

**Erwartete Ausgabe:**

```
╔════════════════════════════════════════════════╗
║  ✅ Installation erfolgreich abgeschlossen       ║
╚════════════════════════════════════════════════╝
📍 Installation:    /home/pi/hotel-reception-display
📍 Display:         http://192.168.x.x:5000/
🔑 Default-Login:   Code 0000 (Admin)
```

### Manuell prüfen

```bash
sudo systemctl status hotel-display
sudo journalctl -u hotel-display -f    # Live-Logs
bash installer/status.sh               # Status-Dashboard
```

## Display-Konfiguration (Chromium-Kiosk)

Damit der 7"-Touchscreen direkt beim Boot das Display zeigt:

### Chromium installieren

```bash
sudo apt install -y chromium-browser unclutter
```

### Kiosk-Service

```bash
sudo nano /etc/systemd/system/hotel-kiosk.service
```

```ini
[Unit]
Description=Hotel Display — Chromium Kiosk
After=hotel-display.service
After=graphical.target
Wants=graphical.target

[Service]
User=pi
Environment=DISPLAY=:0
ExecStart=/usr/bin/chromium-browser \
  --noerrdialogs \
  --disable-infobars \
  --kiosk \
  --touch-events=enabled \
  http://localhost:5000/
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
```

```bash
sudo systemctl enable hotel-kiosk
sudo systemctl start hotel-kiosk
```

> **Hinweis:** Lite-OS hat keinen X-Server. Wenn Chromium-Kiosk gewünscht ist, **Raspberry Pi OS with desktop** verwenden (statt Lite).

## Tailscale für Updates

Der Update-Mechanismus (Phase 5) lädt neue Versionen vom Docker-PC zuhause über Tailscale-VPN.

Auf dem **Docker-PC**:

```bash
# Update-Verzeichnis + Manifest anlegen
sudo mkdir -p /opt/hotel-display-updates
cd /opt/hotel-display-updates

# GPG-Key für Manifest-Signatur
gpg --gen-key                              # Email: hotel-display@yourdomain.de
gpg --armor --export-secret-keys > /etc/gpg/hotel-display-sign.key  # nur offline!

# In env-File referenzieren
echo "GPG_SIGN_KEY_ID=<key-id>" | sudo tee -a /etc/default/hotel-display-server
```

Auf dem **Pi** (zusätzlich):

```bash
# Public-Key des Docker-PCs importieren
gpg --import docker-pc-public.key

# Update-Script triggern alle 6h (Phase 5)
```

Wird in **Phase 5: Update-Mechanismus** detailliert ausgearbeitet.

## Erstkonfiguration

Nach der Installation:

1. Im Browser: `http://<Pi-IP>:5000/` öffnen
2. Auf **Admin** klicken (oben rechts)
3. Mit **Code 0000** einloggen
4. **Default-Admin deaktivieren:**
   - Mitarbeiter "Admin" → ⏸️-Button → Status "inaktiv"
5. **Neuen Admin anlegen:**
   - Name: z.B. "Chefrezeption"
   - Code: 4 eigene Ziffern (z.B. 4711)
   - Optional: 🎲 Zufallscode-Generator
6. **Mitarbeiter anlegen** für alle Rezeptionisten:
   - Name + persönlicher 4-stelliger Code
7. **Codes an Mitarbeiter verteilen** (mündlich, niemals per Mail)

## Wartung & Updates

### Service-Befehle

```bash
sudo systemctl restart hotel-display    # Neustart
sudo systemctl stop hotel-display       # Stoppen (z.B. für Wartung)
sudo journalctl -u hotel-display -f     # Live-Logs
bash installer/status.sh                # Status-Dashboard
```

### Backup der DB

```bash
# Manuell
cp /home/pi/hotel-reception-display/data/hotel-display.db /tmp/backup-$(date +%Y%m%d).db

# Automatisch (via cronjob) — Phase 5 ergänzt das
```

### Updates einspielen

**Phase 5 (kommend):**
- Alle 6h Check via systemd-timer
- Wartungs-Window 03–05 Uhr
- Signiertes Manifest vom Docker-PC
- Automatischer Rollback bei Fehler

Bis dahin manuell:

```bash
cd ~/hotel-reception-display
git pull
sudo systemctl restart hotel-display
```

## Troubleshooting

### Service startet nicht

```bash
sudo journalctl -u hotel-display -n 50
```

Häufige Fehler:

| Fehler | Ursache | Lösung |
|---|---|---|
| `Address already in use` | Port 5000 belegt | `sudo lsof -i :5000` → Prozess beenden |
| `Permission denied: data/` | Rechte-Problem | `sudo chown pi:pi -R ~/hotel-reception-display/data` |
| `ModuleNotFoundError: flask` | venv nicht aktiv | `~/hotel-reception-display/venv/bin/pip install -r requirements.txt` |

### Touch-Display reagiert nicht

```bash
# Touch kalibrieren
sudo apt install -y xinput-calibrator
DISPLAY=:0 xinput_calibrator
```

### Updates kommen nicht an

```bash
# Tailscale-Status prüfen
sudo tailscale status
# Service-Logs checken
sudo journalctl -u hotel-display -f
```

### Komplett-Reset

```bash
sudo bash installer/uninstall.sh
sudo rm -rf /home/pi/hotel-reception-display
sudo rm -f /etc/default/hotel-display
# Danach SD-Karte neu flashen + installer erneut
```
