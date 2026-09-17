"""Oneshot invocato dal timer systemd del 1° del mese a mezzanotte: aggrega i
riepiloghi settimanali del mese appena chiuso (salvato subito), poi aspetta
le 6:00 del mattino per l'invio effettivo del PDF."""

from datetime import datetime, timedelta

import analyzer
import db
import pipeline
from notifiche import FUSO_ITALIA, get_logger

log = get_logger("monthly_summary")


def main():
    db.init_db()
    oggi = datetime.now(FUSO_ITALIA)
    mese_chiuso = (oggi.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    righe = db.report_settimanali_mese(mese_chiuso)
    if not righe:
        log.info("Nessun riepilogo settimanale da comprimere per %s", mese_chiuso)
        return

    testo_input = "\n\n".join(
        f"### Riepilogo settimana conclusa il {r['settimana_fine']}\n{r['testo']}" for r in righe
    )

    pipeline.genera_e_invia(
        etichetta=f"Riepilogo mensile di {mese_chiuso}",
        chiama_analyzer=lambda: analyzer.genera_riepilogo(testo_input, effort="high"),
        salva_db=lambda riepilogo: db.salva_report_mensile(mese_chiuso, riepilogo),
        nome_file=f"riepilogo_mensile_{mese_chiuso}.pdf",
        titolo_pdf=f"REPORT MENSILE PRODOTTO IL {oggi.strftime('%d/%m/%Y')}",
        didascalia=f"Riepilogo mensile di {mese_chiuso}",
        # il job parte già alle 00:00 dello stesso giorno di invio, niente giorno_dopo
    )


if __name__ == "__main__":
    main()
