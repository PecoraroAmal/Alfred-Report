"""Servizio long-running (long polling, l'unica opzione dato che la VPS non è
raggiungibile da internet pubblico). Whitelist rigida su TELEGRAM_OWNER_ID:
chiunque altro viene ignorato del tutto, nessuna risposta."""

import asyncio
import re
from functools import wraps

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import analyzer
import config
import db
from collector import normalizza_canale, url_non_youtube
from notifiche import get_logger

log = get_logger("bot")

LIMITE_MESSAGGIO = 4000  # margine sotto i 4096 caratteri di Telegram

COMANDI = [
    ("aggiungi", "Aggiungi un canale da monitorare: /aggiungi @canale (o incolla il link t.me/...)"),
    ("rimuovi", "Rimuovi un canale monitorato: /rimuovi @canale (o incolla il link t.me/...)"),
    ("lista", "Mostra l'elenco dei canali attualmente monitorati"),
    (
        "analizza_messaggi",
        "Analizza subito tutti i messaggi che hai inoltrato al bot da quando "
        "non hai più usato questo comando (o /scarta), poi svuota la coda",
    ),
    ("scarta", "Svuota la coda di messaggi inoltrati senza analizzarli"),
    ("backup", "Ricevi una copia del database (canali + archivio report)"),
    ("help", "Mostra questo elenco comandi con la spiegazione"),
]


def _spezza_messaggio(testo: str, limite: int = LIMITE_MESSAGGIO) -> list[str]:
    """Spezza un testo lungo in pezzi <= limite caratteri, tagliando su un a capo
    quando possibile invece che a metà parola."""
    pezzi = []
    while len(testo) > limite:
        taglio = testo.rfind("\n", 0, limite)
        if taglio <= 0:
            taglio = limite
        pezzi.append(testo[:taglio])
        testo = testo[taglio:].lstrip("\n")
    pezzi.append(testo)
    return pezzi


def _testo_semplice(markdown: str) -> str:
    """Toglie i marcatori markdown leggeri usati dal prompt (**grassetto**,
    eventuali ### residui): il flusso on-demand resta un messaggio Telegram
    normale, senza parse_mode, quindi i marcatori andrebbero mostrati alla
    lettera se non tolti."""
    testo = re.sub(r"\*\*(.+?)\*\*", r"\1", markdown)
    testo = re.sub(r"^#{1,6}\s*", "", testo, flags=re.MULTILINE)
    return testo


async def _invia_a_pezzi(update: Update, testo: str):
    for pezzo in _spezza_messaggio(_testo_semplice(testo)):
        await update.message.reply_text(pezzo)


async def _elimina_messaggi(context: ContextTypes.DEFAULT_TYPE, coda) -> None:
    for r in coda:
        try:
            await context.bot.delete_message(chat_id=r["chat_id"], message_id=r["message_id"])
        except Exception:
            log.warning("Impossibile eliminare il messaggio %s in chat %s (probabilmente troppo vecchio)",
                        r["message_id"], r["chat_id"])


def solo_owner(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user is None or update.effective_user.id != config.TELEGRAM_OWNER_ID:
            return  # ignora silenziosamente, nessuna risposta
        return await handler(update, context)

    return wrapper


@solo_owner
async def aggiungi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /aggiungi @canale (o incolla il link t.me/...)")
        return
    canale = normalizza_canale(context.args[0])
    if db.aggiungi_canale(canale):
        await update.message.reply_text(f"Canale {canale} aggiunto.")
    else:
        await update.message.reply_text(f"Canale {canale} già presente.")


@solo_owner
async def rimuovi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /rimuovi @canale (o incolla il link t.me/...)")
        return
    canale = normalizza_canale(context.args[0])
    if db.rimuovi_canale(canale):
        await update.message.reply_text(f"Canale {canale} rimosso.")
    else:
        await update.message.reply_text(f"Canale {canale} non era in lista.")


@solo_owner
async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    canali = db.lista_canali()
    testo = "\n".join(canali) if canali else "Nessun canale in lista."
    await update.message.reply_text(testo)


@solo_owner
async def on_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text or update.message.caption
    if not testo:
        return
    db.accoda_messaggio(
        testo,
        chat_id=update.effective_chat.id,
        message_id=update.message.message_id,
        url=url_non_youtube(testo),
    )
    # silenzioso di proposito: nessuna risposta finché non arriva /analizza_messaggi


@solo_owner
async def analizza_messaggi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coda = db.messaggi_in_coda()
    if not coda:
        await update.message.reply_text("Nessun messaggio in coda.")
        return

    voci = [
        (f"messaggio delle {r['ricevuto_il']}" + (f" (fonte: {r['url']})" if r["url"] else ""), r["testo"])
        for r in coda
    ]
    testo_input = "\n\n".join(f"[{etichetta}] {testo}" for etichetta, testo in voci)

    stato = await update.message.reply_text("⏳ Avvio analisi...")

    loop = asyncio.get_running_loop()

    def aggiorna_stato(testo: str):
        # chiamato da un thread separato: va schedulato sull'event loop del bot
        asyncio.run_coroutine_threadsafe(stato.edit_text(testo), loop)

    try:
        risposta = await asyncio.to_thread(
            analyzer.genera_report_con_ricerca, voci, effort="low", on_progress=aggiorna_stato
        )
    except analyzer.AnalisiFallitaError:
        await stato.edit_text("❌ Claude Code non disponibile, riprova più tardi.")
        return

    db.log_analisi_on_demand(testo_input, risposta)
    await _elimina_messaggi(context, coda)
    db.svuota_coda()
    await stato.delete()
    await _invia_a_pezzi(update, risposta)


@solo_owner
async def scarta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coda = db.messaggi_in_coda()
    await _elimina_messaggi(context, coda)
    db.svuota_coda()
    await update.message.reply_text("Coda svuotata.")


@solo_owner
async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with open(db.DB_PATH, "rb") as f:
        await update.message.reply_document(document=f, filename="finance_bot.db")


@solo_owner
async def help_(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = "\n\n".join(f"/{nome} — {descrizione}" for nome, descrizione in COMANDI)
    await update.message.reply_text(testo)


async def _registra_menu_comandi(app: Application):
    await app.bot.set_my_commands([BotCommand(nome, descrizione) for nome, descrizione in COMANDI])


def main():
    db.init_db()
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(_registra_menu_comandi).build()

    app.add_handler(CommandHandler("aggiungi", aggiungi))
    app.add_handler(CommandHandler("rimuovi", rimuovi))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("scarta", scarta))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CommandHandler("help", help_))
    # underscore, non trattino: i comandi Telegram ufficiali ammettono solo [a-z0-9_]
    app.add_handler(CommandHandler("analizza_messaggi", analizza_messaggi))
    app.add_handler(MessageHandler(filters.FORWARDED & (filters.TEXT | filters.CAPTION), on_forward))

    log.info("Bot avviato (long polling)")
    app.run_polling()


if __name__ == "__main__":
    main()
