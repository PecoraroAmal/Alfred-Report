"""Orchestratore del job giornaliero (invocato dal timer systemd delle 5:00):
raccoglie tutti i canali, chiama l'analyzer con calma, salva l'archivio e il
PDF, poi aspetta le 6:00 in punto (ora italiana) per l'invio effettivo."""

import asyncio
from datetime import datetime

import analyzer
import collector
import db
import pipeline
from notifiche import FUSO_ITALIA, get_logger, notifica_owner

log = get_logger("main")


def _contesto_continuita(oggi: datetime) -> str:
    if oggi.weekday() == 0:  # lunedì: solo il riepilogo settimanale
        riga = db.ultimo_report_settimanale()
        if riga:
            return f"Riepilogo della settimana precedente:\n{riga['testo']}"
        return ""

    righe = db.report_ultimi_n_giorni(7)
    if not righe:
        return ""
    parti = [f"### Report del {r['data']}\n{r['testo']}" for r in reversed(righe)]
    return "Report dei giorni precedenti (per continuità):\n\n" + "\n\n".join(parti)


def main():
    db.init_db()
    oggi = datetime.now(FUSO_ITALIA)

    dati = asyncio.run(collector.raccogli_messaggi())
    if not dati:
        notifica_owner("ℹ️ Nessun messaggio raccolto nelle ultime 24 ore, nessun report generato.")
        return

    voci = [
        (f"{canale} delle ore {ora}" + (f" (fonte: {url})" if url else ""), testo)
        for canale, messaggi in dati.items()
        for ora, testo, url in messaggi
    ]
    contesto = _contesto_continuita(oggi)
    data_str = oggi.strftime("%Y-%m-%d")

    pipeline.genera_e_invia(
        etichetta=f"Report del {data_str}",
        chiama_analyzer=lambda: analyzer.genera_report_con_ricerca(voci, contesto=contesto, effort="high"),
        salva_db=lambda report: db.salva_report_giornaliero(data_str, report),
        nome_file=f"report_{oggi.strftime('%d-%m-%Y')}.pdf",
        titolo_pdf=f"REPORT GIORNALIERO PRODOTTO IL {oggi.strftime('%d/%m/%Y')}",
        didascalia=f"Report finanza/crypto del {oggi.strftime('%d/%m/%Y')}",
    )


if __name__ == "__main__":
    main()
