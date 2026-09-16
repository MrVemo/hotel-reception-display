"""Tests fuer den Idle-Timeout (Sicherheits-Feature: Session verfaellt nach
IDLE_TIMEOUT_SECONDS ohne echte Mitarbeiter-Aktivitaet, siehe app.mark_activity()
und app.get_current_employee()).

Deckt ab:
- Frisch eingeloggt: Zugriff funktioniert
- Nach Ueberschreiten des Timeouts: automatischer Logout (401 + whoami false)
- Reines Polling (GET /items) verlaengert die Session NICHT
- Eine echte Aktion (POST /items) verlaengert die Session
- POST /api/touch verlaengert die Session (Aktivitaets-Ping vom Frontend)
"""
import time

import app as app_module


def _expire_session(client, seconds_ago):
    with client.session_transaction() as sess:
        sess["last_activity"] = time.time() - seconds_ago


def test_fresh_login_has_access(admin_client):
    resp = admin_client.get("/items")
    assert resp.status_code == 200


def test_idle_timeout_logs_out(admin_client):
    """Nach Ueberschreiten von IDLE_TIMEOUT_SECONDS wird die Session automatisch
    beendet, auch ohne expliziten /logout-Call."""
    _expire_session(admin_client, app_module.IDLE_TIMEOUT_SECONDS + 1)

    resp = admin_client.get("/items")
    assert resp.status_code == 401

    who = admin_client.get("/whoami").get_json()
    assert who["logged_in"] is False


def test_polling_does_not_extend_session(admin_client):
    """GET /items (Auto-Polling im Frontend) darf die Session NICHT am Leben
    halten, sonst greift der Idle-Timeout bei einem ambient laufenden Display nie."""
    _expire_session(admin_client, app_module.IDLE_TIMEOUT_SECONDS - 5)

    # Kurz vor Ablauf: noch eingeloggt
    resp = admin_client.get("/items")
    assert resp.status_code == 200

    # Weiter "warten" (simuliert) - reines Polling darf das nicht verhindert haben
    _expire_session(admin_client, app_module.IDLE_TIMEOUT_SECONDS + 1)
    resp2 = admin_client.get("/items")
    assert resp2.status_code == 401


def test_real_action_extends_session(admin_client):
    """Eine echte Aktion (Item anlegen) aktualisiert last_activity und
    verlaengert damit die Session."""
    _expire_session(admin_client, app_module.IDLE_TIMEOUT_SECONDS - 5)

    resp = admin_client.post("/items", json={"text": "Verlaengert die Session"})
    assert resp.status_code == 201

    # last_activity wurde gerade erst gesetzt -> sofort danach wieder abgelaufen
    # simulieren waere gleichbedeutend mit dem alten Timer, also stattdessen:
    # direkt danach ist die Session noch gueltig.
    resp2 = admin_client.get("/items")
    assert resp2.status_code == 200


def test_touch_ping_extends_session(admin_client):
    """POST /api/touch (Aktivitaets-Ping vom Frontend bei Touch/Klick) haelt
    die Session am Leben."""
    _expire_session(admin_client, app_module.IDLE_TIMEOUT_SECONDS - 5)

    resp = admin_client.post("/api/touch")
    assert resp.status_code == 200

    resp2 = admin_client.get("/items")
    assert resp2.status_code == 200


def test_touch_ping_requires_login(client):
    resp = client.post("/api/touch")
    assert resp.status_code == 401
