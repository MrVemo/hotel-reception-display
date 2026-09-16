"""Tests fuer Items-CRUD (/items GET/POST/PATCH/DELETE/mark-done).

Deckt ab:
- POST erfordert Login (Regression: require_login-Decorator)
- POST legt Item mit korrektem Schema an
- POST mit leerem Text → 400
- POST mit Default-Deadline (heute 18:00) wenn nicht angegeben
- GET liefert nur offene Items, sortiert nach Deadline
- GET erfordert Login (Aufgaben sind kein oeffentliches Display mehr)
- PATCH erlaubt Text/Deadline/assigned_to zu aendern
- POST /items/<id>/done markiert als erledigt
- DELETE entfernt das Item
- DELETE erfordert Login
- Nach mark-done: GET liefert das Item nicht mehr
"""
import json


def test_create_item_requires_login(client):
    """Regression: POST /items ohne Login muss 401 liefern."""
    resp = client.post("/items", json={"text": "Sollte abgelehnt werden"})
    assert resp.status_code == 401


def test_create_item_minimal(admin_client):
    """Mit nur 'text' wird Item angelegt, Default-Deadline wird gesetzt."""
    resp = admin_client.post("/items", json={"text": "Minibar Suite 312 leer"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["id"], int)


def test_create_item_empty_text_rejected(admin_client):
    """Leerer Text → 400 (kein leeres Item)."""
    resp = admin_client.post("/items", json={"text": ""})
    assert resp.status_code == 400
    resp2 = admin_client.post("/items", json={"text": "   "})
    assert resp2.status_code == 400


def test_create_item_default_deadline_today(admin_client):
    """Wenn keine Deadline angegeben wird, wird Default 'heute + 12h' gesetzt."""
    resp = admin_client.post("/items", json={"text": "Mit Default-Deadline"})
    assert resp.status_code == 201
    item_id = resp.get_json()["id"]
    # GET und pruefen
    listing = admin_client.get("/items").get_json()
    item = next(i for i in listing["items"] if i["id"] == item_id)
    assert item["deadline"] is not None
    assert item["deadline_display"] is not None


def test_get_items_requires_login(client, sample_item):
    """GET /items ohne Login -> 401 (Aufgaben nur fuer eingeloggte Mitarbeiter sichtbar)."""
    resp = client.get("/items")
    assert resp.status_code == 401


def test_get_items_logged_in(admin_client, sample_item):
    """GET /items mit Login liefert die offenen Items."""
    resp = admin_client.get("/items")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "count" in data
    # sample_item muss enthalten sein
    assert any(i["id"] == sample_item["id"] for i in data["items"])


def test_get_items_excludes_done(admin_client):
    """Erledigte Items erscheinen NICHT in der offenen Liste."""
    create = admin_client.post("/items", json={"text": "Wird abgehakt"})
    item_id = create.get_json()["id"]

    # Vorher da
    listing = admin_client.get("/items").get_json()
    assert any(i["id"] == item_id for i in listing["items"])

    # Abhaken
    done = admin_client.post(f"/items/{item_id}/done")
    assert done.status_code == 200
    assert done.get_json()["ok"] is True

    # Nachher weg
    listing2 = admin_client.get("/items").get_json()
    assert not any(i["id"] == item_id for i in listing2["items"])


def test_mark_done_requires_login(client, sample_item):
    """Regression: Abhaken ohne Login → 401."""
    resp = client.post(f"/items/{sample_item['id']}/done")
    assert resp.status_code == 401


def test_mark_done_twice_is_400(admin_client):
    """Bereits erledigtes Item nochmal abhaken → 400."""
    create = admin_client.post("/items", json={"text": "Doppelt abhaken"})
    item_id = create.get_json()["id"]
    assert admin_client.post(f"/items/{item_id}/done").status_code == 200
    second = admin_client.post(f"/items/{item_id}/done")
    assert second.status_code == 400


def test_patch_updates_text(admin_client):
    """PATCH /items/<id> aktualisiert den Text."""
    create = admin_client.post("/items", json={"text": "Original"})
    item_id = create.get_json()["id"]
    resp = admin_client.patch(f"/items/{item_id}", json={"text": "Korrigiert"})
    assert resp.status_code == 200
    # Ueber GET verifizieren
    listing = admin_client.get("/items").get_json()
    item = next(i for i in listing["items"] if i["id"] == item_id)
    assert item["text"] == "Korrigiert"


def test_delete_item_hard_remove(admin_client):
    """DELETE /items/<id> entfernt das Item komplett."""
    create = admin_client.post("/items", json={"text": "Wird geloescht"})
    item_id = create.get_json()["id"]
    assert admin_client.delete(f"/items/{item_id}").status_code == 200

    # Auch nach done-mark darf DELETE noch funktionieren (Hard delete)
    create2 = admin_client.post("/items", json={"text": "Done + delete"})
    item_id2 = create2.get_json()["id"]
    admin_client.post(f"/items/{item_id2}/done")
    assert admin_client.delete(f"/items/{item_id2}").status_code == 200


def test_delete_requires_login(client, sample_item):
    """Regression: DELETE ohne Login → 401."""
    resp = client.delete(f"/items/{sample_item['id']}")
    assert resp.status_code == 401


def test_items_sorted_by_deadline_asc(admin_client):
    """Items werden nach Deadline sortiert: frueheste zuerst.

    Hinweis: Aktuell kann man Items nicht ohne Deadline anlegen — create_item()
    setzt als Default "heute + 12h" wenn deadline=None/leer. Der Test
    dokumentiert das bestehende Sortierverhalten ohne NULL-Deadline-Fall.
    """
    admin_client.post("/items", json={"text": "Spaet", "deadline": "2099-01-01 23:59"})
    admin_client.post("/items", json={"text": "Frueh", "deadline": "2026-01-01 08:00"})

    listing = admin_client.get("/items").get_json()
    items = listing["items"]
    # Frueheste Deadline zuerst
    assert items[0]["text"] == "Frueh"
    # Spaetere Deadline danach (egal welche Position, solange nach Frueh)
    assert items[1]["text"] == "Spaet"
    # Beide haben eine Deadline gesetzt
    assert items[0]["deadline"] is not None
    assert items[1]["deadline"] is not None


def test_create_item_default_deadline_when_none(admin_client):
    """Wenn deadline nicht (oder leer) angegeben wird, wird heute+12h
    als Default gesetzt — das ist der einzige Weg ein Item anzulegen."""
    resp = admin_client.post("/items", json={"text": "Default-Deadline"})
    assert resp.status_code == 201
    item_id = resp.get_json()["id"]
    listing = admin_client.get("/items").get_json()
    item = next(i for i in listing["items"] if i["id"] == item_id)
    assert item["deadline"] is not None

    # Auch leerer String wird als "kein Wert" behandelt → Default
    resp2 = admin_client.post("/items", json={"text": "Auch Default", "deadline": ""})
    assert resp2.status_code == 201


def test_create_assigns_created_by_current_user(admin_client):
    """Regression: created_by muss der eingeloggte User sein, nicht 0 oder NULL."""
    create = admin_client.post("/items", json={"text": "Wer-bin-ich"})
    item_id = create.get_json()["id"]
    listing = admin_client.get("/items").get_json()
    item = next(i for i in listing["items"] if i["id"] == item_id)
    # created_by_name kommt vom JOIN mit employees
    assert item["created_by_name"] == "Admin"


def test_audit_log_records_create_and_done(admin_client):
    """Regression: create_item und mark_done werden im audit_log geloggt."""
    import db as db_module
    create = admin_client.post("/items", json={"text": "Audit-Test"})
    item_id = create.get_json()["id"]
    admin_client.post(f"/items/{item_id}/done")

    db = db_module.get_db()
    actions = [r["action"] for r in db.execute(
        "SELECT action FROM audit_log WHERE item_id = ? ORDER BY ts", (item_id,)
    ).fetchall()]
    db.close()
    assert "create_item" in actions
    assert "mark_done" in actions
