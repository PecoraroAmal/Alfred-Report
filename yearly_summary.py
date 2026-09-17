"""Oneshot invocato dal timer systemd del 1° gennaio a mezzanotte: aggrega i
riepiloghi mensili dell'anno appena chiuso (salvato subito), poi aspetta le
6:00 del mattino per l'invio effettivo del PDF."""

from datetime import datetime, timedelta

import analyzer
import db
import pipeline
from notifiche import FUSO_ITALIA, get_logger

log = get_logger("yearly_summary")


def main():
    db.init_db()
    oggi = datetime.now(FUSO_ITALIA)
    anno_chiuso = (oggi.replace(month=1, day=1) - timedelta(days=1)).strftime("%Y")

    righe = db.report_mensili_anno(anno_chiuso)
    if not righe:
        log.info("Nessun riepilogo mensile da comprimere per %s", anno_chiuso)
        return

    testo_input = "\n\n".join(f"### Riepilogo di {r['mese']}\n{r['testo']}" for r in righe)

    pipeline.genera_e_invia(
        etichetta=f"Riepilogo annuale di {anno_chiuso}",
        chiama_analyzer=lambda: analyzer.genera_riepilogo(testo_input, effort="high"),
        salva_db=lambda riepilogo: db.salva_report_annuale(anno_chiuso, riepilogo),
        nome_file=f"riepilogo_annuale_{anno_chiuso}.pdf",
        titolo_pdf=f"REPORT ANNUALE PRODOTTO IL {oggi.strftime('%d/%m/%Y')}",
        didascalia=f"Riepilogo annuale di {anno_chiuso}",
        # il job parte già alle 00:00 dello stesso giorno di invio, niente giorno_dopo
    )


if __name__ == "__main__":
    main()
