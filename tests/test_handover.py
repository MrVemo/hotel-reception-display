"""Tests fuer Handover-Notizen (/api/handover GET/POST/DELETE).

Deckt ab:
- GET ist oeffentlich (kein Login) — das Log soll auch ohne Login lesbar sein
- POST erfordert Login, aber KEIN Admin
- POST auch als non-Admin erlaubt
- POST mit leerem Text → 400
- POST mit zu langem Text → 400
- GET liefert neueste zuerst
- GET ?limit=N begrenzt das Ergebnis
- DELETE erfordert Admin (Tippfehler-Korrekturen)
- DELETE als non-Admin → 403
- DELETE ohne Login → 401
- DELETE fuer nicht-existente ID → 404
- Audit-Log: create_handover und delete_handover werden mitgeloggt
"""
import db as db_module


# ===== GET /api/handover =====

def test_get_handover_public(client):
    """GET /api/handover ist oeffentlich lesbar — Log soll jeder sehen."""
    resp = client.get("/api/handover")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "notes" in data
    assert "count" in data


def test_get_handover_empty_initially(client):
    """Frische DB hat keine Notizen."""
    data = client.get("/api/handover").get_json()
    assert data["count"] == 0
    assert data["notes"] == []


def test_get_handover_newest_first(client, admin_client):
    """Notizen werden neueste-zuerst sortiert."""
    admin_client.post("/api/handover", json={"text": "Erste"})
    admin_client.post("/api/handover", json={"text": "Zweite"})
    admin_client.post("/api/handover", json={"text": "Dritte"})

    notes = client.get("/api/handover").get_json()["notes"]
    # Neueste zuerst → "Dritte" zuerst
    assert notes[0]["text"] == "Dritte"
    assert notes[-1]["text"] == "Erste"


def test_get_handover_limit(client, admin_client):
    """?limit=N begrenzt die Anzahl."""
    for i in range(5):
        admin_client.post("/api/handover", json={"text": f"Note {i}"})

    resp = client.get("/api/handover?limit=2")
    data = resp.get_json()
    assert data["count"] == 2


def test_get_handover_limit_bounded(client, admin_client):
    """?limit>500 wird auf 500 begrenzt (DoS-Schutz)."""
    resp = client.get("/api/handover?limit=10000")
    # Sollte nicht crashen, und count <= 500
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] <= 500


def test_get_handover_includes_employee_name(client, admin_client):
    """Notizen enthalten employee_name via JOIN."""
    admin_client.post("/api/handover", json={"text": "Mit Autor"})
    notes = client.get("/api/handover").get_json()["notes"]
    assert notes[0]["employee_name"] == "Admin"


# ===== POST /api/handover =====

def test_create_handover_requires_login(client):
    """Regression: POST ohne Login → 401."""
    resp = client.post("/api/handover", json={"text": "Anonymous"})
    assert resp.status_code == 401


def test_create_handover_any_employee_allowed(regular_client):
    """REGRESSION: POST ist fuer JEDEN eingeloggten Mitarbeiter erlaubt,
    nicht nur Admin. Wer das versehentlich zu Admin-only macht, schliesst
    Mitarbeiter vom Schicht-Handover aus."""
    resp = regular_client.post("/api/handover", json={"text": "Anna war hier"})
    assert resp.status_code == 201
    assert resp.get_json()["ok"] is True


def test_create_handover_empty_text_rejected(admin_client):
    """Leerer Text → 400."""
    resp = admin_client.post("/api/handover", json={"text": ""})
    assert resp.status_code == 400
    resp2 = admin_client.post("/api/handover", json={"text": "   "})
    assert resp2.status_code == 400


def test_create_handover_too_long_rejected(admin_client):
    """Mehr als 5000 Zeichen → 400."""
    long_text = "x" * 5001
    resp = admin_client.post("/api/handover", json={"text": long_text})
    assert resp.status_code == 400


def test_create_handover_at_limit_accepted(admin_client):
    """5000 Zeichen genau ist noch OK."""
    limit_text = "x" * 5000
    resp = admin_client.post("/api/handover", json={"text": limit_text})
    assert resp.status_code == 201


def test_create_handover_audit_logged(admin_client):
    """Regression: create_handover wird im audit_log mitgeloggt."""
    admin_client.post("/api/handover", json={"text": "Audit-Test"})
    db = db_module.get_db()
    actions = [r["action"] for r in db.execute(
        "SELECT action FROM audit_log WHERE action LIKE '%%handover%%'"
    ).fetchall()]
    db.close()
    assert "create_handover" in actions


# ===== DELETE /api/handover/<id> =====

def test_delete_handover_requires_login(client):
    """Regression: DELETE ohne Login → 401."""
    resp = client.delete("/api/handover/1")
    assert resp.status_code == 401


def test_delete_handover_requires_admin(regular_client):
    """REGRESSION: DELETE erfordert Admin-Rechte (Tippfehler-Korrekturen).
    Jeder-Mitarbeiter-darf-Loeschen waere ein Sicherheitsproblem — Notizen
    gehen sonst verloren."""
    # Erst eine Notiz anlegen
    c = regular_client
    create = c.post("/api/handover", json={"text": "Anna's Notiz"})
    assert create.status_code == 201
    note_id = create.get_json()["id"]

    # Versuch zu loeschen als non-Admin → 403
    resp = c.delete(f"/api/handover/{note_id}")
    assert resp.status_code == 403


def test_delete_handover_admin_can_delete(admin_client):
    """Admin darf loeschen."""
    create = admin_client.post("/api/handover", json={"text": "Tippfehler-Notiz"})
    note_id = create.get_json()["id"]
    resp = admin_client.delete(f"/api/handover/{note_id}")
    assert resp.status_code == 200

    # Notiz ist weg
    notes = admin_client.get("/api/handover").get_json()["notes"]
    assert not any(n["id"] == note_id for n in notes)


def test_delete_handover_not_found(admin_client):
    """DELETE fuer nicht-existierende ID → 404."""
    resp = admin_client.delete("/api/handover/9999")
    assert resp.status_code == 404


def test_delete_handover_audit_logged(admin_client):
    """Regression: delete_handover wird im audit_log mitgeloggt."""
    create = admin_client.post("/api/handover", json={"text": "Loeschen-Audit"})
    note_id = create.get_json()["id"]
    admin_client.delete(f"/api/handover/{note_id}")

    db = db_module.get_db()
    rows = db.execute(
        "SELECT action, details FROM audit_log WHERE action = 'delete_handover'"
    ).fetchall()
    db.close()
    assert len(rows) == 1
    assert f"#{note_id}" in rows[0]["details"]


# ===== Page-Route /handover =====

def test_handover_page_renders(client):
    """Die /handover-Seite (HTML) rendert fuer anonyme User."""
    resp = client.get("/handover")
    assert resp.status_code == 200
    assert b"bergabe" in resp.data or b"Handover" in resp.data
