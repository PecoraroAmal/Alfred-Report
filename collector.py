"""Telethon: legge SOLO i canali salvati in db.canali (mai get_dialogs, mai la
lista completa delle chat). Finestra mobile di 24h, solo testo: audio/vocali e
immagini vengono ignorati (mai scaricati), i link YouTube vengono ignorati
(nessuna trascrizione), gli altri URL restano nel testo così Gemini può
leggerli da solo con url_context."""

import re
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient, errors

import config
import db
from notifiche import FUSO_ITALIA, get_logger, notifica_owner

log = get_logger("collector")

_URL_RE = re.compile(r"https?://\S+")
_YOUTUBE_RE = re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)


def url_non_youtube(testo: str) -> str | None:
    for url in _URL_RE.findall(testo or ""):
        if not _YOUTUBE_RE.search(url):
            return url
    return None


def _rimuovi_firma_canale(testo: str, canale: str) -> str:
    """Alcuni canali hanno la 'firma messaggi' attiva: Telegram allega in coda
    al testo una riga con lo username del canale. Va tolta perché altrimenti
    finisce nel prompt come riga fantasma senza orario, confondendo i confini
    tra un messaggio e l'altro."""
    righe = testo.rstrip().split("\n")
    while righe and righe[-1].strip() in (canale, canale.lstrip("@")):
        righe.pop()
    return "\n".join(righe).rstrip()


def normalizza_canale(testo: str) -> str:
    """Accetta sia un link (https://t.me/NomeCanale) sia @NomeCanale/NomeCanale,
    ritorna sempre @NomeCanale — così il DB resta coerente indipendentemente da
    cosa incolla l'utente."""
    testo = testo.strip().split("?")[0].rstrip("/")
    if "t.me/" in testo:
        testo = testo.rsplit("/", 1)[-1]
    return "@" + testo.lstrip("@")


async def raccogli_messaggi() -> dict[str, list[tuple[str, str, str | None]]]:
    """Ritorna {canale: [(ora "HH:MM", testo, url_o_None), ...]}.
    Se un canale non è più accessibile viene rimosso da db.canali e notificato.
    Se la connessione cade a metà, ritorna quanto raccolto finora e notifica."""
    risultato: dict[str, list[tuple[str, str, str | None]]] = {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    client = TelegramClient(
        config.TELETHON_SESSION_PATH, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH
    )
    async with client:
        for canale in db.lista_canali():
            try:
                entity = await client.get_entity(canale)
            except (
                errors.UsernameNotOccupiedError,
                errors.UsernameInvalidError,
                errors.ChannelPrivateError,
                ValueError,
            ):
                db.rimuovi_canale(canale)
                notifica_owner(
                    f"⚠️ Canale {canale} non più accessibile: rimosso automaticamente dalla lista."
                )
                log.warning("Canale rimosso (non accessibile): %s", canale)
                continue
            except Exception:
                log.exception("Raccolta interrotta durante il canale %s", canale)
                notifica_owner(
                    f"⚠️ Connessione interrotta durante la lettura di {canale}: "
                    "procedo con i canali già raccolti."
                )
                return risultato

            messaggi = []
            try:
                async for msg in client.iter_messages(entity):
                    if msg.date < cutoff:
                        break
                    if msg.voice or msg.audio or not msg.text:
                        continue
                    testo = _rimuovi_firma_canale(msg.text, canale)
                    if not testo:
                        continue
                    ora = msg.date.astimezone(FUSO_ITALIA).strftime("%H:%M")
                    url = url_non_youtube(testo)
                    messaggi.append((ora, testo, url))
            except Exception:
                log.exception("Errore durante la lettura dei messaggi di %s", canale)
                notifica_owner(
                    f"⚠️ Errore durante la lettura di {canale}: canale saltato per oggi."
                )
                continue

            if messaggi:
                risultato[canale] = list(reversed(messaggi))

    return risultato
