# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### In Arbeit
- Phase 7: Tests + Refactor (laufende pytest-Suite, siehe `tests/`)
- Memory-Vault-Layer für Audit-Log (Langzeit-Auswertungen)

### Geplant
- Multi-Hotel-Support (mehrere Branding-Profile parallel)
- Push-Notifications wenn ueberfaellige Items offen sind

## [1.1.0] - 2026-09-15

### Hinzugefügt
- **Schicht-Übergabe-Log (`/handover`, `/api/handover`)** — eigenstaendiges
  digitales Log fuer die Schichtuebergabe, komplett separat von den Items.
  Tabellenzeile `handover_notes` (id, employee_id FK, text, created_at).
  API: GET (oeffentlich, neueste zuerst), POST (jeder Mitarbeiter), DELETE
  (nur Admin fuer Tippfehler-Korrekturen). Audit-Log mit `create_handover`
  und `delete_handover`. UI: Touch-Template `handover.html` mit Login-Overlay
  + Composer-Textarea; Header-Button in Kiosk und Web.
- **Frontend-Split**: neues responsives Web-Template `display_web.html`
  fuer PC/Handy/Tablet. Nutzt dieselbe API wie der Kiosk (`/items`,
  `/whoami`, `/api/branding`, `/api/network`); pollt 5s/60s/30s.
  Root-Redirect akzeptiert jetzt `?view=display|form|admin|web`.
  Kiosk-Header hat Link "Web", Web-Footer hat Link "Kiosk-Anzeige".
- **Admin-Changelog-Tab**: dritter Tab im Admin-Panel neben
  "Mitarbeiter" und "Branding". Zeigt aktuelle Version (aus VERSION-File)
  und CHANGELOG.md als vorformatierten Text. Endpoint `GET /api/changelog`
  (Login-pflichtig).
- **Tests-Suite**: `tests/` mit pytest + pytest-flask, 88 Tests, eigene
  Test-DB in `tmp_path`, isolierte `UPLOADS_DIR` und `CONFIG_PATH`.
  Coverage: Auth, Items-CRUD, Branding-Save, Logo-Upload, Handover,
  Employee-CRUD, 404-Fallback (in-place via `tests/conftest.py`).
  Deckt mehrere Regressions-Bugs dieser Session ab (siehe Test-Kommentare).
- **`tests/conftest.py`-Isolation**: `UPLOADS_DIR` und `CONFIG_PATH`
  werden pro Test auf `tmp_path` umgebogen, damit Tests nicht das echte
  `data/uploads/` oder `data/config.json` beruehren.
- **`require_admin`-Decorator** in `app.py`: zentrale Admin-Pruefung
  fuer Endpoints die nur Admin duerfen. Setzt `require_login` voraus,
  liefert 401 ohne Login, 403 fuer non-Admin.
- **Permanentes Deploy-Script `kiko-display-deploy.sh`** auf dem
  Display-Pi (192.168.178.129): macht `git pull --ff-only` als
  `willmersdorferhof` + restart `hotel-display.service` + restart
  `hotel-kiosk.service` (try-restart, graceful skip wenn Unit fehlt).
  fail-fast bei divergierter Historie VOR dem Service-Restart.
  Entsprechende 4. Zeile in `/etc/sudoers.d/kiko-display-setup`
  (`visudo -c` parsed OK).

### Geaendert
- **Items-Deadline**: POST /items setzt heute+12h als Default wenn
  keine Deadline angegeben wird (vorher: kein Default, Item konnte ohne
  Deadline angelegt werden — Tests dokumentieren das jetzt explizit).
- **`/whoami`** liefert jetzt `is_admin` mit im Employee-Objekt, damit
  Frontend den Handover-Delete-Button konditional rendern kann.
- **Items-Sortierung**: GET /items sortiert ueberfaellige zuerst, dann
  frueheste Deadline zuerst, dann keine-Deadline zuletzt (war vorher
  nur nach Deadline ASC).

### Bugfixes
- **`delete_item` FK-Constraint-Fehler**: konnte erledigte Items nicht
  loeschen weil `audit_log.item_id -> items.id` mit RESTRICT.
  Fix: `UPDATE audit_log SET item_id = NULL WHERE item_id = ?` vor dem
  DELETE — Audit-History bleibt erhalten (Details-Spalte), Item-Referenz
  wird entkoppelt.
- **`/api/employees*`-Endpoints hatten nur Login-Check, keinen
  Admin-Check** (Sicherheitsluecke ueber mehrere Commits hinweg): jeder
  Mitarbeiter haette Mitarbeiter listen/anlegen/loeschen koennen.
  Fix: alle 5 Routes auf `@require_admin` umgestellt.
- **`/?view=display` Endlosschleife** in `index()`: redirect auf `/`
  ohne `view=` Param fuehrte bei Touch-UA wieder zu `/form`. Fix:
  direkt `render_template('display.html', ...)` statt redirect.
- **`form.html` "Zur Anzeige"-Link** zeigte auf `/?mode=display` (gibt's
  nicht, wurde stillschweigend ignoriert). Fix: auf `/display-web`
  umgebogen.
- **404-Fallback fuer Kiosk-Chromium** (kein Zurueck-Button):
  `/nope` o.ae. liefert HTML-Fehlerseite mit grossem Zurueck-Button +
  Auto-Redirect nach 5s, per `Accept`-Header-Detection (HTML fuer
  Browser-Navigation, JSON fuer API-Calls).
- **`api_set_branding` ueberschrieb Logo**: `save_branding_config(data)`
  mit POST-Body ohne `logo_filename` loeschte das Feld. Fix in 77caf8e
  via `config.update(data)` statt direktem Save.
- **Updater Security**: flacher Tarball-Pfad in `apply_update()` war
  ungefiltert (`tar -xzf ... -C REPO_DIR`). Fix: Pre-Check +
  Post-Extract-Cleanup auf `BACKUP_TARGETS`. Branding-Einstellungen
  ueberleben jetzt garantiert jeden Update-Pfad.
- **Cache-Busting fuer Logo-URLs**: `logo_url` enthaelt mtime als
  `?v=<timestamp>` Query-Param. Vermeidet dass Browser altes Logo
  nach Re-Upload cachen.
- **Login-Cookies `SameSite=Lax`** (war schon konfiguriert, hier explizit
  getestet damit Cross-Tab-Workflow `+ Neu` funktioniert).

### Lessons (diese Session)
1. **Tests sind die Lebendversicherung** fuer die ganze Bug-Geschichte
   der letzten 24h. Regressions-Tests als `Regression: ...` im Docstring
   markiert, damit der naechste Mensch sieht warum sie existieren.
2. **`data/uploads/` und `data/config.json` sind globaler State** den
   Tests beruehren koennen — `conftest.py`-Isolation per `tmp_path` ist
   nicht optional.
3. **Base64 decoded schrumpft um ~33%**, nicht expandiert. Tests die
   "10MB raw bytes" pruefen muessen einen ~14MB base64-String schicken.
4. **`sqlite3.Row` hat kein `.get()`** — bei Helper-Funktionen die
   sowohl dicts als auch Rows akzeptieren sollen: `dict(row)` casten
   oder explizit auf Index-Zugriff umstellen.
5. **Echte Test-Artefakte aufraeumen** (gestern: `data/uploads/logo.png`
   mit Inhalt `fake-png-bytes` lag noch rum). `.gitignore` checken ob
   `data/` richtig ausgeschlossen ist.

<!-- project: path:/home/pi/hotel-reception-display -->

## [1.0.0] - 2026-09-08

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
