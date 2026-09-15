#!/bin/bash
# ============================================================
# Hotel Reception Display — Deploy-Script (kanonische Quelle)
# ============================================================
#
# Wird auf dem Display-Pi unter /usr/local/bin/kiko-display-deploy.sh
# installiert. kiko darf es per Sudoers-Regel ohne Passwort als root
# aufrufen:
#
#   kiko ALL=(ALL) NOPASSWD: /usr/local/bin/kiko-display-deploy.sh
#
# Aufruf:
#   sudo /usr/local/bin/kiko-display-deploy.sh
#
# Aufgaben:
#   1. Optionale Reparatur: korrigiert Owner von $REPO/.git/objects
#      falls ein frueherer git-Lauf Objekte als root angelegt hat
#      (passiert wenn das Script selbst oder git mit root-Rechten
#      lief und neue Remote-Objekte holte). Siehe Lessons in
#      CHANGELOG.md (Phase 8 Deploy-Block).
#   2. git pull --ff-only als SERVICE_USER (willmersdorferhof)
#   3. systemctl restart hotel-display.service
#   4. systemctl try-restart hotel-kiosk.service (graceful skip)
#
# Fail-fast: Divergierte Historie (kein fast-forward) bricht VOR
# dem Service-Restart ab. Permission-Fehler werden automatisch
# repariert (siehe Schritt 1).
#
# ============================================================

set -e

REPO=/home/willmersdorferhof/hotel-reception-display
SERVICE_USER=willmersdorferhof

# --- 1. Self-Healing: Repo-Ownership reparieren ---
#
# Falls ein frueherer git-Lauf Objekte in $REPO/.git/objects/ als
# root angelegt hat, kann SERVICE_USER dort nicht schreiben und
# der nachfolgende git pull bricht mit
#   "insufficient permission for adding an object to repository
#    database .git/objects"
# ab.
#
# Wir korrigieren den Owner rekursiv, BEVOR wir pullen. Idempotent
# und read-only-safe (chown mit bereits korrektem Owner ist no-op).
if [ -d "$REPO/.git/objects" ]; then
    broken=$(find "$REPO/.git/objects" -mindepth 1 -maxdepth 1 \
        -type d -not -user "$SERVICE_USER" 2>/dev/null | wc -l)
    if [ "$broken" -gt 0 ]; then
        echo "[deploy] $broken Repo-Object-Subdir(s) mit falschem Owner gefunden"
        echo "[deploy] Repariere $REPO/.git/objects → $SERVICE_USER:$SERVICE_USER ..."
        chown -R "$SERVICE_USER:$SERVICE_USER" "$REPO/.git/objects"
        echo "[deploy] Repair OK"
    fi
fi

# --- 2. Pull ---
echo "[deploy] git pull --ff-only in $REPO als $SERVICE_USER ..."
sudo -u "$SERVICE_USER" git -C "$REPO" pull --ff-only

# --- 3. Service-Restart ---
echo "[deploy] systemctl restart hotel-display.service ..."
systemctl restart hotel-display.service

# --- 4. Optional: hotel-kiosk.service (existiert auf diesem Pi NICHT,
# weil Chromium ueber openbox-autostart laeuft). try-restart statt
# restart, faengt NotFound ab. ---
if systemctl list-unit-files hotel-kiosk.service >/dev/null 2>&1; then
    echo "[deploy] systemctl try-restart hotel-kiosk.service ..."
    systemctl try-restart hotel-kiosk.service
else
    echo "[deploy] Hinweis: hotel-kiosk.service nicht vorhanden,"
    echo "[deploy]   ueberspringe (Chromium laeuft ueber openbox-autostart)"
fi

# --- Abschluss ---
HEAD=$(sudo -u "$SERVICE_USER" git -C "$REPO" rev-parse --short HEAD)
echo "Deploy OK: $HEAD"
