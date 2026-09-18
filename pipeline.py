"""Pipeline comune ai tre job oneshot (main.py, weekly_summary.py,
monthly_summary.py): chiama l'analyzer, salva su DB, genera il PDF, aspetta
l'orario di invio e lo manda. Estratta perché le tre pipeline erano quasi
identiche carattere per carattere."""

from typing import Callable

import analyzer
import pdf_report
from notifiche import attendi_fino_alle, get_logger, invia_documento

log = get_logger("pipeline")


def genera_e_invia(
    etichetta: str,
    chiama_analyzer: Callable[[], str],
    salva_db: Callable[[str], None],
    nome_file: str,
    titolo_pdf: str,
    didascalia: str,
    ora_invio: str = "06:00",
    giorno_dopo: bool = False,
    attendi: bool = True,
) -> bool:
    """Ritorna True solo se il report è stato davvero generato e inviato —
    False se saltato (Claude Code non disponibile). I chiamanti CLI (main.py
    e affini) usano questo valore per uscire con un codice diverso da 0 sui
    salti, così un sottoprocesso (es. lanciato da bot.py per /report) non
    dichiara falsamente successo quando in realtà non ha inviato nulla."""
    try:
        report = chiama_analyzer()
    except analyzer.AnalisiFallitaError:
        log.error("%s saltato: Claude Code non disponibile", etichetta)
        return False

    salva_db(report)

    with open(nome_file, "wb") as f:
        f.write(pdf_report.genera_pdf(report, titolo=titolo_pdf))

    if attendi:
        attendi_fino_alle(ora_invio, giorno_dopo=giorno_dopo)
    invia_documento(nome_file, didascalia=didascalia)
    log.info("%s inviato correttamente", etichetta)
    return True
