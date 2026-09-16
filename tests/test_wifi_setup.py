"""Tests fuer den WLAN-Setup-Modus (/setup-wifi GET/POST + /setup-wifi/check).

Deckt ab:
- GET /setup-wifi rendert 200 auch ohne Login (Captive-Portal!)
- GET ohne setup_mode zeigt nur Status-Ansicht
- GET mit setup_mode zeigt Setup-Form mit SSID-Liste
- POST validiert SSID (Laenge, Zeichen)
- POST validiert Passwort (Laenge 8-63 oder leer fuer offene WLANs)
- POST schreibt wifi.json mit chmod 600
- POST aktualisiert bestehende SSID statt Duplikate
- POST-Fehler (nmcli fails) leitet mit ?error= zurueck
- /setup-wifi/check gibt JSON-Status zurueck
- wifi.json-Pfad ist per env ueberschreibbar (verhindert Root-Pfad-Tests)
"""
import json
import os
from pathlib import Path


def test_setup_wifi_no_login_required(client, monkeypatch):
    """REGRESSION: Captive-Portal MUSS ohne Login funktionieren.

    Hotel-Mitarbeiter ohne Technik-Kenntnisse hat keinen Code und
    kann sich keinen holen — wenn er die Seite nicht aufrufen kann,
    ist der ganze Use-Code kaputt.
    """
    # Setup-Mode erzwingen (sonst sehen wir die Status-Seite)
    marker = Path('/tmp/test-setup-mode-marker')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        resp = client.get('/setup-wifi')
        assert resp.status_code == 200, (
            f"Setup-Wifi muss ohne Login 200 liefern, war {resp.status_code}"
        )
    finally:
        marker.unlink(missing_ok=True)


def test_setup_wifi_status_mode(client):
    """Ohne setup_mode-Marker wird nur Status angezeigt (kein Form)."""
    resp = client.get('/setup-wifi')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Status-Seite enthaelt Interface-Info, aber KEIN SSID-Form
    assert 'wlan0' in body
    assert 'Nicht verbunden' in body or 'Verbunden' in body
    assert 'name="password"' not in body, (
        "Im Status-Modus darf KEIN Passwort-Form angezeigt werden"
    )


def test_setup_wifi_setup_mode_shows_form(client, monkeypatch):
    """Mit setup_mode-Marker wird das Form mit SSID-Liste angezeigt."""
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", "/tmp/test-wifi-form.json")
    marker = Path('/tmp/test-setup-mode-marker-form')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        resp = client.get('/setup-wifi')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'name="ssid"' in body
        assert 'name="password"' in body
        assert 'Verf\u00fcgbare WLANs' in body  # Umlaute
    finally:
        marker.unlink(missing_ok=True)


def test_setup_wifi_submit_writes_config(client, monkeypatch):
    """POST schreibt wifi.json mit SSID + Passwort + chmod 600."""
    cfg_path = Path('/tmp/test-wifi-write.json')
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", str(cfg_path))
    marker = Path('/tmp/test-setup-mode-write')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        # nmcli wird im Test scheitern (kein echtes WLAN), aber wir
        # checken VOR dem nmcli-Aufruf dass die Config geschrieben wird.
        # Trick: das nmcli wird fehlschlagen, aber das File sollte schon da sein.
        resp = client.post('/setup-wifi', data={
            'ssid': 'Hotel-Gast-WLAN',
            'password': 'supersecret123',
        }, follow_redirects=False)
        # Wir akzeptieren 200 (connecting) oder 302 (redirect bei nmcli-fail)
        assert resp.status_code in (200, 302)

        # Config muss geschrieben sein mit korrekten Feldern
        assert cfg_path.exists(), "wifi.json wurde nicht geschrieben!"
        assert oct(cfg_path.stat().st_mode & 0o777) == '0o600', (
            f"wifi.json muss Mode 0600 haben, hat aber "
            f"{oct(cfg_path.stat().st_mode & 0o777)}"
        )

        cfg = json.loads(cfg_path.read_text())
        assert 'networks' in cfg
        assert len(cfg['networks']) == 1
        assert cfg['networks'][0]['ssid'] == 'Hotel-Gast-WLAN'
        assert cfg['networks'][0]['password'] == 'supersecret123'
        assert 'last_seen' in cfg['networks'][0]
    finally:
        marker.unlink(missing_ok=True)
        cfg_path.unlink(missing_ok=True)


def test_setup_wifi_submit_updates_existing(client, monkeypatch):
    """POST mit existierender SSID aktualisiert statt Duplikat anzulegen."""
    cfg_path = Path('/tmp/test-wifi-update.json')
    cfg_path.write_text(json.dumps({
        'networks': [{
            'ssid': 'Hotel-WLAN',
            'password': 'old_password',
            'last_seen': '2026-01-01T00:00:00',
        }]
    }))
    cfg_path.chmod(0o600)
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", str(cfg_path))
    marker = Path('/tmp/test-setup-mode-update')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        client.post('/setup-wifi', data={
            'ssid': 'Hotel-WLAN',
            'password': 'new_password',
        }, follow_redirects=False)

        cfg = json.loads(cfg_path.read_text())
        assert len(cfg['networks']) == 1, "SSID wurde dupliziert!"
        assert cfg['networks'][0]['password'] == 'new_password'
        # last_seen muss aktualisiert worden sein
        assert cfg['networks'][0]['last_seen'] != '2026-01-01T00:00:00'
    finally:
        marker.unlink(missing_ok=True)
        cfg_path.unlink(missing_ok=True)


def test_setup_wifi_submit_validates_ssid_too_short(client, monkeypatch):
    """SSID < 1 Zeichen → 302 redirect mit Fehler."""
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", "/tmp/test-wifi-validation.json")
    marker = Path('/tmp/test-setup-mode-validation')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        resp = client.post('/setup-wifi', data={
            'ssid': '',
            'password': 'geheimespass',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert 'error=' in resp.headers['Location']
    finally:
        marker.unlink(missing_ok=True)


def test_setup_wifi_submit_validates_ssid_too_long(client, monkeypatch):
    """SSID > 32 Zeichen → 302 redirect mit Fehler."""
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", "/tmp/test-wifi-long.json")
    marker = Path('/tmp/test-setup-mode-long')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        resp = client.post('/setup-wifi', data={
            'ssid': 'A' * 33,
            'password': 'geheimespass',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert 'error=' in resp.headers['Location']
    finally:
        marker.unlink(missing_ok=True)


def test_setup_wifi_submit_validates_ssid_invalid_chars(client, monkeypatch):
    """SSID mit Non-ASCII (z.B. Newline) → 302 redirect mit Fehler."""
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", "/tmp/test-wifi-chars.json")
    marker = Path('/tmp/test-setup-mode-chars')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        resp = client.post('/setup-wifi', data={
            'ssid': 'WLAN\nmit\nNewline',
            'password': 'geheimespass',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert 'error=' in resp.headers['Location']
    finally:
        marker.unlink(missing_ok=True)


def test_setup_wifi_submit_validates_password_too_short(client, monkeypatch):
    """Passwort < 8 Zeichen (wenn nicht leer) → 302 redirect mit Fehler."""
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", "/tmp/test-wifi-pw.json")
    marker = Path('/tmp/test-setup-mode-pw')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        resp = client.post('/setup-wifi', data={
            'ssid': 'Hotel-WLAN',
            'password': 'kurz',   # 4 Zeichen, unter dem 8er-Minimum
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert 'error=' in resp.headers['Location']
    finally:
        marker.unlink(missing_ok=True)


def test_setup_wifi_submit_allows_empty_password(client, monkeypatch):
    """Leeres Passwort ist erlaubt (offenes WLAN)."""
    cfg_path = Path('/tmp/test-wifi-empty-pw.json')
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", str(cfg_path))
    marker = Path('/tmp/test-setup-mode-empty')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        resp = client.post('/setup-wifi', data={
            'ssid': 'Offenes-Hotel-WLAN',
            'password': '',
        }, follow_redirects=False)
        # Leeres PW ist erlaubt → entweder 200 (connecting) oder 302 (nmcli-fail)
        assert resp.status_code in (200, 302)

        cfg = json.loads(cfg_path.read_text())
        assert cfg['networks'][0]['password'] == ''
    finally:
        marker.unlink(missing_ok=True)
        cfg_path.unlink(missing_ok=True)


def test_setup_wifi_check_returns_json(client):
    """/setup-wifi/check ist ein JSON-Endpoint ohne Login."""
    resp = client.get('/setup-wifi/check')
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
    assert 'connected' in data
    assert 'setup_mode' in data
    assert 'interface' in data


def test_wifi_config_path_overridable(client, monkeypatch):
    """REGRESSION: env-Variable HOTEL_DISPLAY_WIFI_CONFIG muss greifen.

    Wenn die env nicht greift, wuerden Tests versuchen auf /etc/hotel-display/
    zu schreiben — was als normaler User fehlschlaegt.
    """
    custom_path = '/tmp/test-wifi-env-override.json'
    monkeypatch.setenv("HOTEL_DISPLAY_WIFI_CONFIG", custom_path)
    marker = Path('/tmp/test-setup-mode-env')
    monkeypatch.setenv("HOTEL_DISPLAY_SETUP_MARKER", str(marker))
    marker.touch()
    try:
        client.post('/setup-wifi', data={
            'ssid': 'Test-WLAN',
            'password': 'testpassword',
        }, follow_redirects=False)
        assert Path(custom_path).exists(), (
            "HOTEL_DISPLAY_WIFI_CONFIG env wurde nicht beachtet"
        )
    finally:
        marker.unlink(missing_ok=True)
        Path(custom_path).unlink(missing_ok=True)
