"""Tests fuer Employee-CRUD (/api/employees GET/POST/PATCH/DELETE).

Deckt ab:
- GET erfordert Login
- GET liefert alle aktiven Mitarbeiter per Default
- GET active_only=false liefert auch inaktive
- POST erfordert Login
- POST erfordert Admin (jeder-Mitarbeiter-anlegen waere ein Sicherheitsproblem)
- POST Validierung: Name pflicht, Code genau 4 Ziffern
- POST: doppelter Code → 409
- PATCH: Code-Update funktioniert, Duplikat wird verhindert
- DELETE: nicht-Admin → 403
- DELETE: self-delete → 400 (man kann sich nicht selbst loeschen)
- DELETE: nicht-existent → 404
- DELETE: Audit-Log
- generate-code liefert freien Code
- generate-code erfordert Login + Admin
"""
import db as db_module


# ===== GET /api/employees =====

def test_list_employees_requires_login(client):
    """Regression: GET ohne Login → 401."""
    resp = client.get("/api/employees")
    assert resp.status_code == 401


def test_list_employees_admin_only(regular_client):
    """REGRESSION: nur Admin darf Mitarbeiter listen — das ist Admin-Funktion."""
    resp = regular_client.get("/api/employees")
    assert resp.status_code == 403


def test_list_employees_admin_default_active_only(admin_client):
    """Default: nur aktive Mitarbeiter."""
    db = db_module.get_db()
    db.execute(
        "INSERT INTO employees (name, code, active, is_admin) VALUES (?, ?, 0, 0)",
        ("Inactive", "9999"),
    )
    db.commit()
    db.close()

    data = admin_client.get("/api/employees").get_json()
    names = [e["name"] for e in data["employees"]]
    assert "Admin" in names
    assert "Inactive" not in names


def test_list_employees_with_inactive(admin_client):
    """active_only=false zeigt auch inaktive."""
    db = db_module.get_db()
    db.execute(
        "INSERT INTO employees (name, code, active, is_admin) VALUES (?, ?, 0, 0)",
        ("Inactive Bob", "9998"),
    )
    db.commit()
    db.close()

    data = admin_client.get("/api/employees?active_only=false").get_json()
    names = [e["name"] for e in data["employees"]]
    assert "Inactive Bob" in names


# ===== POST /api/employees =====

def test_create_employee_requires_login(client):
    """Regression: POST ohne Login → 401."""
    resp = client.post("/api/employees", json={"name": "X", "code": "1111"})
    assert resp.status_code == 401


def test_create_employee_requires_admin(regular_client):
    """REGRESSION: nur Admin darf Mitarbeiter anlegen."""
    resp = regular_client.post("/api/employees", json={"name": "Anna2", "code": "1212"})
    assert resp.status_code == 403


def test_create_employee_admin_ok(admin_client):
    """Happy Path: Admin legt neuen Mitarbeiter an."""
    resp = admin_client.post("/api/employees", json={"name": "Bob", "code": "2345"})
    assert resp.status_code == 201
    assert resp.get_json()["ok"] is True
    assert isinstance(resp.get_json()["id"], int)


def test_create_employee_name_required(admin_client):
    """Leerer Name → 400."""
    resp = admin_client.post("/api/employees", json={"name": "", "code": "1111"})
    assert resp.status_code == 400


def test_create_employee_code_must_be_4_digits(admin_client):
    """Code muss genau 4 Ziffern sein."""
    # Zu kurz
    assert admin_client.post("/api/employees", json={"name": "X", "code": "12"}).status_code == 400
    # Zu lang
    assert admin_client.post("/api/employees", json={"name": "X", "code": "12345"}).status_code == 400
    # Buchstaben
    assert admin_client.post("/api/employees", json={"name": "X", "code": "abcd"}).status_code == 400


def test_create_employee_duplicate_code_rejected(admin_client):
    """Doppelter Code → 409 (Conflict).

    REGRESSION: das waere ein Login-Bug — zwei Mitarbeiter mit gleichem
    Code fuehren zu 'wer hat eingeloggt?'-Ambiguitaten."""
    admin_client.post("/api/employees", json={"name": "First", "code": "1234"})
    resp = admin_client.post("/api/employees", json={"name": "Second", "code": "1234"})
    assert resp.status_code == 409


def test_create_employee_audit_logged(admin_client):
    """create_employee wird im audit_log mitgeloggt."""
    admin_client.post("/api/employees", json={"name": "Audit-Emp", "code": "4321"})
    db = db_module.get_db()
    rows = db.execute(
        "SELECT details FROM audit_log WHERE action = 'create_employee'"
    ).fetchall()
    db.close()
    assert len(rows) == 1
    assert "Audit-Emp" in rows[0]["details"]


# ===== PATCH /api/employees/<id> =====

def test_update_employee_requires_admin(regular_client):
    """PATCH als non-Admin → 403."""
    db = db_module.get_db()
    db.execute(
        "INSERT INTO employees (name, code, active, is_admin) VALUES ('Eve', '5555', 1, 0)"
    )
    db.commit()
    db.close()
    resp = regular_client.patch("/api/employees/2", json={"name": "Eve2"})
    assert resp.status_code == 403


def test_update_employee_name(admin_client):
    """Admin kann Namen aendern."""
    create = admin_client.post("/api/employees", json={"name": "Original", "code": "1112"})
    emp_id = create.get_json()["id"]
    resp = admin_client.patch(f"/api/employees/{emp_id}", json={"name": "Updated"})
    assert resp.status_code == 200

    # Verifizieren
    data = admin_client.get("/api/employees?active_only=false").get_json()
    emp = next(e for e in data["employees"] if e["id"] == emp_id)
    assert emp["name"] == "Updated"


def test_update_employee_code_validates_format(admin_client):
    """PATCH mit ungueltigem Code → 400."""
    create = admin_client.post("/api/employees", json={"name": "X", "code": "1113"})
    emp_id = create.get_json()["id"]
    resp = admin_client.patch(f"/api/employees/{emp_id}", json={"code": "abc"})
    assert resp.status_code == 400


def test_update_employee_code_duplicate_rejected(admin_client):
    """PATCH auf bereits vergebenen Code → 409."""
    admin_client.post("/api/employees", json={"name": "First", "code": "1114"})
    create = admin_client.post("/api/employees", json={"name": "Second", "code": "1115"})
    emp2_id = create.get_json()["id"]
    # Versuch Code von First auf Second zu setzen
    resp = admin_client.patch(f"/api/employees/{emp2_id}", json={"code": "1114"})
    assert resp.status_code == 409


def test_update_employee_not_found(admin_client):
    """PATCH fuer nicht-existierende ID → 404."""
    resp = admin_client.patch("/api/employees/9999", json={"name": "X"})
    assert resp.status_code == 404


# ===== DELETE /api/employees/<id> =====

def test_delete_employee_requires_admin(regular_client):
    """DELETE als non-Admin → 403."""
    db = db_module.get_db()
    db.execute("INSERT INTO employees (name, code, active, is_admin) VALUES ('Eve', '6666', 1, 0)")
    db.commit()
    db.close()
    resp = regular_client.delete("/api/employees/2")
    assert resp.status_code == 403


def test_delete_employee_self_protection(admin_client):
    """REGRESSION: Admin kann sich nicht selbst loeschen → 400.

    Hintergrund: Wuerde der Admin sich selbst loeschen, waere nach dem
    naechsten Logout kein Admin-User mehr uebrig und das System waere
    ueber den Admin-Pfad nicht mehr wartbar."""
    # admin_client IST Admin (id=1)
    resp = admin_client.delete("/api/employees/1")
    assert resp.status_code == 400


def test_delete_employee_admin_can_delete_other(admin_client):
    """Admin kann andere Mitarbeiter loeschen."""
    create = admin_client.post("/api/employees", json={"name": "Doomed", "code": "1116"})
    emp_id = create.get_json()["id"]
    resp = admin_client.delete(f"/api/employees/{emp_id}")
    assert resp.status_code == 200

    # Nicht mehr in der Liste
    data = admin_client.get("/api/employees?active_only=false").get_json()
    assert not any(e["id"] == emp_id for e in data["employees"])


def test_delete_employee_not_found(admin_client):
    """DELETE fuer nicht-existente ID → 404."""
    resp = admin_client.delete("/api/employees/9999")
    assert resp.status_code == 404


def test_delete_employee_audit_logged(admin_client):
    """delete_employee wird im audit_log mitgeloggt."""
    create = admin_client.post("/api/employees", json={"name": "Goner", "code": "1117"})
    emp_id = create.get_json()["id"]
    admin_client.delete(f"/api/employees/{emp_id}")

    db = db_module.get_db()
    rows = db.execute(
        "SELECT details FROM audit_log WHERE action = 'delete_employee'"
    ).fetchall()
    db.close()
    assert len(rows) == 1
    assert "Goner" in rows[0]["details"]


# ===== POST /api/employees/generate-code =====

def test_generate_code_requires_admin(regular_client):
    """generate-code ist Admin-Funktion."""
    resp = regular_client.post("/api/employees/generate-code")
    assert resp.status_code == 403


def test_generate_code_returns_unique(admin_client):
    """generate-code liefert einen Code, der noch nicht vergeben ist."""
    # Bereits vergeben: 0000 (Admin)
    resp = admin_client.post("/api/employees/generate-code")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert len(data["code"]) == 4
    assert data["code"].isdigit()
    assert data["code"] != "0000"
