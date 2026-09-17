"""Login one-time di Telethon: da eseguire una sola volta, in un terminale
interattivo vero. Chiede numero di telefono, codice OTP e (se attiva)
password 2FA, poi salva la sessione in TELETHON_SESSION_PATH. Da quel momento
in poi collector.py/main.py riusano la sessione senza richiedere altro."""

from telethon import TelegramClient

import config

client = TelegramClient(config.TELETHON_SESSION_PATH, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)

with client:
    me = client.loop.run_until_complete(client.get_me())
    print(f"Login riuscito: {me.first_name} (@{me.username})")
    print(f"Sessione salvata in: {config.TELETHON_SESSION_PATH}")
