"""Regressionstests fuer die Touch-Tastatur Static-Files (Phase 8).

Sichert ab dass:
- src/static/touch-keyboard.css + .js vom Flask ausgeliefert werden
- Beide Files die noetigen DOM-Hooks (CSS-Klassen, JS-Funktionen) enthalten
- Mindestgroesse (kein leerer Stub)
- Templates /form und /handover referenzieren die Files korrekt
"""
import re


def _read(path):
    """UTF-8 explizit — System-Locale (C/POSIX) verfaelscht sonst Umlaute."""
    from pathlib import Path
    return Path(path).read_text(encoding="utf-8")


def test_static_files_served(app):
    """Flask serviert die Touch-Keyboard-Files unter /static/."""
    client = app.test_client()
    for filename, expected_type in [
        ("touch-keyboard.css", "text/css"),
        ("touch-keyboard.js", "text/javascript"),
    ]:
        resp = client.get(f"/static/{filename}")
        assert resp.status_code == 200, f"{filename} not served (got {resp.status_code})"
        assert len(resp.data) > 100, f"{filename} suspiciously small ({len(resp.data)} bytes)"
        assert expected_type in resp.content_type, (
            f"{filename} wrong content-type: {resp.content_type}"
        )


def test_css_contains_keyboard_classes():
    """CSS enthaelt die erwarteten Klassen-Hooks."""
    css = _read("src/static/touch-keyboard.css")
    for needle in ("#touch-keyboard", ".tk-btn", ".tk-row", ".tk-shift", ".tk-space",
                   ".tk-backspace", ".tk-enter"):
        assert needle in css, f"CSS missing class hook: {needle}"


def test_js_exposes_public_api():
    """JS registriert window.touchKeyboard mit den erwarteten Methoden."""
    js = _read("src/static/touch-keyboard.js")
    # Public API Hook (fuer Tests / manuelles Triggern)
    assert "window.touchKeyboard" in js, "JS missing window.touchKeyboard API"
    assert "showKeyboard" in js or "show" in js, "JS missing show()"
    assert "hideKeyboard" in js or "hide" in js, "JS missing hide()"


def test_js_qwertz_layout_present():
    """JS enthaelt das deutsche QWERTZ-Layout mit Umlauten."""
    js = _read("src/static/touch-keyboard.js")
    # Untere QWERTZ-Reihen (jeder Buchstabe kommt als eigener Array-Eintrag vor)
    for letter in "qwertzuiop":
        assert f"'{letter}'" in js, f"QWERTZ row 1 missing letter: {letter}"
    for letter in "asdfghjkl":
        assert f"'{letter}'" in js, f"QWERTZ row 2 missing letter: {letter}"
    for letter in "yxcvbnm":
        assert f"'{letter}'" in js, f"QWERTZ row 3 missing letter: {letter}"
    # Umlaute + Eszett als Array-Eintraege
    for umlaut in "äöüß":
        assert f"'{umlaut}'" in js, f"German umlaut missing in layout: {umlaut}"


def test_js_shift_toggle_state_machine():
    """Shift hat einen Triple-State (off → one → caps → off)."""
    js = _read("src/static/touch-keyboard.js")
    assert "shiftState" in js, "JS missing shiftState variable"
    # Triple-State-Logik
    assert re.search(r"shiftState\s*===\s*['\"]off['\"]", js), "shiftState 'off' missing"
    assert re.search(r"shiftState\s*===\s*['\"]one['\"]", js), "shiftState 'one' missing"
    assert re.search(r"shiftState\s*===\s*['\"]caps['\"]", js), "shiftState 'caps' missing"


def test_form_html_references_touch_keyboard(client):
    """Regression: /form Template bindet CSS+JS ein, sonst keine Tastatur."""
    resp = client.get("/form")
    assert resp.status_code in (200, 302)  # 302 wenn Login-Redirect
    if resp.status_code == 200:
        body = resp.get_data(as_text=True)
        assert "touch-keyboard.css" in body, "form.html fehlt touch-keyboard.css"
        assert "touch-keyboard.js" in body, "form.html fehlt touch-keyboard.js"


def test_handover_html_references_touch_keyboard(client):
    """Regression: /handover Template bindet CSS+JS ein."""
    resp = client.get("/handover")
    assert resp.status_code in (200, 302)
    if resp.status_code == 200:
        body = resp.get_data(as_text=True)
        assert "touch-keyboard.css" in body, "handover.html fehlt touch-keyboard.css"
        assert "touch-keyboard.js" in body, "handover.html fehlt touch-keyboard.js"


def test_display_web_html_no_touch_keyboard(client):
    """Regression: /display-web nutzt echte Tastatur, NICHT die Touch-Komponente."""
    resp = client.get("/display-web")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "touch-keyboard.css" not in body, (
        "display_web.html darf KEIN touch-keyboard.css laden "
        "(PC/Handy haben echte Tastatur)"
    )
    assert "touch-keyboard.js" not in body, (
        "display_web.html darf KEIN touch-keyboard.js laden"
    )


def test_js_handles_textarea_and_input():
    """JS hookt textarea UND input — Item-Text ist textarea, Hex-Color ist input."""
    js = _read("src/static/touch-keyboard.js")
    # isTextInput akzeptiert TEXTAREA
    assert "TEXTAREA" in js, "JS does not handle TEXTAREA"
    # input-Filter schliesst color/checkbox/radio etc. aus, aber NICHT text
    assert "nonTextTypes" in js or "'color'" in js, "JS does not filter non-text input types"
