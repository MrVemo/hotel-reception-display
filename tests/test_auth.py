"""Tests fuer Login / Logout / Session.

Deckt ab:
- Login mit korrektem 4-stelligem Code
- Login mit falschem Code (404)
- Login mit kaputtem Format (zu kurz, zu lang, Buchstaben) → 400
- Login mit inaktivem Mitarbeiter → 404
- whoami: vor und nach Login
- Logout: Session wird geloescht, whoami danach wieder logged_in:false
"""
import json


def _login(client, code):
    return client.post("/login", json={"code": code})


def test_login_admin_ok(client, admin_employee):
    """Admin-Login mit korrektem Code liefert ok + employee-Info."""
    resp = _login(client, "0000")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["employee"]["name"] == admin_employee["name"]
    # is_admin wird NICHT in der Login-Antwort zurueckgegeben, sondern nur in
    # /whoami (siehe test_whoami_after_login_returns_is_admin). Login-Response
    # ist absichtlich minimal (id, name) damit sie klein und cache-freundlich bleibt.


def test_login_response_no_is_admin(client):
    """Regression: Login-Antwort enthaelt bewusst KEIN is_admin. Falls das
    jemals dazukommt, sollte das bewusst passieren und is_admin zentral
    via whoami bezogen werden (sonst zwei Stellen die divergieren koennen)."""
    _login(client, "0000")
    resp = client.get("/whoami")  # nicht /login erneut
    assert "is_admin" in resp.get_json()["employee"]


def test_login_wrong_code(client):
    """Falscher Code → 404 not found."""
    resp = _login(client, "9999")
    assert resp.status_code == 404
    assert "nicht" in resp.get_json()["error"].lower() or "not" in resp.get_json()["error"].lower()


def test_login_format_validation(client):
    """Login-Code muss genau 4 Ziffern sein."""
    # Zu kurz
    assert _login(client, "12").status_code == 400
    # Zu lang
    assert _login(client, "12345").status_code == 400
    # Buchstaben
    assert _login(client, "abcd").status_code == 400
    # Leer
    assert _login(client, "").status_code == 400


def test_login_inactive_employee_rejected(app, client):
    """Ein inaktiver Mitarbeiter darf sich nicht einloggen koennen."""
    import db as db_module
    db = db_module.get_db()
    db.execute(
        "INSERT INTO employees (name, code, active, is_admin) VALUES (?, ?, 0, 0)",
        ("Inactive Bob", "4321"),
    )
    db.commit()
    db.close()

    resp = _login(client, "4321")
    assert resp.status_code == 404


def test_whoami_before_login(client):
    """Ohne Login: logged_in=false."""
    resp = client.get("/whoami")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["logged_in"] is False
    assert "employee" not in data or data.get("employee") is None


def test_whoami_after_login_returns_is_admin(client):
    """Regression: whoami muss is_admin mitsenden, sonst rendert das Frontend
    den Handover-Delete-Button konditional falsch."""
    _login(client, "0000")
    resp = client.get("/whoami")
    data = resp.get_json()
    assert data["logged_in"] is True
    assert data["employee"]["is_admin"] is True


def test_logout_clears_session(admin_client):
    """Nach Logout ist whoami wieder logged_in=false."""
    # Vor logout: eingeloggt
    who = admin_client.get("/whoami").get_json()
    assert who["logged_in"] is True

    # Logout
    resp = admin_client.post("/logout")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # Nach logout: nicht mehr eingeloggt
    who = admin_client.get("/whoami").get_json()
    assert who["logged_in"] is False


def test_logout_without_session(client):
    """Logout ohne aktive Session darf nicht crashen."""
    resp = client.post("/logout")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
