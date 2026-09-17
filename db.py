"""Accesso SQLite: canali monitorati, archivio report (giornalieri/settimanali/
mensili), coda messaggi on-demand e relativo log delle analisi."""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "finance_bot.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS canali (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    aggiunto_il TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS report_giornalieri (
    data TEXT PRIMARY KEY,
    testo TEXT NOT NULL,
    creato_il TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS report_settimanali (
    settimana_fine TEXT PRIMARY KEY,
    testo TEXT NOT NULL,
    creato_il TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS report_mensili (
    mese TEXT PRIMARY KEY,
    testo TEXT NOT NULL,
    creato_il TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS report_annuali (
    anno TEXT PRIMARY KEY,
    testo TEXT NOT NULL,
    creato_il TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messaggi_pendenti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    testo TEXT NOT NULL,
    url TEXT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    ricevuto_il TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analisi_on_demand (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    testo_input TEXT NOT NULL,
    testo_risposta TEXT NOT NULL,
    creato_il TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def _connessione():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connessione() as conn:
        conn.executescript(SCHEMA)


# --- canali ---

def aggiungi_canale(username: str) -> bool:
    """Ritorna False se il canale era già presente."""
    with _connessione() as conn:
        try:
            conn.execute("INSERT INTO canali (username) VALUES (?)", (username,))
        except sqlite3.IntegrityError:
            return False
    return True


def rimuovi_canale(username: str) -> bool:
    """Ritorna False se il canale non era presente."""
    with _connessione() as conn:
        cur = conn.execute("DELETE FROM canali WHERE username = ?", (username,))
    return cur.rowcount > 0


def lista_canali() -> list[str]:
    with _connessione() as conn:
        righe = conn.execute("SELECT username FROM canali ORDER BY username").fetchall()
    return [r["username"] for r in righe]


# --- report giornalieri ---

def salva_report_giornaliero(data: str, testo: str):
    with _connessione() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO report_giornalieri (data, testo) VALUES (?, ?)",
            (data, testo),
        )


def report_ultimi_n_giorni(n: int) -> list[sqlite3.Row]:
    with _connessione() as conn:
        return conn.execute(
            "SELECT data, testo FROM report_giornalieri ORDER BY data DESC LIMIT ?",
            (n,),
        ).fetchall()


# --- report settimanali ---

def salva_report_settimanale(settimana_fine: str, testo: str):
    with _connessione() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO report_settimanali (settimana_fine, testo) VALUES (?, ?)",
            (settimana_fine, testo),
        )


def ultimo_report_settimanale() -> sqlite3.Row | None:
    with _connessione() as conn:
        return conn.execute(
            "SELECT settimana_fine, testo FROM report_settimanali ORDER BY settimana_fine DESC LIMIT 1"
        ).fetchone()


def report_settimanali_mese(anno_mese: str) -> list[sqlite3.Row]:
    """anno_mese nel formato 'YYYY-MM'."""
    with _connessione() as conn:
        return conn.execute(
            "SELECT settimana_fine, testo FROM report_settimanali WHERE settimana_fine LIKE ? ORDER BY settimana_fine",
            (f"{anno_mese}-%",),
        ).fetchall()


# --- report mensili ---

def salva_report_mensile(mese: str, testo: str):
    with _connessione() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO report_mensili (mese, testo) VALUES (?, ?)",
            (mese, testo),
        )


def report_mensili_anno(anno: str) -> list[sqlite3.Row]:
    with _connessione() as conn:
        return conn.execute(
            "SELECT mese, testo FROM report_mensili WHERE mese LIKE ? ORDER BY mese",
            (f"{anno}-%",),
        ).fetchall()


# --- report annuali ---

def salva_report_annuale(anno: str, testo: str):
    with _connessione() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO report_annuali (anno, testo) VALUES (?, ?)",
            (anno, testo),
        )


# --- coda on-demand ---

def accoda_messaggio(testo: str, chat_id: int, message_id: int, url: str | None = None):
    with _connessione() as conn:
        conn.execute(
            "INSERT INTO messaggi_pendenti (testo, url, chat_id, message_id) VALUES (?, ?, ?, ?)",
            (testo, url, chat_id, message_id),
        )


def messaggi_in_coda() -> list[sqlite3.Row]:
    with _connessione() as conn:
        return conn.execute(
            "SELECT id, testo, url, chat_id, message_id, ricevuto_il FROM messaggi_pendenti ORDER BY id"
        ).fetchall()


def svuota_coda():
    with _connessione() as conn:
        conn.execute("DELETE FROM messaggi_pendenti")


def log_analisi_on_demand(testo_input: str, testo_risposta: str):
    with _connessione() as conn:
        conn.execute(
            "INSERT INTO analisi_on_demand (testo_input, testo_risposta) VALUES (?, ?)",
            (testo_input, testo_risposta),
        )
