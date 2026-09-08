# 🏨 Hotel Reception Display

Standalone Raspberry-Pi-Touch-Display für Hotel-Rezeptionen. Zeigt laufende Aufgaben live, Eintragen via Web-Formular vom Handy/PC oder direkt am Touch, 4-stellige Login-Codes zur Person-Zuordnung, Audit-Log, Auto-Update via Docker-PC zuhause über Tailscale-VPN.

## Use-Case

Rezeption-Mitarbeiter sehen **live** was im Hotel gerade läuft. Aufgaben werden über ein Web-Formular (vom Handy/PC im Hotel-WLAN oder direkt am Touch) eingetragen, mit Deadline und Personenzuordnung, abgehakte Items verschwinden vom Display. Audit-Log speichert wer wann was gemacht hat.

**Klassische Items:**
- `Zimmer 207: Handtücher fehlen`
- `Minibar Suite 312 leer`
- `Gast Maier will um 18:00 ausgecheckt`
- `Klimaanlage Flur 2.OG piept seit 14:30`

## Features (v1.0)

- ✅ Items mit optionaler Deadline (Datum + Uhrzeit, Default "heute 18:00")
- ✅ Person-Zuordnung via 4-stellige Login-Codes (Admin-verwaltet)
- ✅ Audit-Log: Alle Aktionen werden mit Timestamp + Person gespeichert
- ✅ Touch-Bedienung: Abhaken + Sort-Toggle + Wischen-Lösch-Geste
- ✅ Sort-Toggle: Dringlichkeit ↔ Neueste zuerst
- ✅ Standalone im Hotel-LAN (kein Cloud-Sync nötig)
- ✅ Auto-Update via Tailscale-VPN zu Docker-PC zuhause (signiertes Manifest)
- ✅ Installation in Wartungs-Window (03–05 Uhr) mit Auto-Rollback

## Hardware

| Komponente | Spec | Preis ca. |
|---|---|---|
| Raspberry Pi 4B | 2GB RAM | ~58€ |
| Offizielles 7" Touch Display | 800×480, kapazitiv | ~72€ |
| microSD-Karte | 32GB A1 (SanDisk Extreme) | ~22€ |
| USB-C Netzteil | 5,1V / 3,0A | ~8€ |
| Gehäuse | offizielles 7" Display + Pi 4 | ~13€ |
| Kühlkörper-Set | für Pi 4 | ~2€ |
| **Gesamt** | | **~175€** |

## Architektur

```
[Rezeption-Mitarbeiter] → [Web-Formular im Hotel-WLAN] → [Flask Backend auf RPI] → [SQLite DB]
                                  ↓
                          [Touch-Display am RPI] ← live updates
                                  ↓
                          [Audit-Log: alle Aktionen]

[Update-Flow]:
[Docker-PC (Heim) via Tailscale] → [Manifest-Check alle 6h] → [Installation 03-05 Uhr]
```

## Software-Stack

- **OS:** Raspberry Pi OS Lite 64-bit
- **Backend:** Python Flask
- **Datenbank:** SQLite (lokal auf RPI)
- **Frontend:** Vanilla JS + CSS (kein Build-Step)
- **Display-Renderer:** Chromium Kiosk-Mode via X-Server
- **Update-Mechanismus:** systemd-Timer + Tailscale-VPN + signiertes Manifest

## Projekt-Struktur

```
hotel-reception-display/
├── README.md             # dieses File
├── LICENSE               # MIT
├── CHANGELOG.md          # Version-History
├── docs/                 # weiterführende Docs
│   ├── HARDWARE.md       # Bezugsquellen, BOM
│   ├── SETUP.md          # Installation, Konfiguration
│   └── API.md            # Backend-API
├── src/                  # Python Source
│   ├── app.py            # Flask Backend (Phase 1)
│   ├── db.py             # SQLite Setup
│   └── updater.py        # Update-Mechanismus
├── systemd/              # Service-Files
│   ├── hotel-display.service
│   └── hotel-update.{service,timer}
└── installer/
    └── install.sh        # One-Liner-Install
```

## Build-Phasen

| Phase | Inhalt | Status |
|---|---|---|
| 1 | Backend (Flask + SQLite, Items-CRUD) | ✅ Done |
| 2 | Display-UI (Touch-fähig) | ✅ Done |
| 3 | Form-UI + Login-Code-Auth | ✅ Done |
| 4 | Installer-Script + systemd-Service | ✅ Done |
| 5 | Update-Mechanismus (Tailscale + Manifest) | ⏳ Geplant |
| 6 | Admin-UI (Mitarbeiter-Verwaltung) | ✅ Done |
| 7 | Test + Refactor | 🔄 Optional |

## 🚀 Quick-Install

Auf dem Pi (einmalig):

```bash
git clone https://github.com/MrVemo/hotel-reception-display.git
cd hotel-reception-display
sudo bash installer/install.sh
```

Fertig — Service läuft auf `http://<Pi-IP>:5000/`. Default-Login: `0000` (Admin).

Vollständige Anleitung: [docs/SETUP.md](docs/SETUP.md).

## Lizenz

MIT — siehe [LICENSE](LICENSE)

## Status

✅ **Phase 4 abgeschlossen** — Display ready für Hotel-Deployment, wartet auf Hardware.
