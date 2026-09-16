/*
 * Theme-Toggle (Hell/Dunkel) + kompaktes Overflow-Menu.
 * Theme wird serverseitig in data/config.json gespeichert (POST /api/theme,
 * kein Login noetig - rein kosmetisch, kein Datenrisiko), nicht nur im
 * Browser. Ueberlebt also Kiosk-Reboots und gilt fuer alle Geraete.
 * Server rendert data-theme schon beim ersten Laden (kein Flackern).
 */
(function () {
    function initThemeToggle() {
        var btn = document.querySelector('[data-theme-toggle]');
        if (!btn) return;

        function paint(theme) {
            document.documentElement.setAttribute('data-theme', theme);
            btn.textContent = theme === 'dark' ? '☀️' : '🌙';
            btn.title = theme === 'dark' ? 'Helles Design' : 'Dunkles Design';
        }

        paint(document.documentElement.getAttribute('data-theme') || 'light');

        btn.addEventListener('click', function () {
            var current = document.documentElement.getAttribute('data-theme') || 'light';
            var next = current === 'dark' ? 'light' : 'dark';
            paint(next); // optimistisch sofort umschalten
            fetch('/api/theme', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: next })
            }).catch(function () { /* rein kosmetisch - Fehler ignorieren */ });
        });
    }

    function initOverflowMenus() {
        document.querySelectorAll('.menu-wrap').forEach(function (wrap) {
            var trigger = wrap.querySelector('.menu-trigger');
            var dropdown = wrap.querySelector('.menu-dropdown');
            if (!trigger || !dropdown) return;

            trigger.addEventListener('click', function (e) {
                e.stopPropagation();
                var isOpen = dropdown.classList.toggle('open');
                trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
            });
        });

        document.addEventListener('click', function () {
            document.querySelectorAll('.menu-dropdown.open').forEach(function (d) {
                d.classList.remove('open');
            });
            document.querySelectorAll('.menu-trigger[aria-expanded="true"]').forEach(function (t) {
                t.setAttribute('aria-expanded', 'false');
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            initThemeToggle();
            initOverflowMenus();
        });
    } else {
        initThemeToggle();
        initOverflowMenus();
    }
})();
