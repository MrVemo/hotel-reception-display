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
