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

from flask import Flask, request, jsonify, session, render_template, render_template_string, redirect, url_for
from datetime import datetime, timedelta
import os
import json
import re
import time
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

UPLOADS_DIR = Path(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'uploads'
))

DEFAULT_BRANDING = {
    "hotel_name": "Willmersdorfer Hof",
    "primary_color": "#3498db",
    "header_gradient_from": "#2c3e50",
    "header_gradient_to": "#34495e",
    "urgent_color": "#e74c3c",
    "overdue_color": "#c0392b",
    "done_color": "#27ae60",
    "logo_filename": None,  # wenn gesetzt, wird logo_url automatisch generiert
    "theme": "light",  # "light" oder "dark" - gilt hotelweit, siehe /api/theme
    "closing_time": "22:00"  # "HH:MM" oder "" (deaktiviert) - siehe get_closing_lock_boundary()
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

    # logo_filename → logo_url ableiten, mit File-mtime als Cache-Buster
    if config.get("logo_filename"):
        logo_path = UPLOADS_DIR / config["logo_filename"]
        if logo_path.exists():
            mtime = int(logo_path.stat().st_mtime)
            config["logo_url"] = f"/uploads/{config['logo_filename']}?v={mtime}"
        else:
            config["logo_url"] = f"/uploads/{config['logo_filename']}"
    else:
        config["logo_url"] = None

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
    if 'closing_time' in data and not _is_valid_closing_time(data['closing_time']):
        return jsonify({"ok": False, "error": "closing_time muss 'HH:MM' oder leer sein"}), 400
    config = load_branding_config()
    config.update(data)
    save_branding_config(config)
    log_action(emp_id, 'branding_update', details=json.dumps(data))
    return jsonify({"ok": True, "config": load_branding_config()})

@app.route('/api/theme', methods=['POST'])
def api_set_theme():
    """Hell/Dunkel-Umschalter — bewusst OHNE Login.

    Rein kosmetisch (kein Datenrisiko), soll aber trotzdem hotelweit gelten
    und einen Kiosk-Reboot ueberleben, deshalb serverseitig in derselben
    config.json wie das Branding statt nur im Browser (localStorage geht
    bei einem Chromium-Kiosk-Reset teils verloren, siehe [[project]] Notizen).
    """
    data = request.get_json() or {}
    theme = data.get('theme')
    if theme not in ('light', 'dark'):
        return jsonify({"ok": False, "error": "theme muss 'light' oder 'dark' sein"}), 400

    config = load_branding_config()
    config['theme'] = theme
    save_branding_config(config)
    return jsonify({"ok": True, "theme": theme})


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
    log_action(emp_id, 'branding_reset', details='')
    return jsonify({"ok": True, "config": load_branding_config()})


@app.route('/api/branding/logo', methods=['POST'])
def upload_logo():
    """Logo-Upload: nimmt base64-codiertes PNG/JPG, resized automatisch auf max 256x256"""
    from flask import session
    emp_id = session.get('employee_id')
    if not emp_id:
        return jsonify({'error': 'not authenticated'}), 401
    db = get_db()
    emp = db.execute("SELECT is_admin FROM employees WHERE id = ?", (emp_id,)).fetchone()
    db.close()
    if not emp or not emp['is_admin']:
        return jsonify({'error': 'Keine Admin-Rechte'}), 403

    import base64
    import re
    from io import BytesIO

    data = request.get_json()
    if not data or 'logo_data' not in data:
        return jsonify({'error': 'no logo_data'}), 400

    # Base64-Data-URL parsen: data:image/png;base64,XXXX
    m = re.match(r'data:image/(png|jpeg);base64,(.+)', data['logo_data'])
    if not m:
        return jsonify({'error': 'invalid format (expected data:image/png;base64,...)'}), 400
    ext = m.group(1)
    raw = base64.b64decode(m.group(2))
    if len(raw) > 10 * 1024 * 1024:
        return jsonify({'error': 'file too large (max 10MB vor Resize)'}), 400

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-Resize mit PIL (Pillow) — max 256x256, behält Aspect Ratio
    original_size = len(raw)
    try:
        from PIL import Image
        img = Image.open(BytesIO(raw))

        # Konvertiere zu RGBA für PNG-Kompatibilität
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGBA' if ext == 'png' else 'RGB')

        # Resize nur wenn größer als 256x256
        MAX_SIZE = 256
        resized = False
        if img.width > MAX_SIZE or img.height > MAX_SIZE:
            img.thumbnail((MAX_SIZE, MAX_SIZE), Image.LANCZOS)
            resized = True

        # Speichern als PNG (komprimiert, mit Transparenz)
        logo_path = UPLOADS_DIR / "logo.png"
        if ext == 'jpeg' and img.mode == 'RGBA':
            # JPG hat keine Transparenz — weißer Hintergrund
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        img.save(logo_path, 'PNG', optimize=True)

        logo_url = '/uploads/logo.png'
    except ImportError:
        # PIL nicht verfügbar — speichere original
        logo_path = UPLOADS_DIR / f"logo.{ext}"
        logo_path.write_bytes(raw)
        logo_url = f'/uploads/{logo_path.name}'
        resized = False

    new_size = logo_path.stat().st_size

    # Branding-Config updaten
    config = load_branding_config()
    config['logo_filename'] = logo_path.name
    save_branding_config(config)
    return jsonify({
        'ok': True,
        'logo_url': logo_url,
        'resized': resized,
        'original_kb': round(original_size / 1024, 1),
        'new_kb': round(new_size / 1024, 1),
        'max_size': 256
    })


@app.route('/api/branding/logo', methods=['DELETE'])
def delete_logo():
    """Logo entfernen"""
    from flask import session
    emp_id = session.get('employee_id')
    if not emp_id:
        return jsonify({'error': 'not authenticated'}), 401
    db = get_db()
    emp = db.execute("SELECT is_admin FROM employees WHERE id = ?", (emp_id,)).fetchone()
    db.close()
    if not emp or not emp['is_admin']:
        return jsonify({'error': 'Keine Admin-Rechte'}), 403

    config = load_branding_config()
    logo_filename = config.pop('logo_filename', None)
    save_branding_config(config)
    if logo_filename:
        for ext in ['png', 'jpg', 'jpeg']:
            p = UPLOADS_DIR / f"logo.{ext}"
            if p.exists():
                p.unlink()
    return jsonify({'ok': True})


@app.route('/uploads/<filename>')
def serve_upload(filename):
    """Statische Files aus data/uploads/ ausliefern"""
    from flask import send_from_directory
    return send_from_directory(UPLOADS_DIR, filename)


@app.route('/preview-display')
def preview_display():
    """Vorschau-Display mit aktuellen Branding-Settings (kein Auto-Refresh)."""
    # Lade Defaults aus POST-Data oder aktueller Config
    return render_template('display.html', branding=load_branding_config())


@app.route('/display-web')
def display_web_page():
    """Responsive Browser-Variante der Anzeige (PC/Handy).
    Nutzt dieselbe API wie der Kiosk (/items, /whoami, /api/branding, ...).
    Polling alle 5s, leichte Verzögerung wird bewusst akzeptiert.
    """
    return render_template('display_web.html', branding=load_branding_config())



# Konfigurierbarer DB-Pfad (für Tests + Production)
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'hotel-display.db'
)

# Repo-Top-Level: VERSION + CHANGELOG.md (fuer /api/changelog)
REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERSION_PATH = REPO_ROOT / "VERSION"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

# Templates sind jetzt in src/templates/display.html etc.

# Sicherheits-Feature: Aufgaben/Uebergabeprotokoll sind nur fuer eingeloggte
# Mitarbeiter sichtbar (nicht mehr ambient fuer jeden am Kiosk/im Hotel-WLAN),
# und die Session laeuft bei Inaktivitaet automatisch ab ("Feierabend" -> Display
# zeigt ohne gueltigen Mitarbeiter-Code keine Gast-/Zimmerdaten mehr an).
IDLE_TIMEOUT_SECONDS = 5 * 60

_CLOSING_TIME_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


def _is_valid_closing_time(value):
    """'' (deaktiviert) oder 'HH:MM' (24h)."""
    return value == '' or (isinstance(value, str) and bool(_CLOSING_TIME_RE.match(value)))


def get_closing_lock_boundary():
    """Letzter ueberschrittener closing_time-Zeitpunkt (branding-Config) vor
    jetzt, als datetime - oder None wenn keine/keine gueltige Sperrzeit
    konfiguriert ist. Sessions, die VOR diesem Zeitpunkt eingeloggt wurden,
    gelten als abgelaufen (siehe get_current_employee()) - harte Sperre zur
    konfigurierten Uhrzeit, unabhaengig von Aktivitaet."""
    closing_time = load_branding_config().get('closing_time') or ''
    if not _CLOSING_TIME_RE.match(closing_time):
        return None
    hh, mm = (int(p) for p in closing_time.split(':'))
    now = datetime.now()
    boundary = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if boundary > now:
        boundary -= timedelta(days=1)
    return boundary


def mark_activity():
    """Markiert echte Nutzer-Interaktion (fuer den Idle-Timeout). NICHT auf
    reinen Lese-/Polling-Endpoints aufrufen, sonst haelt staendiges Auto-Refresh
    die Session trotz Inaktivitaet am Leben."""
    session['last_activity'] = time.time()


def get_current_employee():
    """Holt den eingeloggten Mitarbeiter aus der Session, oder None.

    Loggt automatisch aus (Session wird geleert), wenn entweder
    IDLE_TIMEOUT_SECONDS seit der letzten echten Aktivitaet ueberschritten
    sind, oder die konfigurierte Sperrzeit (closing_time) seit dem Login
    ueberschritten wurde ("Feierabend" - harte Sperre, auch bei aktiver
    Nutzung bis kurz vor der Sperrzeit).
    """
    emp_id = session.get('employee_id')
    if not emp_id:
        return None
    last_activity = session.get('last_activity')
    if last_activity is None or (time.time() - last_activity) > IDLE_TIMEOUT_SECONDS:
        session.clear()
        return None
    login_at = session.get('login_at')
    boundary = get_closing_lock_boundary()
    if boundary is not None and (login_at is None or login_at < boundary.timestamp()):
        session.clear()
        return None
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id = ? AND active = 1", (emp_id,)).fetchone()
    db.close()
    return emp


def require_login(f):
    """Decorator: Endpoint nur für eingeloggte Mitarbeiter.

    Reine Lese-Endpoints (Polling) verwenden diesen Decorator OHNE
    Aktivitaets-Refresh, siehe touch_activity() fuer echte Interaktionen.
    """
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_current_employee():
            return jsonify({"error": "not authenticated"}), 401
        return f(*args, **kwargs)
    return wrapper


def touch_activity(f):
    """Wie require_login, markiert zusaetzlich echte Nutzer-Aktivitaet und
    haelt damit die Session am Leben. Fuer Endpoints die eine bewusste
    Mitarbeiter-Handlung darstellen (Aufgabe anlegen/erledigen, Notiz
    schreiben, ...) - nicht fuer Auto-Polling-Endpoints verwenden."""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_current_employee():
            return jsonify({"error": "not authenticated"}), 401
        mark_activity()
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    """Decorator: Endpoint nur fuer Admins.

    Gibt 401 wenn nicht eingeloggt, 403 wenn eingeloggt aber kein Admin.
    Setzt require_login voraus. Markiert Aktivitaet wie touch_activity().
    """
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        emp = get_current_employee()
        if not emp:
            return jsonify({"error": "not authenticated"}), 401
        # get_current_employee() liefert sqlite3.Row (kein .get), daher Index-Zugriff
        if not emp['is_admin']:
            return jsonify({"error": "Keine Admin-Rechte"}), 403
        mark_activity()
        return f(*args, **kwargs)
    return wrapper


# ===== Root + Static Pages =====

@app.route('/')
def index():
    """Smart-Redirect: Touch-Handy → /form, unklar (kein Touch-UA) → clientseitige
    Bildschirmgroessen-Erkennung (Kiosk-Display vs. PC), siehe detect.html.
    Override via ?view=display|form|admin|web
    """
    from flask import request, redirect, url_for

    view = request.args.get('view', '').lower()
    if view == 'display':
        # Direkt rendern statt redirect(url_for('index')), sonst Endlosschleife
        # (Redirect auf / ohne view= würde bei Touch-UA wieder nach /form springen).
        return render_template('display.html', branding=load_branding_config())
    if view == 'form':
        return redirect(url_for('form_page'))
    if view == 'admin':
        return redirect(url_for('admin_page'))
    if view == 'web':
        return redirect(url_for('display_web_page'))

    ua = request.headers.get('User-Agent', '').lower()
    is_touch = any(t in ua for t in ['mobile', 'android', 'iphone', 'ipad', 'touch'])
    if is_touch:
        return redirect(url_for('form_page'))
    # Weder Handy-Touch-UA noch expliziter view-Parameter: das Kiosk-Chromium
    # startet mit einer nackten "/"-URL und sieht UA-seitig wie ein normaler
    # Desktop-Browser aus, genau wie ein PC im selben WLAN. Bildschirmgroesse
    # ist das einzige zuverlaessige Unterscheidungsmerkmal -> clientseitig
    # entscheiden (detect.html), nicht serverseitig raten.
    return render_template('detect.html')


@app.route('/form')
def form_page():
    """Eingabe-Formular für neue Items."""
    return render_template('form.html')


@app.route('/admin')
def admin_page():
    """Mitarbeiter-Verwaltung (nur Admin)."""
    return render_template('admin.html', branding=load_branding_config())


@app.route('/handover')
def handover_page():
    """Schicht-Übergabe-Log (Touch-optimiert, mit Login-Overlay)."""
    return render_template('handover.html', branding=load_branding_config())


# ===== WiFi-Setup (Captive-Portal) =====

# Konfiguration (NICHT hartcoden — soll spaeter ueber env oder Config-File
# anpassbar sein, falls Hotel anderes WLAN-Schema hat)
# Lazy-Init: mkdir + touch erst beim ersten Gebrauch, nicht beim Import —
# sonst knallt es in Dev/CI-Umgebungen ohne root-Rechte auf /etc/...
def _wifi_config_path() -> Path:
    """Gibt den Pfad zur wifi.json zurueck und legt das Parent-Dir lazy an.

    Default = /etc/hotel-display/wifi.json (root-pfad auf dem Display-Pi).
    Ueberschreibbar per HOTEL_DISPLAY_WIFI_CONFIG env (z.B. fuer Tests).
    """
    p = Path(os.environ.get(
        'HOTEL_DISPLAY_WIFI_CONFIG',
        '/etc/hotel-display/wifi.json'
    ))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _is_setup_mode() -> bool:
    """True wenn der Pi im AP/Captive-Portal-Modus laeuft.

    Wird vom WiFi-Fallback-System-Service (/usr/local/bin/hotel-display-wifi-fallback.sh)
    gesetzt durch Anlegen einer Marker-Datei. Wir checken das hier um zu
    entscheiden ob das Captive-Portal ausgeliefert werden soll.

    Pfad konfigurierbar per HOTEL_DISPLAY_SETUP_MARKER env (fuer Tests).
    """
    return Path(os.environ.get(
        'HOTEL_DISPLAY_SETUP_MARKER',
        '/run/hotel-display-setup-mode'
    )).exists()


def _wifi_status() -> dict:
    """Liest den aktuellen WLAN-Status. Read-only, kein Sudo noetig.

    Nutzt 'iw' fuer Interface-Info und 'nmcli' (falls verfuegbar) fuer
    SSID + IP. Faellt zurueck auf einen Default-Status wenn die Tools
    fehlen.
    """
    import subprocess
    status = {
        'interface': 'wlan0',
        'connected': False,
        'ssid': None,
        'ip': None,
        'saved_networks': [],
        'setup_mode': _is_setup_mode(),
    }
    try:
        r = subprocess.run(['iw', 'dev', 'wlan0', 'link'],
                           capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and 'SSID' in r.stdout:
            for line in r.stdout.splitlines():
                if 'SSID:' in line:
                    status['ssid'] = line.split('SSID:')[1].strip()
                if 'tx bitrate:' in line:
                    pass  # nur Info
            status['connected'] = bool(status['ssid'])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        r = subprocess.run(['ip', '-4', '-o', 'addr', 'show', 'wlan0'],
                           capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == 'inet':
                        status['ip'] = parts[i + 1].split('/')[0]
                        break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Gespeicherte WLANs aus wifi.json lesen (zeigt dem User welche SSIDs
    # schon konfiguriert sind — wichtig fuer Hotel-Mitarbeiter die mehrere
    # APs im Hotel sehen)
    cfg_path = _wifi_config_path()
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text() or '{}')
            saved = cfg.get('networks', [])
            status['saved_networks'] = [
                {'ssid': n['ssid'], 'last_seen': n.get('last_seen')}
                for n in saved
            ]
        except (json.JSONDecodeError, KeyError):
            pass

    return status


@app.route('/setup-wifi', methods=['GET'])
def setup_wifi_page():
    """Captive-Portal: zeigt verfügbare WLANs und ein Form zum Eintragen.

    Bewusst OHNE Login: Hotel-Mitarbeiter ohne Technik-Kenntnisse muss
    das ohne Code benutzen koennen. Daher auch keine Branding-Variablen
    im Template — sieht anders aus als die App, soll klar als Setup erkennbar sein.
    """
    import subprocess
    if not _is_setup_mode():
        # Im normal-Modus: Status-Seite (kein Setup-Form)
        return render_template('setup_wifi.html',
                             mode='status',
                             status=_wifi_status(),
                             error=request.args.get('error'))

    visible_ssids = []
    try:
        # nmcli wifi list — braucht sudo, in der Praxis vom Fallback-Service
        # aufgerufen. Wenn die Rechte fehlen, zeigen wir eine leere Liste.
        r = subprocess.run(
            ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list',
             '--rescan', 'yes'],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            seen = set()
            for line in r.stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split(':')
                if len(parts) >= 3 and parts[0] and parts[0] not in seen:
                    seen.add(parts[0])
                    visible_ssids.append({
                        'ssid': parts[0],
                        'signal': int(parts[1]) if parts[1].isdigit() else 0,
                        'security': parts[2] if parts[2] else 'offen',
                    })
            # Sortieren nach Signalstaerke (stark nach oben)
            visible_ssids.sort(key=lambda x: -x['signal'])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return render_template('setup_wifi.html',
                         mode='setup',
                         status=_wifi_status(),
                         visible_ssids=visible_ssids,
                         error=request.args.get('error'))


@app.route('/setup-wifi', methods=['POST'])
def setup_wifi_submit():
    """Speichert eine neue WLAN-Konfiguration und versucht die Verbindung.

    Validierung:
      - SSID: 1-32 Zeichen, keine Sonderzeichen (SSID-Standard)
      - Passwort: 0-63 Zeichen (WPA2 max) — leer = offenes WLAN

    Schreibt nach $WIFI_CONFIG_PATH (chmod 600) und ruft nmcli auf.
    Bei Erfolg: Pi verbindet sich, Marker-File wird geloescht (vom
    Fallback-Service). Bei Fehler: zurueck zum Form mit Fehlermeldung.

    Sicherheits-Gating: POST ist NUR im Setup-Modus erlaubt (Captive-Portal).
    Im normalen Live-Betrieb soll niemand per LAN-Reachability eine neue
    WLAN-Verbindung erzwingen koennen — das waere eine triviale Denial-of-
    Service Attacke gegen den Kiosk (WLAN-Wechsel kappte aktive Verbindung
    und das Display wuerde offline gehen).
    """
    # GATING: Nur erlaubt wenn der Pi im Setup-Modus laeuft (Marker-File).
    # Im Normalbetrieb → redirect mit klarer Fehlermeldung.
    if not _is_setup_mode():
        return redirect(url_for(
            'setup_wifi_page',
            error='WLAN-Aenderung ist nur im Setup-Modus erlaubt. '
                  'Bitte den Setup-Modus manuell aktivieren.'
        ))

    ssid = (request.form.get('ssid') or '').strip()
    password = request.form.get('password') or ''

    # SSID-Validierung (WPA2-Standard: 1-32 octets, druckbare ASCII)
    if not ssid or len(ssid) > 32:
        return redirect(url_for('setup_wifi_page', error='SSID muss 1-32 Zeichen lang sein'))
    if any(ord(c) < 0x20 or ord(c) > 0x7e for c in ssid):
        return redirect(url_for('setup_wifi_page', error='SSID enthaelt ungueltige Zeichen'))
    # Passwort-Validierung (WPA2-Passphrase: 8-63 ASCII, oder 64 Hex fuer WPA-PSK)
    # Wir erlauben auch leeres Passwort fuer offene WLANs
    if password and (len(password) < 8 or len(password) > 63):
        return redirect(url_for('setup_wifi_page', error='Passwort muss 8-63 Zeichen sein (oder leer fuer offen)'))

    # Bestehende Config laden und aktualisieren
    cfg_path = _wifi_config_path()
    try:
        cfg = json.loads(cfg_path.read_text() or '{}')
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {'networks': []}
    cfg.setdefault('networks', [])

    # SSID aktualisieren (oder neu anlegen) + last_seen setzen
    now = datetime.now().isoformat(timespec='seconds')
    found = False
    for n in cfg['networks']:
        if n.get('ssid') == ssid:
            n['password'] = password       # Klartext im File — chmod 600 schuetzt
            n['last_seen'] = now
            found = True
            break
    if not found:
        cfg['networks'].append({
            'ssid': ssid,
            'password': password,
            'last_seen': now,
        })

    # Speichern (chmod 600 ist Pflicht — Passwort im Klartext!)
    cfg_path.write_text(json.dumps(cfg, indent=2))
    cfg_path.chmod(0o600)

    # Verbindung herstellen via nmcli — blockiert bis zu 20s
    import subprocess
    try:
        cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
        if password:
            cmd += ['password', password]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            # Marker-File loeschen — wir sind aus dem Setup-Modus raus
            Path(os.environ.get(
                'HOTEL_DISPLAY_SETUP_MARKER',
                '/run/hotel-display-setup-mode'
            )).unlink(missing_ok=True)
            # Erfolg-Seite anzeigen (Polling-Seite die auf Verbindung wartet)
            return render_template('setup_wifi.html',
                                 mode='connecting',
                                 status=_wifi_status(),
                                 ssid=ssid)
        else:
            err = (r.stderr or 'Verbindung fehlgeschlagen').strip()
            return redirect(url_for('setup_wifi_page', error=err[:200]))
    except subprocess.TimeoutExpired:
        return redirect(url_for('setup_wifi_page', error='Verbindungsversuch hat zu lange gedauert'))
    except FileNotFoundError:
        return redirect(url_for('setup_wifi_page',
                                error='nmcli nicht installiert — bitte Installer ausfuehren'))


@app.route('/setup-wifi/check')
def setup_wifi_check():
    """AJAX-Endpoint fuer die 'connecting'-Seite: gibt aktuellen WLAN-Status.

    Polling: Browser pollt alle 2s und wechselt auf die Status-Seite sobald
    die Verbindung steht.
    """
    return jsonify(_wifi_status())


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
    session['login_at'] = time.time()
    mark_activity()
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
            "employee": {
                "id": emp['id'],
                "name": emp['name'],
                "is_admin": bool(emp['is_admin'])
            }
        })
    return jsonify({"logged_in": False})


@app.route('/api/touch', methods=['POST'])
@touch_activity
def api_touch():
    """Leichtgewichtiger Aktivitaets-Ping vom Frontend (Touch/Klick/Taste),
    haelt eine eingeloggte Session waehrend echter Nutzung am Leben, ohne dass
    das normale 5s-Polling der Ansichten das faelschlich uebernimmt."""
    return jsonify({"ok": True})


# ===== Items CRUD =====

@app.route('/items', methods=['GET'])
@require_login
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
@touch_activity
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
@touch_activity
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
@touch_activity
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
@touch_activity
def delete_item(item_id):
    """Item löschen (hard delete).

    Audit-Log-Eintraege mit item_id auf NULL setzen BEVOR wir das Item loeschen,
    sonst schlaegt die FK-Constraint audit_log.item_id -> items.id fehl (RESTRICT).
    Wir verlieren damit nicht die History — die Details-Spalte enthaelt den Text.
    """
    emp = get_current_employee()

    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        db.close()
        return jsonify({"error": "not found"}), 404

    # Audit-Log fuer dieses Item entkoppeln (item_id -> NULL),
    # Employee-FK und Action-Details bleiben erhalten.
    db.execute("UPDATE audit_log SET item_id = NULL WHERE item_id = ?", (item_id,))
    db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    db.commit()
    db.close()

    log_action(emp['id'], 'delete_item', item_id=None, details=f"#{item_id}: {item['text'][:100]}")

    return jsonify({"ok": True})


# ===== Admin API: Mitarbeiter CRUD =====

@app.route('/api/employees', methods=['GET'])
@require_admin
def api_list_employees():
    """Listet alle aktiven Mitarbeiter (für Dropdowns im Form)."""
    active_only = request.args.get('active_only', 'true').lower() == 'true'
    emps = list_employees(active_only=active_only)
    return jsonify({"employees": emps, "count": len(emps)})


@app.route('/api/employees', methods=['POST'])
@require_admin
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
@require_admin
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
@require_admin
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
@require_admin
def api_generate_code():
    """Generiert einen zufälligen freien 4-stelligen Code."""
    # Bis zu 10 Versuche für eindeutigen Code
    for _ in range(10):
        code = generate_random_code()
        if not get_employee_by_code(code):
            return jsonify({"ok": True, "code": code})
    return jsonify({"error": "kein freier code gefunden"}), 500


# ===== Handover (Schicht-Übergabe-Log) =====

@app.route('/api/handover', methods=['GET'])
@require_login
def api_list_handover():
    """Letzte N Handover-Einträge, neueste zuerst. Login erforderlich (Notizen
    koennen Gast-/Zimmerbezug haben, sollen ohne eingeloggten Mitarbeiter
    nicht sichtbar sein)."""
    limit = request.args.get('limit', 50, type=int)
    limit = max(1, min(limit, 500))  # bounded, sonst DOS-Risiko
    db = get_db()
    rows = db.execute("""
        SELECT h.id, h.text, h.created_at, h.employee_id,
               e.name AS employee_name
        FROM handover_notes h
        JOIN employees e ON h.employee_id = e.id
        ORDER BY h.created_at DESC, h.id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    db.close()
    return jsonify({
        "notes": [dict(r) for r in rows],
        "count": len(rows)
    })


@app.route('/api/handover', methods=['POST'])
@touch_activity
def api_create_handover():
    """Neuen Handover-Eintrag anlegen. Jeder eingeloggte Mitarbeiter, kein Admin nötig."""
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({"error": "text ist pflicht"}), 400
    if len(text) > 5000:
        return jsonify({"error": "text zu lang (max 5000 zeichen)"}), 400

    emp = get_current_employee()
    db = get_db()
    cursor = db.execute(
        "INSERT INTO handover_notes (employee_id, text) VALUES (?, ?)",
        (emp['id'], text)
    )
    note_id = cursor.lastrowid
    db.commit()
    db.close()

    log_action(emp['id'], 'create_handover', details=text[:200])
    return jsonify({"ok": True, "id": note_id}), 201


@app.route('/api/handover/<int:note_id>', methods=['DELETE'])
@touch_activity
def api_delete_handover(note_id):
    """Handover-Eintrag löschen — nur Admin (Tippfehler-Korrekturen)."""
    emp = get_current_employee()
    db = get_db()
    if not emp['is_admin']:
        db.close()
        return jsonify({"error": "Keine Admin-Rechte"}), 403

    note = db.execute("SELECT id, text FROM handover_notes WHERE id = ?", (note_id,)).fetchone()
    if not note:
        db.close()
        return jsonify({"error": "not found"}), 404

    db.execute("DELETE FROM handover_notes WHERE id = ?", (note_id,))
    db.commit()
    db.close()

    log_action(emp['id'], 'delete_handover', details=f"#{note_id}: {note['text'][:100]}")
    return jsonify({"ok": True})


# ===== Changelog =====

@app.route('/api/changelog', methods=['GET'])
@require_login
def api_changelog():
    """Liefert aktuelle Version (aus VERSION-File) und den Inhalt von CHANGELOG.md.
    Reine Leseinfo, kein extra Admin-Check noetig (nichts Sensibles drin)."""
    try:
        version = VERSION_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        version = "unbekannt"
    try:
        changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        changelog = "(CHANGELOG.md nicht gefunden)"
    except Exception as e:
        changelog = f"(Fehler beim Lesen: {e})"
    return jsonify({
        "version": version,
        "changelog": changelog
    })


# ===== Audit-Log =====

@app.route('/audit', methods=['GET'])
@require_login
def get_audit():
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

NOT_FOUND_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="5;url=/">
<title>Seite nicht gefunden</title>
<style>
  body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
       background:#1a1a1a;color:#f0f0f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       text-align:center;gap:18px;padding:20px;box-sizing:border-box;}
  .icon{font-size:3rem;}
  .path{color:#7f8c8d;font-size:0.9rem;font-family:monospace;word-break:break-all;}
  a.btn{background:#2c3e50;color:#f0f0f0;border:1px solid #34495e;padding:16px 32px;border-radius:8px;
        text-decoration:none;font-size:1.15rem;}
  .hint{font-size:0.8rem;color:#555;}
</style>
</head>
<body>
  <div class="icon">🔍</div>
  <div>Seite nicht gefunden</div>
  <div class="path">{{ path }}</div>
  <a class="btn" href="/">Zurück zur Anzeige</a>
  <div class="hint">Automatische Weiterleitung in 5 Sekunden…</div>
</body>
</html>"""


@app.errorhandler(404)
def not_found(e):
    """Kiosk-Modus hat keine Adressleiste/Zurueck-Button - ein toter Link darf
    hier nie eine nackte JSON-Fehlerseite ohne Ausweg zeigen. API-Aufrufe
    (fetch()) bekommen weiterhin JSON, echte Seitennavigation eine
    Fehlerseite mit Button + Auto-Redirect."""
    if request.path.startswith('/api/') or \
       request.accept_mimetypes['application/json'] >= request.accept_mimetypes['text/html']:
        return jsonify({"error": "not found", "path": request.path}), 404
    return render_template_string(NOT_FOUND_HTML, path=request.path), 404


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
