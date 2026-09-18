"""Orchestratore del job giornaliero (invocato dal timer systemd delle 5:00):
raccoglie tutti i canali, chiama l'analyzer con calma, salva l'archivio e il
PDF, poi aspetta le 6:00 in punto (ora italiana) per l'invio effettivo.
Due flag da riga di comando per l'uso on-demand da bot.py (/report,
/report_ieri): --immediato salta l'attesa fino alle 6:00; --ieri genera il
report del giorno solare precedente (00:00-23:59 Europe/Rome) invece della
finestra mobile delle ultime 24h."""

import asyncio
import sys
from datetime import datetime, timedelta

import analyzer
import collector
import db
import pipeline
from notifiche import FUSO_ITALIA, get_logger, notifica_owner

log = get_logger("main")


def _contesto_continuita(giorno: datetime) -> str:
    if giorno.weekday() == 0:  # lunedì: solo il riepilogo settimanale
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
    immediato = "--immediato" in sys.argv  # /report, /report_ieri: niente attesa fino alle 6:00
    ieri = "--ieri" in sys.argv  # /report_ieri: solo il giorno solare precedente

    oggi = datetime.now(FUSO_ITALIA)
    giorno_target = oggi - timedelta(days=1) if ieri else oggi

    if ieri:
        dati = asyncio.run(collector.raccogli_messaggi_giorno(giorno_target.date()))
    else:
        dati = asyncio.run(collector.raccogli_messaggi())

    if not dati:
        notifica_owner(
            f"ℹ️ Nessun messaggio raccolto per il {giorno_target.strftime('%d/%m/%Y')}, "
            "nessun report generato."
        )
        return

    voci = [
        (f"{canale} delle ore {ora}" + (f" (fonte: {url})" if url else ""), testo)
        for canale, messaggi in dati.items()
        for ora, testo, url in messaggi
    ]
    contesto = _contesto_continuita(giorno_target)
    data_str = giorno_target.strftime("%Y-%m-%d")

    pipeline.genera_e_invia(
        etichetta=f"Report del {data_str}",
        chiama_analyzer=lambda: analyzer.genera_report_con_ricerca(voci, contesto=contesto, effort="high"),
        salva_db=lambda report: db.salva_report_giornaliero(data_str, report),
        nome_file=f"report_{giorno_target.strftime('%d-%m-%Y')}.pdf",
        titolo_pdf=f"REPORT GIORNALIERO PRODOTTO IL {giorno_target.strftime('%d/%m/%Y')}",
        didascalia=f"Report finanza/crypto del {giorno_target.strftime('%d/%m/%Y')}",
        attendi=not immediato,
    )


if __name__ == "__main__":
    main()
