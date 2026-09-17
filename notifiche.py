"""Logging su file condiviso tra i vari processi + notifica errori all'owner
via Bot API (chiamata HTTP diretta, senza dipendere dal processo bot.py)."""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import config

logging.basicConfig(
    filename=config.LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def get_logger(nome: str) -> logging.Logger:
    return logging.getLogger(nome)


def invia_documento(percorso_file: str, didascalia: str | None = None):
    """Invia un file all'owner via send_document (nessun limite ai 4096 caratteri
    dei messaggi normali)."""
    with open(percorso_file, "rb") as f:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument",
            data={"chat_id": config.TELEGRAM_OWNER_ID, "caption": didascalia or ""},
            files={"document": f},
            timeout=60,
        )


FUSO_ITALIA = ZoneInfo("Europe/Rome")


def attendi_fino_alle(ora: str = "06:00", giorno_dopo: bool = False):
    """Aspetta (time.sleep) fino a un orario HH:MM, sempre in ora italiana
    (Europe/Rome, calcolato esplicitamente — non ci si affida al fuso orario
    di sistema del server, che potrebbe essere diverso o mal configurato).
    Con giorno_dopo=False (uso tipico: job che parte poco prima, stesso
    giorno, es. il digest giornaliero) punta a oggi — se l'orario è già
    passato non aspetta affatto, invio immediato. Con giorno_dopo=True (job
    che parte la sera/notte prima, es. i riepiloghi) punta sempre a domani,
    per non inviare subito solo perché l'orario di oggi è ovviamente già
    passato."""
    ore, minuti = (int(x) for x in ora.split(":"))
    adesso = datetime.now(FUSO_ITALIA)
    base = adesso + (timedelta(days=1) if giorno_dopo else timedelta())
    ora_target = base.replace(hour=ore, minute=minuti, second=0, microsecond=0)
    secondi = (ora_target - adesso).total_seconds()
    if secondi > 0:
        get_logger("notifiche").info("In attesa fino alle %s ora italiana (%.0f secondi)", ora, secondi)
        time.sleep(secondi)


def notifica_owner(testo: str):
    """Invia un messaggio di testo all'owner. Non solleva eccezioni: un errore
    nel notificare non deve far crashare il job che stava già gestendo un errore."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_OWNER_ID, "text": testo},
            timeout=15,
        )
    except requests.RequestException:
        get_logger("notifiche").exception("Impossibile notificare l'owner: %s", testo)
