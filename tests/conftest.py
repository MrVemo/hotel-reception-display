"""Pytest conftest fuer hotel-reception-display Tests.

Stellt pro Test eine eigene, frische SQLite-DB in tmp_path bereit und
patcht db.DB_PATH vor dem Import der app-Module, damit die echte
data/hotel-display.db auf KEINEN Fall angetastet wird.
"""
import os
import sys
import pytest

# Sicherstellen dass src/ im Pfad ist (pytest findet sonst weder app noch db)
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# Eigene Test-Config VOR dem Import von app setzen
os.environ["HOTEL_DISPLAY_SECRET"] = "test-secret-not-for-production"

# db wird jetzt importiert; die echte DB_PATH wird ueberschrieben sobald
# die Fixture laeuft (per monkeypatch im selben Prozess).
import db as db_module  # noqa: E402


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Frische Flask-App pro Test mit eigener SQLite-DB in tmp_path.

    Die DB wird VOR dem App-Import initialisiert, weil db.DB_PATH eine
    Modul-Globale ist und get_db() sie direkt liest.
    """
    test_db = tmp_path / "test-hotel.db"
    test_uploads = tmp_path / "uploads"
    test_uploads.mkdir()
    # Realer Pfad zur DB (init_db akzeptiert sowohl str als auch Path)
    db_module.DB_PATH = str(test_db)
    db_module.init_db(path=str(test_db))

    # Jetzt erst die App importieren, damit app.config keinen Bezug zur
    # Produktion hat
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    # Auch fuer den app-Layer die DB-Pfade nochmal hart ueberschreiben
    monkeypatch.setattr(db_module, "DB_PATH", str(test_db))
    monkeypatch.setattr(app_module, "DEFAULT_DB_PATH", str(test_db))
    # UPLOADS_DIR auf tmp_path umbiegen — Tests duerfen NICHT das echte
    # data/uploads/-Verzeichnis beruehren (sonst koennten sie Branding-Logos
    # oder Config-Dateien aus Versehen ueberschreiben oder lesen).
    monkeypatch.setattr(app_module, "UPLOADS_DIR", test_uploads)
    # CONFIG_PATH auch auf tmp_path umbiegen — sonst liest load_branding_config()
    # die produktive data/config.json aus dem Repo und liefert stale Werte.
    test_config = tmp_path / "config.json"
    monkeypatch.setattr(app_module, "CONFIG_PATH", test_config)

    return app_module.app


@pytest.fixture()
def client(app):
    """Flask-Test-Client (kein Login)."""
    return app.test_client()


@pytest.fixture()
def admin_employee(app):
    """Default-Admin (Code 0000, von init_db angelegt) als Dict."""
    import db as db_module
    db = db_module.get_db()
    row = db.execute(
        "SELECT id, name, code, is_admin, active FROM employees WHERE code = ?",
        ("0000",)
    ).fetchone()
    db.close()
    return dict(row)


@pytest.fixture()
def admin_client(app, admin_employee):
    """Test-Client der als Default-Admin eingeloggt ist (Code 0000)."""
    c = app.test_client()
    resp = c.post("/login", json={"code": "0000"})
    assert resp.status_code == 200 and resp.get_json()["ok"], (
        f"admin login failed: {resp.status_code} {resp.get_data(as_text=True)}"
    )
    return c


@pytest.fixture()
def regular_employee(app):
    """Legt einen nicht-Admin Mitarbeiter an, gibt (id, code) zurueck."""
    import db as db_module
    db = db_module.get_db()
    cursor = db.execute(
        "INSERT INTO employees (name, code, active, is_admin) VALUES (?, ?, 1, 0)",
        ("Anna", "1234"),
    )
    emp_id = cursor.lastrowid
    db.commit()
    db.close()
    return {"id": emp_id, "name": "Anna", "code": "1234", "is_admin": False}


@pytest.fixture()
def regular_client(app, regular_employee):
    """Test-Client der als non-Admin-Mitarbeiter 'Anna' (Code 1234) eingeloggt ist."""
    c = app.test_client()
    resp = c.post("/login", json={"code": regular_employee["code"]})
    assert resp.status_code == 200 and resp.get_json()["ok"]
    return c


@pytest.fixture()
def sample_item(admin_client):
    """Erstellt ein Item ueber die API als Admin. Gibt (id, dict) zurueck."""
    resp = admin_client.post("/items", json={"text": "Test-Item vom conftest"})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    item_id = resp.get_json()["id"]
    return {"id": item_id, "text": "Test-Item vom conftest"}
