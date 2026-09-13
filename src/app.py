"""
Flask Backend für Hotel Reception Display.

Endpoints:
- GET  /              → Display-UI (Touch, alle offenen Items)
- GET  /form          → Eingabe-Formular
- GET  /admin         → Mitarbeiter-Verwaltung
- POST /login         → Mitarbeiter-Login (4-stelliger Code)
- GET  /items         → Alle offenen Items als JSON
- POST /items         → Neues Item anlegen
- PATCH /items/<id>   → Item bearbeiten
- POST /items/<id>/done → Item abhaken
- DELETE /items/<id>  → Item löschen
- GET  /audit         → Audit-Log abrufen
- POST /logout        → Session beenden

Start:
    python3 app.py
    # → http://0.0.0.0:5000
"""

from flask import Flask, request, jsonify, session, render_template, render_template_string
from datetime import datetime, timedelta
import os
import json
from pathlib import Path

from db import (
    get_db, close_db, init_db, log_action,
    list_employees, get_employee, get_employee_by_code,
    create_employee, update_employee, delete_employee,
    generate_random_code
)

app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
            static_folder=os.path.join(os.path.dirname(__file__), 'static'))
app.secret_key = os.environ.get('HOTEL_DISPLAY_SECRET', 'dev-secret-change-in-prod')
app.config['JSON_SORT_KEYS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('HOTEL_DISPLAY_HTTPS', '').lower() in ('1', 'true', 'yes')


# ===== Branding-Config =====
CONFIG_PATH = Path(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'config.json'
))

DEFAULT_BRANDING = {
    "hotel_name": "Willmersdorfer Hof",
    "primary_color": "#3498db",
    "header_gradient_from": "#2c3e50",
    "header_gradient_to": "#34495e",
    "background_color": "#1a1a1a",
    "urgent_color": "#e74c3c",
    "overdue_color": "#c0392b",
    "done_color": "#27ae60"
}

def load_branding_config():
    """Lädt Branding-Config aus data/config.json. Fallback auf Defaults."""
    config = DEFAULT_BRANDING.copy()
    try:
        if CONFIG_PATH.exists():
            user_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            config.update(user_config)
    except Exception as e:
        print(f"Warnung: config.json konnte nicht geladen werden: {e}")
    return config

def save_branding_config(config):
    """Speichert Branding-Config nach data/config.json."""
    # Nur erlaubte Keys
    allowed = {k: v for k, v in config.items() if k in DEFAULT_BRANDING}
    CONFIG_PATH.write_text(json.dumps(allowed, indent=2), encoding="utf-8")
    CONFIG_PATH.chmod(0o600)

# Context-Processor: branding ist in allen Templates verfügbar
@app.context_processor
def inject_branding():
    return {"branding": load_branding_config(), "network": get_network_info()}



# ===== Network-Info =====
import socket
import subprocess as sp

def get_network_info():
    """Sammelt LAN-IP, Tailscale-IP und Hostname."""
    info = {
        "hostname": socket.gethostname(),
        "lan_ip": None,
        "tailscale_ip": None,
        "port": int(os.environ.get("HOTEL_DISPLAY_PORT", 5000))
    }

    # LAN-IP via hostname
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        info["lan_ip"] = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # Fallback: parse ip route
    if not info["lan_ip"]:
        try:
            out = sp.check_output(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                                  text=True, timeout=2)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    info["lan_ip"] = parts[3].split("/")[0]
                    break
        except Exception:
            pass

    # Tailscale-IP
    try:
        out = sp.check_output(["tailscale", "ip", "-4"], text=True, timeout=2)
        lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("100.") is False]
        if lines:
            info["tailscale_ip"] = lines[0]
    except Exception:
        pass

    return info


@app.route('/api/network', methods=['GET'])
def api_network():
    """Liefert Netzwerk-Infos (IPs + Hostname + Port)."""
    return jsonify(get_network_info())

# ===== Branding-API =====
@app.route('/api/branding', methods=['GET'])
def api_get_branding():
    """Branding-Config abrufen (öffentlich, kein Login nötig)."""
    return jsonify(load_branding_config())

@app.route('/api/branding', methods=['POST'])
def api_set_branding():
    """Branding-Config speichern (nur Admin)."""
    # Admin-Check
    emp_id = session.get('employee_id')
    if not emp_id:
        return jsonify({"ok": False, "error": "Nicht eingeloggt"}), 401
    db = get_db()
    emp = db.execute("SELECT is_admin FROM employees WHERE id = ?", (emp_id,)).fetchone()
    db.close()
    if not emp or not emp['is_admin']:
        return jsonify({"ok": False, "error": "Keine Admin-Rechte"}), 403

    data = request.get_json() or {}
    save_branding_config(data)
    log_action(emp_id, 'branding_update', json.dumps(data))
    return jsonify({"ok": True, "config": load_branding_config()})

@app.route('/api/branding/reset', methods=['POST'])
def api_reset_branding():
    """Branding auf Defaults zurücksetzen (nur Admin)."""
    emp_id = session.get('employee_id')
    if not emp_id:
        return jsonify({"ok": False, "error": "Nicht eingeloggt"}), 401
    db = get_db()
    emp = db.execute("SELECT is_admin FROM employees WHERE id = ?", (emp_id,)).fetchone()
    db.close()
    if not emp or not emp['is_admin']:
        return jsonify({"ok": False, "error": "Keine Admin-Rechte"}), 403

    save_branding_config(DEFAULT_BRANDING)
    log_action(emp_id, 'branding_reset', '')
    return jsonify({"ok": True, "config": load_branding_config()})

@app.route('/preview-display')
def preview_display():
    """Vorschau-Display mit aktuellen Branding-Settings (kein Auto-Refresh)."""
    # Lade Defaults aus POST-Data oder aktueller Config
    return render_template('display.html', branding=load_branding_config())



# Konfigurierbarer DB-Pfad (für Tests + Production)
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'hotel-display.db'
)

# Templates sind jetzt in src/templates/display.html etc.


def get_current_employee():
    """Holt den eingeloggten Mitarbeiter aus der Session, oder None."""
    emp_id = session.get('employee_id')
    if not emp_id:
        return None
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ? AND active = 1", (emp_id,)).fetchone()
    db.close()
    return emp


def require_login(f):
    """Decorator: Endpoint nur für eingeloggte Mitarbeiter."""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_current_employee():
            return jsonify({"error": "not authenticated"}), 401
        return f(*args, **kwargs)
    return wrapper


# ===== Root + Static Pages =====

@app.route('/')
def index():
    """Smart-Redirect: Touch-User → /form, Desktop → /display.
    Override via ?mode=display|form|admin"""
    from flask import request, redirect, url_for

    mode = request.args.get('mode', '').lower()
    if mode == 'display':
        return redirect(url_for('index'))
    if mode == 'form':
        return redirect(url_for('form_page'))
    if mode == 'admin':
        return redirect(url_for('admin_page'))

    ua = request.headers.get('User-Agent', '').lower()
    is_touch = any(t in ua for t in ['mobile', 'android', 'iphone', 'ipad', 'touch'])
    if is_touch:
        return redirect(url_for('form_page'))
    return render_template('display.html', branding=load_branding_config())


@app.route('/form')
def form_page():
    """Eingabe-Formular für neue Items."""
    return render_template('form.html')


@app.route('/admin')
def admin_page():
    """Mitarbeiter-Verwaltung (nur Admin)."""
    return render_template('admin.html', branding=load_branding_config())


# ===== Auth =====

@app.route('/login', methods=['POST'])
def login():
    """Mitarbeiter-Login via 4-stelligem Code."""
    data = request.get_json() or {}
    code = data.get('code', '').strip()

    if not code or len(code) != 4 or not code.isdigit():
        return jsonify({"error": "invalid code format (4 digits expected)"}), 400

    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE code = ? AND active = 1", (code,)).fetchone()
    if not emp:
        db.close()
        return jsonify({"error": "code not found"}), 404

    # last_seen_at updaten
    db.execute("UPDATE employees SET last_seen_at = datetime('now', 'localtime') WHERE id = ?", (emp['id'],))
    db.commit()
    db.close()

    session['employee_id'] = emp['id']
    session['employee_name'] = emp['name']
    log_action(emp['id'], 'login')

    return jsonify({
        "ok": True,
        "employee": {
            "id": emp['id'],
            "name": emp['name']
        }
    })


@app.route('/logout', methods=['POST'])
def logout():
    emp_id = session.get('employee_id')
    if emp_id:
        log_action(emp_id, 'logout')
    session.clear()
    return jsonify({"ok": True})


@app.route('/whoami')
def whoami():
    """Aktueller Login-Status."""
    emp = get_current_employee()
    if emp:
        return jsonify({
            "logged_in": True,
            "employee": {"id": emp['id'], "name": emp['name']}
        })
    return jsonify({"logged_in": False})


# ===== Items CRUD =====

@app.route('/items', methods=['GET'])
def get_items():
    """Alle offenen Items, sortiert nach Deadline (Dringlichkeit)."""
    db = get_db()
    items = db.execute("""
        SELECT i.*, e.name AS created_by_name, a.name AS assigned_to_name
        FROM items i
        JOIN employees e ON i.created_by = e.id
        LEFT JOIN employees a ON i.assigned_to = a.id
        WHERE i.done_at IS NULL
        ORDER BY
            CASE WHEN i.deadline IS NULL THEN 1 ELSE 0 END,
            i.deadline ASC,
            i.created_at ASC
    """).fetchall()
    db.close()

    items_list = []
    for i in items:
        item = dict(i)
        if item.get("deadline"):
            try:
                dt = datetime.fromisoformat(item["deadline"])
                item["deadline_display"] = dt.strftime("%d.%m. %H:%M")
            except ValueError:
                item["deadline_display"] = item["deadline"]
        else:
            item["deadline_display"] = None
        items_list.append(item)

    return jsonify({
        "items": items_list,
        "count": len(items)
    })


@app.route('/items', methods=['POST'])
@require_login
def create_item():
    """Neues Item anlegen."""
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    deadline = data.get('deadline')  # ISO-Format oder None
    assigned_to = data.get('assigned_to')

    if not text:
        return jsonify({"error": "text is required"}), 400

    emp = get_current_employee()

    # Deadline-Default: heute 18:00 wenn nicht angegeben
    if deadline is None or deadline == '':
        deadline = (datetime.now() + timedelta(hours=12)).strftime('%Y-%m-%d %H:%M')

    db = get_db()
    cursor = db.execute(
        "INSERT INTO items (text, deadline, created_by, assigned_to) VALUES (?, ?, ?, ?)",
        (text, deadline, emp['id'], assigned_to)
    )
    item_id = cursor.lastrowid
    db.commit()
    db.close()

    log_action(emp['id'], 'create_item', item_id=item_id, details=text[:100])

    return jsonify({"ok": True, "id": item_id}), 201


@app.route('/items/<int:item_id>', methods=['PATCH'])
@require_login
def update_item(item_id):
    """Item bearbeiten (Text, Deadline, assigned_to)."""
    data = request.get_json() or {}
    emp = get_current_employee()

    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        db.close()
        return jsonify({"error": "not found"}), 404

    updates = []
    params = []
    if 'text' in data:
        updates.append("text = ?")
        params.append(data['text'].strip())
    if 'deadline' in data:
        updates.append("deadline = ?")
        params.append(data['deadline'])
    if 'assigned_to' in data:
        updates.append("assigned_to = ?")
        params.append(data['assigned_to'])

    if updates:
        params.append(item_id)
        db.execute(f"UPDATE items SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()

    db.close()
    log_action(emp['id'], 'update_item', item_id=item_id, details=str(data)[:200])

    return jsonify({"ok": True})


@app.route('/items/<int:item_id>/done', methods=['POST'])
@require_login
def mark_done(item_id):
    """Item als erledigt markieren."""
    emp = get_current_employee()

    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        db.close()
        return jsonify({"error": "not found"}), 404

    if item['done_at']:
        db.close()
        return jsonify({"error": "already done"}), 400

    db.execute(
        "UPDATE items SET done_at = datetime('now', 'localtime'), done_by = ? WHERE id = ?",
        (emp['id'], item_id)
    )
    db.commit()
    db.close()

    log_action(emp['id'], 'mark_done', item_id=item_id)

    return jsonify({"ok": True})


@app.route('/items/<int:item_id>', methods=['DELETE'])
@require_login
def delete_item(item_id):
    """Item löschen (hard delete)."""
    emp = get_current_employee()

    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        db.close()
        return jsonify({"error": "not found"}), 404

    db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    db.commit()
    db.close()

    log_action(emp['id'], 'delete_item', item_id=item_id, details=item['text'][:100])

    return jsonify({"ok": True})


# ===== Admin API: Mitarbeiter CRUD =====

@app.route('/api/employees', methods=['GET'])
@require_login
def api_list_employees():
    """Listet alle aktiven Mitarbeiter (für Dropdowns im Form)."""
    active_only = request.args.get('active_only', 'true').lower() == 'true'
    emps = list_employees(active_only=active_only)
    return jsonify({"employees": emps, "count": len(emps)})


@app.route('/api/employees', methods=['POST'])
@require_login
def api_create_employee():
    """Legt einen neuen Mitarbeiter an (Name + 4-stelliger Code)."""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    code = str(data.get('code', '')).strip()

    if not name:
        return jsonify({"error": "name ist pflicht"}), 400
    if len(code) != 4 or not code.isdigit():
        return jsonify({"error": "code muss genau 4 Ziffern haben"}), 400

    # Existiert schon ein Mitarbeiter mit dem Code?
    existing = get_employee_by_code(code)
    if existing:
        return jsonify({"error": f"Code {code} ist schon vergeben (an {existing['name']})"}), 409

    emp_id = create_employee(name, code)
    log_action(get_current_employee()['id'], 'create_employee', details=f"{name} ({code})")
    return jsonify({"ok": True, "id": emp_id}), 201


@app.route('/api/employees/<int:emp_id>', methods=['PATCH'])
@require_login
def api_update_employee(emp_id):
    """Updated Mitarbeiter (Name, Code, active)."""
    data = request.get_json() or {}

    existing = get_employee(emp_id)
    if not existing:
        return jsonify({"error": "mitarbeiter nicht gefunden"}), 404

    # Code-Validierung wenn angegeben
    new_code = data.get('code')
    if new_code is not None:
        new_code = str(new_code).strip()
        if len(new_code) != 4 or not new_code.isdigit():
            return jsonify({"error": "code muss genau 4 Ziffern haben"}), 400
        if new_code != existing['code']:
            dup = get_employee_by_code(new_code)
            if dup:
                return jsonify({"error": f"Code {new_code} ist schon vergeben"}), 409

    update_employee(
        emp_id,
        name=data.get('name'),
        code=new_code if new_code is not None else None,
        active=data.get('active')
    )
    log_action(get_current_employee()['id'], 'update_employee', details=f"ID {emp_id}: {data}")
    return jsonify({"ok": True})


@app.route('/api/employees/<int:emp_id>', methods=['DELETE'])
@require_login
def api_delete_employee(emp_id):
    """Löscht einen Mitarbeiter hard (soft via active=0 wäre Alternative)."""
    # Aktuell eingeloggten Mitarbeiter nicht löschen lassen
    current = get_current_employee()
    if current['id'] == emp_id:
        return jsonify({"error": "kann sich nicht selbst löschen"}), 400

    existing = get_employee(emp_id)
    if not existing:
        return jsonify({"error": "mitarbeiter nicht gefunden"}), 404

    delete_employee(emp_id)
    log_action(current['id'], 'delete_employee', details=f"{existing['name']} ({existing['code']})")
    return jsonify({"ok": True})


@app.route('/api/employees/generate-code', methods=['POST'])
@require_login
def api_generate_code():
    """Generiert einen zufälligen freien 4-stelligen Code."""
    # Bis zu 10 Versuche für eindeutigen Code
    for _ in range(10):
        code = generate_random_code()
        if not get_employee_by_code(code):
            return jsonify({"ok": True, "code": code})
    return jsonify({"error": "kein freier code gefunden"}), 500


# ===== Audit-Log =====

@app.route('/audit', methods=['GET'])
@require_login
def get_audit():
    """Audit-Log abrufen (neueste zuerst)."""
    limit = request.args.get('limit', 100, type=int)
    db = get_db()
    entries = db.execute("""
        SELECT a.*, e.name AS employee_name
        FROM audit_log a
        LEFT JOIN employees e ON a.employee_id = e.id
        ORDER BY a.ts DESC
        LIMIT ?
    """, (limit,)).fetchall()
    db.close()

    return jsonify({
        "entries": [dict(e) for e in entries],
        "count": len(entries)
    })


# ===== Error-Handler =====

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found", "path": request.path}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "server error", "details": str(e)}), 500


if __name__ == "__main__":
    # DB einmal initialisieren beim Start
    import db as db_module
    db_module.DB_PATH = os.environ.get('HOTEL_DISPLAY_DB', DEFAULT_DB_PATH)
    db_module.init_db()

    host = os.environ.get('HOTEL_DISPLAY_HOST', '0.0.0.0')
    port = int(os.environ.get('HOTEL_DISPLAY_PORT', '5000'))
    debug = os.environ.get('HOTEL_DISPLAY_DEBUG', '').lower() in ('1', 'true', 'yes')
    print(f"[app] Starting Flask on http://{host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug)
