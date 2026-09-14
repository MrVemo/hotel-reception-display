"""Tests fuer Branding-Save (/api/branding POST/GET/reset).

Deckt ab:
- GET /api/branding ist oeffentlich (kein Login noetig)
- POST /api/branding erfordert Login
- POST erfordert Admin-Rechte (Regression: nicht-Admin → 403)
- POST updated nur die uebergebenen Felder, andere bleiben unveraendert
  (REGRESSION: das war Bug aus 77caf8e — vorher hat api_set_branding
  data direkt an save_branding_config gegeben, was vorhandene Felder
  geloescht hat, weil data nur die POST-Felder enthielt)
- Logo-URL wird automatisch aus logo_filename abgeleitet
- Cache-Buster (mtime) aendert sich wenn logo_filename gesetzt wird
- Reset stellt Defaults wieder her
"""
import json


# ===== GET /api/branding =====

def test_get_branding_public(client):
    """GET /api/branding ist oeffentlich (kein Login)."""
    resp = client.get("/api/branding")
    assert resp.status_code == 200
    data = resp.get_json()
    # Muss die Default-Felder enthalten
    for key in ["hotel_name", "primary_color", "logo_url"]:
        assert key in data


def test_get_branding_logo_url_default_none(client):
    """Default-Logo-URL ist None (kein Logo gesetzt)."""
    data = client.get("/api/branding").get_json()
    assert data["logo_url"] is None


# ===== POST /api/branding =====

def test_set_branding_requires_login(client):
    """Regression: POST ohne Login → 401."""
    resp = client.post("/api/branding", json={"hotel_name": "X"})
    assert resp.status_code == 401


def test_set_branding_requires_admin(regular_client):
    """Regression: POST als non-Admin → 403.

    Bug-Cluster dieser Session: Login-Check ohne Admin-Check war mehrfach
    ein Problem. Hier explizit als Test verankert."""
    resp = regular_client.post("/api/branding", json={"hotel_name": "Anna's Hotel"})
    assert resp.status_code == 403


def test_set_branding_updates_only_posted_fields(admin_client):
    """REGRESSIONSTEST fuer Bug 77caf8e (Branding-Save ueberschreibt Logo).

    Szenario: Hotel hat ein Logo. Admin speichert nur den Hotel-Namen.
    Erwartet: Hotel-Name ist neu, logo_filename und logo_url bleiben erhalten.

    Vorher (buggy code): save_branding_config(data) mit data={"hotel_name": ...}
    schrieb NUR hotel_name in die JSON-Datei → logo_filename weg.
    Fix in 77caf8e: config.update(data) statt save_branding_config(data).
    """
    # Setup: Admin loggt sich ein und setzt erst ein Logo
    set_logo = admin_client.post(
        "/api/branding",
        json={"logo_filename": "logo.png", "hotel_name": "Original"}
    )
    assert set_logo.status_code == 200

    # Logo-URL muss jetzt gesetzt sein
    before = admin_client.get("/api/branding").get_json()
    assert before["logo_filename"] == "logo.png"
    assert before["logo_url"] is not None
    assert before["logo_url"].startswith("/uploads/logo.png")

    # Aktion: Admin speichert NUR eine andere Farbe
    save = admin_client.post(
        "/api/branding",
        json={"primary_color": "#abcdef"}
    )
    assert save.status_code == 200

    # Erwartet: primary_color neu, logo_filename + hotel_name UNVERAENDERT
    after = admin_client.get("/api/branding").get_json()
    assert after["primary_color"] == "#abcdef"
    assert after["logo_filename"] == "logo.png", \
        "REGRESSION: logo_filename wurde geloescht (Bug 77caf8e ist zurueck)"
    assert after["hotel_name"] == "Original", \
        "REGRESSION: hotel_name wurde ueberschrieben"
    assert after["logo_url"] is not None


def test_set_branding_admin_can_update(admin_client):
    """Happy Path: Admin kann alle Branding-Felder updaten."""
    resp = admin_client.post("/api/branding", json={
        "hotel_name": "Willmersdorfer Hof",
        "primary_color": "#ff0000",
        "header_gradient_from": "#111111",
        "header_gradient_to": "#222222",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["config"]["hotel_name"] == "Willmersdorfer Hof"
    assert data["config"]["primary_color"] == "#ff0000"


# ===== Reset =====

def test_reset_branding_requires_login(client):
    """Regression: Reset ohne Login → 401."""
    resp = client.post("/api/branding/reset")
    assert resp.status_code == 401


def test_reset_branding_requires_admin(regular_client):
    """Regression: Reset als non-Admin → 403."""
    resp = regular_client.post("/api/branding/reset")
    assert resp.status_code == 403


def test_reset_branding_restores_defaults(admin_client):
    """Reset stellt die DEFAULT_BRANDING-Werte wieder her."""
    # Erst was setzen
    admin_client.post("/api/branding", json={"hotel_name": "Custom Name"})
    # Dann reset
    resp = admin_client.post("/api/branding/reset")
    assert resp.status_code == 200
    cfg = admin_client.get("/api/branding").get_json()
    # hotel_name sollte wieder dem Default entsprechen
    assert cfg["hotel_name"] != "Custom Name"


def test_reset_clears_logo_filename(admin_client):
    """Reset loescht auch logo_filename, sodass kein verwaistes logo_url uebrig bleibt."""
    admin_client.post("/api/branding", json={"logo_filename": "logo.png"})
    before = admin_client.get("/api/branding").get_json()
    assert before["logo_filename"] == "logo.png"

    admin_client.post("/api/branding/reset")
    after = admin_client.get("/api/branding").get_json()
    # logo_filename ist None (oder fehlt), logo_url ist None
    assert after.get("logo_filename") is None
    assert after["logo_url"] is None


# ===== Cache-Busting (logo_url mit mtime) =====

def test_logo_url_for_existing_file_contains_mtime(app, admin_client):
    """Regression: Wenn die Logo-Datei existiert, enthaelt logo_url den
    mtime-Query-Param fuer Cache-Busting.

    Hintergrund: Wenn ein neues Logo hochgeladen wird, muss sich die URL
    aendern damit Browser nicht das alte Bild cachen. Der mtime-Query-Param
    ist der Mechanismus dafuer.

    UPLOADS_DIR wird von der conftest auf tmp_path/uploads/ umgebogen,
    sodass wir ohne Bedenken eine Testdatei anlegen koennen.
    """
    import app as app_module
    uploads_dir = app_module.UPLOADS_DIR
    logo_path = uploads_dir / "logo.png"
    logo_path.write_bytes(b"fake-png-bytes")

    admin_client.post("/api/branding", json={"logo_filename": "logo.png"})
    cfg = admin_client.get("/api/branding").get_json()
    assert cfg["logo_url"].startswith("/uploads/logo.png")
    assert "?v=" in cfg["logo_url"], \
        f"logo_url sollte mtime-Query-Param enthalten, hat aber: {cfg['logo_url']!r}"
    # mtime-Wert sollte numerisch sein (Unix-Timestamp)
    version_str = cfg["logo_url"].split("?v=")[1]
    assert version_str.isdigit()
