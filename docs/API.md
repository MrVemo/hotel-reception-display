# API-Dokumentation

Wird in Phase 1 (Backend) erstellt. Folgt später.

## Geplante Endpoints

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/` | Display-UI (Touch) |
| GET | `/form` | Eingabe-Formular |
| GET | `/admin` | Mitarbeiter-Verwaltung |
| POST | `/login` | Mitarbeiter-Login (4-stelliger Code → Session) |
| GET | `/items` | Alle offenen Items (JSON) |
| POST | `/items` | Neuen Item anlegen |
| PATCH | `/items/{id}` | Item bearbeiten |
| POST | `/items/{id}/done` | Item abhaken |
| DELETE | `/items/{id}` | Item löschen |
| GET | `/audit` | Audit-Log abrufen |
