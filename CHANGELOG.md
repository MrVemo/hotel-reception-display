# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### In Arbeit
- Backend-Phase 1: Flask + SQLite, Items-CRUD
- Hardware bestellt (Pi 4B 2GB + 7" Touch + Zubehör)

### Geplant
- Display-UI (Touch-fähig)
- Form-UI + Login-Code-Auth
- Installer-Script + systemd-Service
- ~~Admin-UI (Mitarbeiter-Verwaltung)~~ → erledigt
- ~~Update-Mechanismus (Tailscale + Manifest)~~ → erledigt

### Hinzugefügt (Frontend-Split)
- Neue responsive Web-Variante `src/templates/display_web.html`
  - Optimiert für PC/Handy/Tablet (Grid-Layout, responsive Breakpoints)
  - Login via 4-stelligem Code in `<input type="password">` (kein Touch-Keyboard)
  - Items als Karten-Grid mit Checkbox + Löschen-Button (kein Swipe)
  - Polling: Items 5s, Network-Info 60s, Branding 30s
  - Live-Branding-Reload via `/api/branding` (Admin ändert Farben → Web sieht es sofort)
  - Toast-Notifications für Aktionen
  - Bestätigungs-Dialog vor Löschen
  - Tab-Sichtbarkeit: Refresh bei Rückkehr zum Tab
  - Sort-Auswahl wird in `localStorage` gemerkt
- Neue Route `GET /display-web` in `src/app.py` (nutzt dieselbe API wie Kiosk)
- Erweiterter Root-Redirect `/?view=display|form|admin|web` für explizite Wahl
- Link vom Kiosk-Header (`🌐 Web`) und Web-Footer (`Kiosk-Anzeige`) für einfaches Wechseln

## [0.1.0] - 2026-09-08

### Hinzugefügt
- Phase 5: Auto-Update-Mechanismus (`src/updater.py`)
  - Signiertes Manifest via GPG-Detached-Signatur
  - SHA256-verifizierter Tarball-Download
  - Backup + Apply + Auto-Rollback bei Fehler
  - Wartungs-Window 03:00–05:00 Uhr (konfigurierbar)
  - Health-Check via GET /items nach Service-Restart
  - Audit-Log in SQLite-DB (Tabelle `updater_log`)
  - UTF-8 safe für alle Log-/Datei-Operationen
- systemd-Timer `hotel-update.timer` (alle 6h)
- systemd-Service `hotel-update.service` (einmaliger Lauf)
- `VERSION`-Datei (1.0.0) als Update-Quelle
- `docs/UPDATER.md` mit Docker-PC-Setup, Build-Script, Tailscale-Anleitung, Fehlerbehebung
- `installer/install.sh` installiert Updater-Units automatisch mit

## [0.0.1] - 2026-09-08

### Hinzugefügt
- README.md mit Projekt-Übersicht
- LICENSE (MIT)
- .gitignore für Python/Secrets
- docs/ Ordner-Struktur
- Initiale Projekt-Planung im SKILL.md
