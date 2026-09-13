# 🖼️ Logo hochladen — Anleitung

Diese Anleitung erklärt, wie das Hotel-Logo auf dem Rezeption-Display angezeigt wird.

## ⚠️ Wichtig: Logo wird **nicht** in GitHub gespeichert!

Logos sind **lokal** auf dem Raspberry Pi unter `/home/willmersdorferhof/hotel-reception-display/data/uploads/` gespeichert. Das ist Absicht — Git soll keine binären Bilddateien enthalten. Jedes Hotel kann sein eigenes Logo verwenden, ohne dass andere Hotels etwas davon mitbekommen.

## So geht's

### Schritt 1: Logo vorbereiten

- **Format:** PNG (mit transparentem Hintergrund) oder JPG
- **Größe:** Empfohlen quadratisch, z.B. **256×256 Pixel** oder **512×512 Pixel**
- **Dateigröße:** Maximal 2 MB
- **Hintergrund:** Am besten transparent, damit es auf jedem Header gut aussieht

### Schritt 2: Im Admin-UI hochladen

1. Öffne im Browser: `http://192.168.178.129:5000/admin` (LAN) oder `http://100.73.15.104:5000/admin` (Tailscale/VPN)
2. Logge dich ein mit deinem 4-stelligen Admin-Code
3. Klick oben auf den Tab **🎨 Branding**
4. Im Bereich **🖼️ Logo** hast du zwei Möglichkeiten:
   - **Klicken** auf den gestrichelten Bereich → Datei-Auswahl öffnet sich
   - **Drag & Drop** — Datei direkt in den Bereich ziehen
5. Das Logo erscheint als Vorschau
6. Klick auf **💾 Branding speichern** um alles zu übernehmen
7. **Live-Preview** unten zeigt sofort, wie es aussieht

### Schritt 3: Optional — Logo wieder entfernen

1. Im Branding-Tab den **🗑️ Logo entfernen** Button klicken
2. Bestätigen
3. Speichern

## Wo wird das Logo gespeichert?

```
/home/willmersdorferhof/hotel-reception-display/data/uploads/logo.png
```

(oder `logo.jpg`, je nach Format)

## Backup / Migration auf neuen Pi

Falls ihr den Pi austauscht oder ein Backup braucht:

```bash
# Logo sichern
scp willmersdorferhof@192.168.178.129:/home/willmersdorferhof/hotel-reception-display/data/uploads/logo.* ./

# Logo auf neuen Pi kopieren
scp logo.png willmersdorferhof@<neuer-pi>:/home/willmersdorferhof/hotel-reception-display/data/uploads/
```

## Häufige Fragen

**F: Mein Logo wird nicht angezeigt — was tun?**
A: Browser-Reload (Strg+Shift+R). Chromium cached die Logos stark. Auf dem Display-Pi passiert das automatisch alle 5 Minuten (Backup-Reload).

**F: Das Logo ist zu groß/klein — was tun?**
A: Im Admin-UI ist die Höhe auf **48px** festgelegt. Für andere Größen: Im `display.html` den Style `height:48px` anpassen.

**F: Kann ich mehrere Logos hochladen?**
A: Nein, das System unterstützt nur ein Logo. Für mehrere Logos müsste das `display.html` Template angepasst werden.

**F: Wo ist die Branding-Config?**
A: `/home/willmersdorferhof/hotel-reception-display/data/config.json` — dort steht `logo_filename`.

**F: Kann ich das Logo auch ohne Admin-Login hochladen?**
A: Nein, der Upload erfordert Login. Falls du nicht eingeloggt bist, hilft der Rezeption-Mitarbeiter oder der Hotel-Admin.

## Support

Bei Fragen: K.I.K.O. fragen (über Telegram an Commander), oder Issue auf GitHub erstellen.
