"""Oneshot invocato dal timer systemd della domenica sera: aggrega i report
giornalieri dell'ultima settimana in un unico riepilogo (salvato subito, per
la continuità del digest di lunedì), poi aspetta le 6:00 del mattino
successivo per l'invio effettivo del PDF."""

import sys
from datetime import datetime, timedelta

import analyzer
import db
import pipeline
from notifiche import FUSO_ITALIA, get_logger

log = get_logger("weekly_summary")


def main() -> bool:
    db.init_db()
    righe = db.report_ultimi_n_giorni(7)
    if not righe:
        log.info("Nessun report giornaliero da riassumere questa settimana")
        return False

    testo_input = "\n\n".join(f"### Report del {r['data']}\n{r['testo']}" for r in reversed(righe))

    oggi = datetime.now(FUSO_ITALIA)
    settimana_fine = oggi.strftime("%Y-%m-%d")
    domani = oggi + timedelta(days=1)

    return pipeline.genera_e_invia(
        etichetta=f"Riepilogo settimanale (fine {settimana_fine})",
        chiama_analyzer=lambda: analyzer.genera_riepilogo(testo_input, effort="high"),
        salva_db=lambda riepilogo: db.salva_report_settimanale(settimana_fine, riepilogo),
        nome_file=f"riepilogo_settimanale_{settimana_fine}.pdf",
        titolo_pdf=f"REPORT SETTIMANALE PRODOTTO IL {domani.strftime('%d/%m/%Y')}",
        didascalia=f"Riepilogo settimanale del {settimana_fine}",
        giorno_dopo=True,
    )


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
