# Setup-Anleitung

Wird in Phase 4 (Installer-Script) erstellt. Folgt später.

## Voraussetzungen

- Raspberry Pi 4B mit Raspberry Pi OS Lite 64-bit
- microSD-Karte mit Raspberry Pi OS (via Raspberry Pi Imager geflasht)
- SSH-Zugang (in Imager aktivieren + WLAN-Config)
- Tailscale-Account (für Update-Mechanismus)
- Optional: Docker-PC als Update-Server

## Schritte (geplant)

1. Hardware zusammenbauen
2. Pi first-boot, SSH + WLAN + Tailscale einrichten
3. Repo clonen + Installer-Script laufen lassen
4. Display anschließen + Chromium-Kiosk testen
5. Erste Items eintragen + abhaken

## Wartung

- **Updates:** Automatisch via Tailscale-VPN (Docker-PC Manifest, alle 6h Check, Installation 03–05 Uhr)
- **Backups:** SQLite-DB wird täglich auf USB-Stick gesichert
- **Logs:** systemd journal, einfach abrufbar
