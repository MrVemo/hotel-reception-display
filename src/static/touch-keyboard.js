/* On-Screen-QWERTZ-Tastatur fuer Touch-Displays ohne physikalisches Keyboard.
 *
 * Verwendung:
 *   <link rel="stylesheet" href="{{ url_for('static', filename='touch-keyboard.css') }}">
 *   <script src="{{ url_for('static', filename='touch-keyboard.js') }}"></script>
 *
 * Oder via auto-attach beim DOMContentLoaded: jeder <input type="text">,
 * <input type="search">, <input> ohne type (default text) und jede <textarea>
 * bekommt automatisch eine Touch-Tastatur, sobald er fokussiert wird.
 *
 * Multi-Touch: ein einziges Keyboard wird zwischen Inputs geteilt; bei
 * Wechsel des Fokus wandert der Cursor (caret position) erhalten.
 *
 * Escape-Tasten / Ausnahmen:
 *   - Inputs mit data-touch-keyboard="off" bekommen KEINE Tastatur
 *   - Inputs vom type=color / type=checkbox / type=radio / type=submit /
 *     type=button / type=hidden werden uebersprungen
 *   - Inputs vom type=number / type=email etc. koennen wir generisch
 *     behandeln — wenn der User auf dem Pi nur eine Tastatur hat, ist
 *     QWERTZ dafuer immer noch nuetzlicher als gar nichts.
 *
 * Tipps / Lessons Learned:
 *   - Chromium-Kiosk hat keinen Zurueck-Button, daher kein "Schliessen"-X
 *     noetig — die Eingabe ist nach Enter/Fertig sowieso vorbei, oder
 *     der User tappt woanders hin (Blur) zum Ausblenden.
 *   - Touchstart statt click verwenden — schnelleres Feedback auf Touch.
 *   - ev.preventDefault() im touchstart, damit der Tap nicht auch ein
 *     care-move-Event ausloest.
 *   - Shift/Caps-Lock-Toggle: erster Tap → Shift (ein Zeichen gross),
 *     zweiter Tap → Caps (dauerhaft gross), dritter Tap → aus.
 *   - Backspace als longpress → Dauergeschwindigkeit? Out of scope fuer
 *     jetzt, kann spaeter dazukommen.
 */

(function() {
    'use strict';

    // ===== Konfiguration =====
    // Deutsches QWERTZ-Layout, jede Zeile entspricht einer Keyboard-Row.
    // Modifier-Buttons haben einen speziellen data-action.
    const LAYOUT_LOWER = [
        ['q', 'w', 'e', 'r', 't', 'z', 'u', 'i', 'o', 'p', 'ü'],
        ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'ö', 'ä'],
        // Row 3 hat Shift am Anfang und Backspace am Ende
        ['shift', 'y', 'x', 'c', 'v', 'b', 'n', 'm', 'ß', 'backspace'],
        // Row 4: Zahlen-Reihe ueber QWERTZ (per Layout auf 123? — out of scope
        // hier, optional spaeter), Leerzeichen und Fertig
        ['123?']
    ];

    // Grossbuchstaben-Version: nur die Letter-Buttons ändern sich, Modifier
    // bleiben gleich. Wir bauen das Layout zur Laufzeit dynamisch auf.
    const LAYOUT_UPPER = [
        ['Q', 'W', 'E', 'R', 'T', 'Z', 'U', 'I', 'O', 'P', 'Ü'],
        ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'Ö', 'Ä'],
        ['shift', 'Y', 'X', 'C', 'V', 'B', 'N', 'M', 'ß', 'backspace'],
        ['space', 'enter']
    ];

    // Bei Shift EIN: erstes Zeichen nach Shift gross, dann wieder lower
    // (One-Shift-Verhalten wie auf iOS/Android).
    // Bei Shift "active" (Doppel-Tap = Caps): dauerhaft gross bis erneut Tap.

    // ===== DOM =====
    let keyboardEl = null;
    let currentInput = null;
    let shiftState = 'off';    // 'off' | 'one' | 'caps'

    function buildKeyboard() {
        // Falls schon da, nicht doppelt bauen
        if (document.getElementById('touch-keyboard')) return;

        keyboardEl = document.createElement('div');
        keyboardEl.id = 'touch-keyboard';
        keyboardEl.setAttribute('role', 'toolbar');
        keyboardEl.setAttribute('aria-label', 'Touch-Tastatur');

        document.body.appendChild(keyboardEl);
        renderLayout();
    }

    function renderLayout() {
        if (!keyboardEl) return;

        // Welches Layout? Bei shiftState 'off' lower, sonst upper
        const layout = shiftState === 'off' ? LAYOUT_LOWER : LAYOUT_UPPER;

        keyboardEl.innerHTML = '';

        // Reihen rendern. Hinweis: layout[3] ist die Spezial-Reihe
        // (space/enter vs 123-Platzhalter); die bauen wir ebenfalls.
        for (let rowIdx = 0; rowIdx < layout.length; rowIdx++) {
            const rowEl = document.createElement('div');
            rowEl.className = 'tk-row';

            for (const key of layout[rowIdx]) {
                const btn = document.createElement('button');
                btn.type = 'button';     // wichtig: kein Form-Submit!
                btn.className = 'tk-btn';

                if (key === 'shift') {
                    btn.classList.add('tk-shift');
                    btn.setAttribute('data-action', 'shift');
                    btn.textContent = shiftState === 'caps' ? '⇪' : '⇧';
                    if (shiftState !== 'off') btn.classList.add('active');
                    btn.setAttribute('aria-label', 'Umschalttaste');
                } else if (key === 'backspace') {
                    btn.classList.add('tk-backspace');
                    btn.setAttribute('data-action', 'backspace');
                    btn.textContent = '⌫';
                    btn.setAttribute('aria-label', 'Rueckschritt');
                } else if (key === 'space') {
                    btn.classList.add('tk-space');
                    btn.textContent = '⎵';          // Leerzeichen-Symbol
                    btn.setAttribute('data-action', 'space');
                    btn.setAttribute('aria-label', 'Leerzeichen');
                } else if (key === 'enter') {
                    btn.classList.add('tk-enter');
                    btn.textContent = '✓ Fertig';
                    btn.setAttribute('data-action', 'enter');
                    btn.setAttribute('aria-label', 'Eingabe abschliessen');
                } else if (key === '123?') {
                    // Platzhalter fuer spaetere Erweiterung (Zahlen/Sonder-
                    // zeichen). Erstmal kein Click-Handler.
                    btn.classList.add('tk-btn-wide');
                    btn.textContent = 'ABC';
                    btn.disabled = true;
                    btn.style.opacity = '0.4';
                } else {
                    // Normaler Buchstabe
                    btn.textContent = key;
                    btn.setAttribute('data-char', key);
                    btn.setAttribute('aria-label', key);
                }

                // Click + Touchstart parallel (manche Touch-Geraete feuern
                // nur eines davon zuverlaessig)
                const handler = (e) => {
                    e.preventDefault();
                    handleKey(btn);
                };
                btn.addEventListener('click', handler);
                btn.addEventListener('touchstart', handler, { passive: false });

                rowEl.appendChild(btn);
            }

            keyboardEl.appendChild(rowEl);
        }
    }

    function handleKey(btn) {
        if (!currentInput) return;

        const action = btn.dataset.action;
        if (action === 'shift') {
            // Triple-State: off → one → caps → off
            if (shiftState === 'off') {
                shiftState = 'one';
            } else if (shiftState === 'one') {
                shiftState = 'caps';
            } else {
                shiftState = 'off';
            }
            renderLayout();
            return;
        }

        if (action === 'backspace') {
            // Standard-Verhalten: letztes Zeichen weg
            deleteCharBeforeCaret(currentInput);
            // Shift nach one-shot zuruecksetzen (Caps bleibt)
            if (shiftState === 'one') shiftState = 'off';
            if (shiftState === 'caps') renderLayout();
            return;
        }

        if (action === 'space') {
            insertAtCaret(currentInput, ' ');
        } else if (action === 'enter') {
            // Bei textarea: Newline. Bei input type=text: fertig (Blur).
            if (currentInput.tagName === 'TEXTAREA') {
                insertAtCaret(currentInput, '\n');
            } else {
                hideKeyboard();
                return;
            }
        } else {
            // Normaler Buchstabe
            const ch = btn.dataset.char || btn.textContent;
            insertAtCaret(currentInput, ch);
        }

        // One-Shift zuruecksetzen nach jedem Buchstaben (ausser Caps bleibt)
        if (shiftState === 'one') {
            shiftState = 'off';
            renderLayout();
        } else if (shiftState === 'caps') {
            // Caps bleibt: renderLayout NICHT noetig, keine Aenderung
        }

        // Input-Event feuern, damit ggf. Listener (Validierung etc.) reagieren
        currentInput.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function insertAtCaret(input, text) {
        // Native setRangeText ist die saubere Loesung: respektiert
        // Selektion und Cursor-Position automatisch.
        if (typeof input.setRangeText === 'function') {
            const start = input.selectionStart || 0;
            const end = input.selectionEnd || 0;
            input.setRangeText(text, start, end, 'end');
            // Bei maxlength-Begrenzung setRangeText → input.value korrigieren
            if (input.maxLength > 0 && input.value.length > input.maxLength) {
                input.value = input.value.slice(0, input.maxLength);
            }
        } else {
            // Fallback fuer sehr alte Browser
            input.value += text;
        }
        // Focus sicherstellen (manche Inputs blurren nach Touch)
        if (document.activeElement !== input) input.focus();
    }

    function deleteCharBeforeCaret(input) {
        const start = input.selectionStart || 0;
        const end = input.selectionEnd || 0;
        if (start !== end) {
            // Selektion loeschen
            input.setRangeText('', start, end, 'end');
        } else if (start > 0) {
            // Ein Zeichen davor loeschen
            input.setRangeText('', start - 1, start, 'end');
        }
    }

    function showKeyboard(input) {
        currentInput = input;
        if (!keyboardEl) buildKeyboard();
        keyboardEl.classList.add('visible');
        document.body.classList.add('tk-open');

        // Sanity: bei Wechsel zurueck auf lower (nicht sticks an caps)
        if (shiftState === 'one') {
            shiftState = 'off';
            renderLayout();
        }
    }

    function hideKeyboard() {
        if (keyboardEl) keyboardEl.classList.remove('visible');
        document.body.classList.remove('tk-open');
        currentInput = null;
    }

    function isTextInput(el) {
        if (!el || el.tagName === 'INPUT' && el.type === 'hidden') return false;
        const tag = el.tagName;
        if (tag === 'TEXTAREA') return true;
        if (tag !== 'INPUT') return false;
        // Opt-out per Attribut
        if (el.dataset.touchKeyboard === 'off') return false;
        // Opt-out per Klasse
        if (el.classList.contains('no-touch-keyboard')) return false;
        // Default-Text-Inputs einschliessen; number/email/etc. auch (am
        // Touch-Display gibt's eh keine andere Tastatur, QWERTZ ist besser
        // als gar nichts).
        const nonTextTypes = ['color', 'checkbox', 'radio', 'submit', 'button', 'reset', 'file', 'image', 'range'];
        const t = (el.type || 'text').toLowerCase();
        return !nonTextTypes.includes(t);
    }

    function attach() {
        // Auto-Attach: jeder Input/Textarea im Dokument
        document.addEventListener('focusin', (e) => {
            if (isTextInput(e.target)) showKeyboard(e.target);
        });
        document.addEventListener('focusout', (e) => {
            // Verzoegert prüfen, damit Klick auf Keyboard-Button nicht
            // versehentlich Blur ausloest
            setTimeout(() => {
                if (!currentInput || document.activeElement !== currentInput) {
                    hideKeyboard();
                }
            }, 100);
        });
        // Tap irgendwo ausserhalb des Keyboards → Keyboard ausblenden
        document.addEventListener('touchstart', (e) => {
            if (!keyboardEl) return;
            if (!keyboardEl.contains(e.target) &&
                !isTextInput(e.target) &&
                currentInput) {
                hideKeyboard();
            }
        }, { passive: true });
    }

    // ===== Boot =====
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attach);
    } else {
        attach();
    }

    // Public API fuer manuelle Steuerung (z.B. Tests)
    window.touchKeyboard = {
        show: showKeyboard,
        hide: hideKeyboard,
        // Test-Hook: sichtbar ohne Input-Fokus (fuer visuelle Verifikation)
        _testShow: () => {
            if (!keyboardEl) buildKeyboard();
            keyboardEl.classList.add('visible');
            document.body.classList.add('tk-open');
        },
        _testHide: hideKeyboard
    };
})();
