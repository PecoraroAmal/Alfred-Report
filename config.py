"""Caricamento configurazione da .env. Fallisce subito all'import se manca una
variabile obbligatoria, per non scoprire il problema a metà di un job notturno."""

import os

from dotenv import load_dotenv

load_dotenv()

_OBBLIGATORIE = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_ID",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
]

_mancanti = [nome for nome in _OBBLIGATORIE if not os.getenv(nome)]
if _mancanti:
    raise RuntimeError(
        "Variabili d'ambiente mancanti in .env: " + ", ".join(_mancanti)
    )

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_OWNER_ID = int(os.environ["TELEGRAM_OWNER_ID"])

TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
TELETHON_SESSION_PATH = os.getenv("TELETHON_SESSION_PATH", "./finance_bot.session")

LOG_PATH = os.getenv("LOG_PATH", "./finance_bot.log")
