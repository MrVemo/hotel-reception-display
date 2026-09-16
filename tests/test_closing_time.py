"""Tests fuer die konfigurierbare Sperrzeit (branding.closing_time).

Deckt ab:
- get_closing_lock_boundary(): Grenze heute vs. gestern je nach Uhrzeit,
  None wenn deaktiviert/ungueltig
- get_current_employee(): Session vor der Sperrzeit -> abgelaufen, nach der
  Sperrzeit (z.B. Nachtschicht-Login) -> weiterhin gueltig
- POST /api/branding validiert closing_time-Format
- Deaktivieren via leerem String hebt die Sperre wieder auf
"""
import time
from datetime import datetime

import app as app_module


class _FrozenDatetime:
    """Ersetzt app_module.datetime nur fuer die Dauer eines Tests -
    .now() liefert einen festen Zeitpunkt, alles andere (replace(), Vergleiche,
    Arithmetik mit timedelta) laeuft auf echten datetime-Objekten weiter."""
    _now = None

    @staticmethod
    def now(tz=None):
        return _FrozenDatetime._now


def _freeze(monkeypatch, when):
    """Friert app_module.datetime.now() UND time.time() auf denselben
    Zeitpunkt ein - sonst greift der IDLE_TIMEOUT-Check (echte Wanduhr) vor
    dem closing_time-Check und die Tests werden vom tatsaechlichen
    Testlauf-Datum abhaengig."""
    _FrozenDatetime._now = when
    monkeypatch.setattr(app_module, "datetime", _FrozenDatetime)
    monkeypatch.setattr(app_module.time, "time", lambda: when.timestamp())


# ===== get_closing_lock_boundary() =====

def test_boundary_none_when_disabled(app):
    app_module.save_branding_config({**app_module.load_branding_config(), "closing_time": ""})
    assert app_module.get_closing_lock_boundary() is None


def test_boundary_today_after_closing_time(app, monkeypatch):
    app_module.save_branding_config({**app_module.load_branding_config(), "closing_time": "22:00"})
    _freeze(monkeypatch, datetime(2026, 9, 16, 22, 30))
    boundary = app_module.get_closing_lock_boundary()
    assert boundary == datetime(2026, 9, 16, 22, 0)


def test_boundary_yesterday_before_closing_time(app, monkeypatch):
    """Um 8 Uhr morgens liegt die zuletzt ueberschrittene Sperrzeit noch am
    Vorabend (Nachtschicht-Logins von gestern Abend bleiben bis dahin gueltig)."""
    app_module.save_branding_config({**app_module.load_branding_config(), "closing_time": "22:00"})
    _freeze(monkeypatch, datetime(2026, 9, 16, 8, 0))
    boundary = app_module.get_closing_lock_boundary()
    assert boundary == datetime(2026, 9, 15, 22, 0)


# ===== get_current_employee() / require_login ueber HTTP =====

def test_session_before_closing_time_expires(admin_client, app, monkeypatch):
    """Auch bei durchgehender Aktivitaet (last_activity ganz frisch, Idle-
    Timeout greift NICHT) wird die Session zur Sperrzeit ungueltig, weil der
    Login (18 Uhr) vor der Sperrzeit (22 Uhr) lag - das ist der Unterschied
    zum reinen Idle-Timeout."""
    app_module.save_branding_config({**app_module.load_branding_config(), "closing_time": "22:00"})

    # Login lag vor der heutigen Sperrzeit, letzte Aktivitaet ist aber frisch
    with admin_client.session_transaction() as sess:
        sess["login_at"] = datetime(2026, 9, 16, 18, 0).timestamp()
        sess["last_activity"] = datetime(2026, 9, 16, 22, 29).timestamp()

    _freeze(monkeypatch, datetime(2026, 9, 16, 22, 30))

    resp = admin_client.get("/items")
    assert resp.status_code == 401

    who = admin_client.get("/whoami").get_json()
    assert who["logged_in"] is False


def test_session_after_closing_time_stays_valid(admin_client, app, monkeypatch):
    """Nachtschicht: Login NACH der Sperrzeit bleibt bis zur naechsten
    Sperrzeit gueltig (normaler Idle-Timeout gilt weiter)."""
    app_module.save_branding_config({**app_module.load_branding_config(), "closing_time": "22:00"})

    with admin_client.session_transaction() as sess:
        sess["login_at"] = datetime(2026, 9, 16, 23, 0).timestamp()
        sess["last_activity"] = datetime(2026, 9, 17, 0, 59).timestamp()

    _freeze(monkeypatch, datetime(2026, 9, 17, 1, 0))

    resp = admin_client.get("/items")
    assert resp.status_code == 200


def test_disabled_closing_time_never_expires_session(admin_client, app, monkeypatch):
    app_module.save_branding_config({**app_module.load_branding_config(), "closing_time": ""})

    with admin_client.session_transaction() as sess:
        sess["login_at"] = datetime(2020, 1, 1).timestamp()  # weit in der Vergangenheit
        sess["last_activity"] = time.time()  # Idle-Timeout separat davon nicht ueberschritten

    resp = admin_client.get("/items")
    assert resp.status_code == 200


# ===== POST /api/branding Validierung =====

def test_set_closing_time_valid(admin_client):
    resp = admin_client.post("/api/branding", json={"closing_time": "21:30"})
    assert resp.status_code == 200
    assert admin_client.get("/api/branding").get_json()["closing_time"] == "21:30"


def test_set_closing_time_empty_disables(admin_client):
    resp = admin_client.post("/api/branding", json={"closing_time": ""})
    assert resp.status_code == 200
    assert admin_client.get("/api/branding").get_json()["closing_time"] == ""


def test_set_closing_time_invalid_rejected(admin_client):
    for bad in ["25:00", "9:00", "abc", "22:60", "22"]:
        resp = admin_client.post("/api/branding", json={"closing_time": bad})
        assert resp.status_code == 400, f"{bad!r} haette abgelehnt werden muessen"
