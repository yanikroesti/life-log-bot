"""SQLite-Speicher: Benutzer, Zeiten, offene Frage, Eintraege.

Wichtig: der offene Slot (welche Frage gerade auf eine Antwort wartet) liegt
BEWUSST in der Datenbank und nicht im Arbeitsspeicher. Der Lernbot haelt so
etwas in einem dict - fuer ein Quiz reicht das, aber hier kann zwischen Frage
und Antwort ein halber Tag liegen. Nach einem Neustart waere die offene Frage
sonst weg und die Antwort wuerde ins Leere laufen.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("LIFELOG_DB") or Path(__file__).with_name("lifelog.db"))

SLOTS = ("morning", "sleep", "midday", "evening")

# Slots mit eigenem Zeitplan (sleep wird an morning angehaengt, kein Timer)
GEPLANTE_SLOTS = ("morning", "midday", "evening")

STANDARDZEITEN = {"morning": "07:00", "midday": "12:15", "evening": "21:00"}


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id      INTEGER PRIMARY KEY,
            tz           TEXT    DEFAULT 'Europe/Zurich',
            t_morning    TEXT    DEFAULT '07:00',
            t_midday     TEXT    DEFAULT '12:15',
            t_evening    TEXT    DEFAULT '21:00',
            pending_slot TEXT,
            pending_date TEXT,
            aktiv        INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS entries (
            chat_id    INTEGER,
            datum      TEXT,
            slot       TEXT,
            raw        TEXT,
            polished   TEXT,
            created_at TEXT,
            PRIMARY KEY (chat_id, datum, slot)
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    INTEGER,
            text       TEXT,
            art        TEXT,      -- 'once' | 'daily' | 'weekly'
            wann       TEXT,      -- once:      'YYYY-MM-DD HH:MM' (Ortszeit)
            zeit       TEXT,      -- daily/weekly: 'HH:MM'
            wochentag  INTEGER,   -- weekly: 0=Montag .. 6=Sonntag (Python-Konvention)
            aktiv      INTEGER DEFAULT 1,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS pending_reminders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    INTEGER,
            text       TEXT,   -- worum es geht (schon aufbereitet)
            roh        TEXT,   -- Originalnachricht, falls es doch ins Tagebuch soll
            created_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


# ---------- Benutzer ----------

def ensure_user(chat_id: int):
    conn = _conn()
    conn.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()


def get_user(chat_id: int):
    conn = _conn()
    row = conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def all_active_users() -> list[int]:
    conn = _conn()
    rows = conn.execute("SELECT chat_id FROM users WHERE aktiv=1").fetchall()
    conn.close()
    return [r["chat_id"] for r in rows]


def set_aktiv(chat_id: int, aktiv: bool):
    conn = _conn()
    conn.execute("UPDATE users SET aktiv=? WHERE chat_id=?", (1 if aktiv else 0, chat_id))
    conn.commit()
    conn.close()


def set_tz(chat_id: int, tz: str):
    conn = _conn()
    conn.execute("UPDATE users SET tz=? WHERE chat_id=?", (tz, chat_id))
    conn.commit()
    conn.close()


def set_zeit(chat_id: int, slot: str, hhmm: str):
    """Uhrzeit fuer einen geplanten Slot setzen."""
    if slot not in GEPLANTE_SLOTS:
        raise ValueError(f"Slot ohne eigenen Zeitplan: {slot}")
    # Spaltenname aus einer festen Whitelist - kein String aus Benutzereingabe.
    spalte = {"morning": "t_morning", "midday": "t_midday", "evening": "t_evening"}[slot]
    conn = _conn()
    conn.execute(f"UPDATE users SET {spalte}=? WHERE chat_id=?", (hhmm, chat_id))
    conn.commit()
    conn.close()


def zeit_fuer(user: dict, slot: str) -> str:
    return user[{"morning": "t_morning", "midday": "t_midday", "evening": "t_evening"}[slot]]


# ---------- Offene Frage ----------

def set_pending(chat_id: int, slot: str | None, datum: str | None = None):
    conn = _conn()
    conn.execute(
        "UPDATE users SET pending_slot=?, pending_date=? WHERE chat_id=?",
        (slot, datum, chat_id),
    )
    conn.commit()
    conn.close()


def get_pending(chat_id: int) -> tuple[str | None, str | None]:
    user = get_user(chat_id)
    if not user:
        return None, None
    return user["pending_slot"], user["pending_date"]


# ---------- Eintraege ----------

def save_entry(chat_id: int, datum: str, slot: str, raw: str, polished: str):
    """Rohtext + aufbereiteten Text sichern.

    Die Sicherung passiert unabhaengig vom Vault: selbst wenn das Schreiben der
    Markdown-Datei scheitert (Sync-Ordner weg, Platte voll), ist der Text hier.
    """
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO entries "
        "(chat_id, datum, slot, raw, polished, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, datum, slot, raw, polished, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def entries_for_day(chat_id: int, datum: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM entries WHERE chat_id=? AND datum=?", (chat_id, datum)
    ).fetchall()
    conn.close()
    reihenfolge = {s: i for i, s in enumerate(SLOTS)}
    return sorted((dict(r) for r in rows), key=lambda e: reihenfolge.get(e["slot"], 99))


# ---------- Erinnerungen ----------

def add_reminder(chat_id: int, text: str, art: str, wann: str = "",
                 zeit: str = "", wochentag: int = -1) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO reminders (chat_id, text, art, wann, zeit, wochentag, aktiv, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (chat_id, text, art, wann, zeit, wochentag,
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_reminder(rid: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def reminders_for(chat_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE chat_id=? AND aktiv=1 ORDER BY id", (chat_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def all_active_reminders() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM reminders WHERE aktiv=1 ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deactivate_reminder(rid: int):
    conn = _conn()
    conn.execute("UPDATE reminders SET aktiv=0 WHERE id=?", (rid,))
    conn.commit()
    conn.close()


# ---------- Erinnerung, die auf eine Zeitauswahl wartet ----------

def add_pending_reminder(chat_id: int, text: str, roh: str) -> int:
    """Neue offene Zeitfrage. Es gibt immer hoechstens eine pro Chat -
    aeltere werden verworfen, damit alte Knoepfe nicht doppelt anlegen."""
    conn = _conn()
    conn.execute("DELETE FROM pending_reminders WHERE chat_id=?", (chat_id,))
    cur = conn.execute(
        "INSERT INTO pending_reminders (chat_id, text, roh, created_at) VALUES (?, ?, ?, ?)",
        (chat_id, text, roh, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def latest_pending_reminder(chat_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM pending_reminders WHERE chat_id=? ORDER BY id DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_reminder(pid: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM pending_reminders WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_pending_reminder(pid: int):
    conn = _conn()
    conn.execute("DELETE FROM pending_reminders WHERE id=?", (pid,))
    conn.commit()
    conn.close()
