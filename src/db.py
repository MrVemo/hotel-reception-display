"""
SQLite Datenbank-Setup für Hotel Reception Display.

Schema:
- employees: Mitarbeiter mit 4-stelligen Login-Codes
- items: Aufgaben/Items mit Deadline, Text, Status
- audit_log: Alle Aktionen (Eintragen, Abhaken, Edit, Delete)

Verwendung:
    from db import init_db, get_db, close_db
    init_db()  # einmal beim ersten Start
"""

import sqlite3
from datetime import datetime, timedelta
import os
import secrets

# Pfad zur DB (relativ zum src/-Verzeichnis)
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'hotel-display.db')


def get_db():
    """Gibt eine SQLite-Connection zurück (mit Foreign Keys + Row-Factory)."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def close_db(db):
    """Schließt die DB-Connection sauber."""
    if db is not None:
        db.close()


def init_db():
    """Erstellt die Tabellen falls nicht vorhanden, und seedet Default-Admin."""
    # Sicherstellen dass data/-Verzeichnis existiert
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    db = get_db()
    cursor = db.cursor()

    # Mitarbeiter-Tabelle
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            last_seen_at TEXT
        )
    """)

    # Items-Tabelle
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            deadline TEXT,
            created_by INTEGER NOT NULL,
            assigned_to INTEGER,
            done_at TEXT,
            done_by INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (created_by) REFERENCES employees(id),
            FOREIGN KEY (assigned_to) REFERENCES employees(id),
            FOREIGN KEY (done_by) REFERENCES employees(id)
        )
    """)

    # Audit-Log-Tabelle
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            employee_id INTEGER,
            action TEXT NOT NULL,
            item_id INTEGER,
            details TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees(id),
            FOREIGN KEY (item_id) REFERENCES items(id)
        )
    """)

    # Indizes für Performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_done ON items(done_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_deadline ON items(deadline)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts)")

    db.commit()

    # Default-Admin anlegen wenn keine Mitarbeiter existieren
    cursor.execute("SELECT COUNT(*) FROM employees")
    if cursor.fetchone()[0] == 0:
        admin_code = "0000"
        cursor.execute(
            "INSERT INTO employees (name, code, active) VALUES (?, ?, ?)",
            ("Admin", admin_code, 1)
        )
        db.commit()
        print(f"[db] Default-Admin angelegt mit Code: {admin_code}")

    db.close()
    print(f"[db] Datenbank initialisiert: {DB_PATH}")


def log_action(employee_id, action, item_id=None, details=None):
    """Schreibt eine Aktion ins Audit-Log."""
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (employee_id, action, item_id, details) VALUES (?, ?, ?, ?)",
        (employee_id, action, item_id, details)
    )
    db.commit()
    db.close()


if __name__ == "__main__":
    # Direkt-Init wenn als Script aufgerufen
    init_db()
