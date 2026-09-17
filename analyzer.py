"""Isola la chiamata all'LLM: Claude Code (abbonamento, via `claude -p`) è
l'unico motore di analisi. Nessun fallback: se non risponde, l'analisi
fallisce e viene notificato l'owner — niente di silenzioso o parziale."""

import json
import os
import subprocess
from typing import Callable, Optional

from notifiche import get_logger, notifica_owner
from pdf_report import VERDETTI

log = get_logger("analyzer")

FONTI_AFFIDABILI = [
    "milanofinanza.it",
    "finance.yahoo.com",
    "repubblica.it",
    "ansa.it",
    "investing.com",
]

_VERDETTI_SLASH = " / ".join(VERDETTI)
_VERDETTI_VIRGOLA = f"{', '.join(VERDETTI[:-1])} o {VERDETTI[-1]}"

PROMPT_FRAMEWORK = f"""Sei un analista finanziario critico. Analizza i messaggi
qui sotto (organizzati per canale/fonte Telegram) e produci un report in
ITALIANO.

LINGUAGGIO: scrivi in modo chiaro e accessibile, evita gergo tecnico non
necessario. Per i pochi termini tecnici indispensabili (es. "perpetual
futures") usa la sezione Spiegazioni descritta più sotto, non spiegarli
inline nel corpo della voce.

RICERCA: verifica ogni notizia PRIMA di scrivere la voce (ricerca web/lettura
di eventuali link presenti nel messaggio). Dai priorità a questi siti
finanziari affidabili: {", ".join(FONTI_AFFIDABILI)}. Usa altre fonti solo se
questi non hanno nulla di pertinente sull'argomento. Se il messaggio contiene
un link diretto a un articolo, aprilo e leggilo davvero, non limitarti a
cercarne conferma altrove.

FORMATTAZIONE, OBBLIGATORIA E SENZA ECCEZIONI: ogni voce inizia con un
riassunto in prosa semplice (una o due frasi, SENZA etichetta né prefisso
"->" — è l'unico campo senza), poi ogni campo successivo va SEMPRE su una
riga propria, col prefisso "->" e l'etichetta in **grassetto**, es.:
Il canale segnala che l'azienda X ha annunciato Y.
**-> Fact check:** VERO
Questo vale anche per le notizie che raggruppi perché già trattate in
precedenza: non scriverle mai come prosa continua in un unico paragrafo.
Non usare altra sintassi markdown (niente ###, elenchi puntati con -,
backtick, tabelle). Scrivi il verdetto del Fact check ({_VERDETTI_SLASH})
in testo semplice, senza grassetto né colore: ci pensa il
codice a evidenziarlo dopo. Non inserire tu stesso righe di separazione tra
una voce e l'altra (niente ---, ***, ___ o simili): ci pensa il codice a
separare visivamente le voci nel PDF finale.

OUTPUT, SOLO IL REPORT: la tua risposta finale deve iniziare direttamente con
il report (titolo generale se lo scrivi, poi le voci). Non anticipare nulla
con frasi di commento sul tuo processo (es. "ho verificato tutte le notizie,
ora scrivo il report", "procedo con l'analisi") né altre meta-note: quel
testo finirebbe copiato as-is nel PDF inviato all'utente.

REGOLA DI COMPLETEZZA, OBBLIGATORIA: ogni singolo messaggio fornito in input
deve comparire in almeno una voce del report (da solo o raggruppato con
altri). Non ometterne MAI silenziosamente nemmeno uno. Se un messaggio non è
rilevante dal punto di vista finanziario (spam, meme, argomento non
pertinente), non ignorarlo: fagli comunque una voce minima con scritto "Non
pertinente all'analisi finanziaria" — questo conta come averlo trattato.

Prima di scrivere, raggruppa i messaggi per argomento: se più messaggi (anche
da canali diversi) parlano della stessa notizia/evento, trattali come UNA SOLA
voce — non ripetere la stessa analisi più volte solo perché più fonti hanno
riportato la stessa cosa. Il raggruppamento unisce notizie duplicate, non è
una scusa per ometterne qualcuna né per abbandonare la struttura a campi
separati.

Per ogni voce/argomento (dopo il raggruppamento), in quest'ordine:

Riassunto in prosa semplice (una o due frasi, senza etichetta): cosa dice il
messaggio. Se riporta una dichiarazione attribuita a una persona (es. "X ha
detto..."), riporta qui solo cosa viene attribuito, senza ancora valutarla.

**-> Fact check:** {_VERDETTI_VIRGOLA}. Per le dichiarazioni
attribuite, verifica PRIMA se la persona ha davvero detto quella cosa
(l'attribuzione stessa), non solo se il fatto sottostante è plausibile. Se è
chiaramente hype/pump senza riscontri, dillo apertamente.

**-> Riflessione:** SEMPRE presente, qualsiasi sia l'esito del fact check.
Poniti (e rispondi) alcune domande critiche a partire dal testo: perché viene
detto questo? cosa lo motiva? è plausibile? c'è un angolo scettico da
considerare (hype, FOMO, interesse di chi lo dice)? Se il Fact check è FALSO
o NON VERIFICABILE, la riflessione va comunque scritta ma orientata a
ipotizzare perché quella notizia potrebbe essere stata diffusa (es.
pump-and-dump, disinformazione, chi ci guadagna) — mai inventare conseguenze
di mercato come se il fatto fosse vero.

**-> Conseguenze:** SEMPRE presente. Cosa potrebbe succedere dopo, comprese
letture scettiche/alternative quando pertinenti (es. "se è FOMO, forse serve
a far vendere prima che il prezzo scenda").

**-> Fonti:** un URL per riga, quelli usati per il fact check/la lettura del
link. Se non ce ne sono, scrivi "nessuna fonte esterna".

**-> Canali telegram:** un link nel formato https://t.me/<username> per
riga, uno per ogni canale che ha riportato questa notizia (più righe se la
voce raggruppa più messaggi/canali). Costruisci il link meccanicamente a
partire dallo username indicato nell'etichetta della fonte fornita nel
testo — non inventarlo. Se il messaggio non riporta un canale di origine
riconoscibile, scrivi "canale non disponibile".

Dopo tutte le voci, una sola volta (non ripetuta per voce):

**-> Spiegazioni:** solo se nel report compaiono termini tecnici che
meritano una spiegazione breve (es. "perpetual futures: ..."); ometti del
tutto questa sezione se non serve, non forzarla.

Se ti vengono forniti report precedenti come contesto per la continuità, e una
notizia di oggi è un aggiornamento di qualcosa già trattato, segnalalo tu
stesso nel testo (es. "Aggiornamento rispetto a ieri: ...").
"""

PROMPT_RIEPILOGO = """Sei un analista finanziario. Ti vengono forniti più report
già scritti in italiano (giornalieri o settimanali). Producine un UNICO
riepilogo comprensivo in ITALIANO, organizzato per categoria (es. crypto,
azionario, macro), che mantenga i fatti e le cifre chiave (es. massimi/minimi
con relativa data per i principali asset citati), utile come contesto storico
per il periodo successivo.

LINGUAGGIO: scrivi in modo chiaro e accessibile, evita gergo tecnico non
necessario.

FORMATTAZIONE: usa markdown leggero — **grassetto** solo per le intestazioni
di categoria (es. **Crypto**, **Azionario**, **Macro**). Non usare altra
sintassi markdown (niente ###, elenchi puntati con -, backtick, tabelle).

Non ripetere la struttura punto-per-punto dei report di partenza: qui serve
una sintesi discorsiva ma densa di informazioni verificabili.
"""


class AnalisiFallitaError(Exception):
    pass


ProgressCallback = Optional[Callable[[str], None]]

CLAUDE_MODEL = "claude-sonnet-5"
_TIMEOUT_PER_EFFORT = {"low": 180}
_TIMEOUT_DEFAULT = 600  # medium/high/xhigh/max: digest e riepiloghi, più ricerche web


def _fmt(n: Optional[int]) -> str:
    return "n.d." if n is None else f"{n:,}".replace(",", ".")


def _fmt_secondi(secondi: Optional[float]) -> str:
    if secondi is None:
        return "n.d."
    return f"{secondi:.1f}".replace(".", ",") + " secondi"


def _footer_info_ai(usage: dict) -> str:
    return (
        "**-> Info sull'AI:**\n"
        f"**-> Modello:** {CLAUDE_MODEL} (Claude Code)\n"
        f"**-> Token:** {_fmt(usage.get('ingresso'))} in ingresso, "
        f"{_fmt(usage.get('ragionamento'))} di ragionamento, "
        f"{_fmt(usage.get('uscita'))} in uscita\n"
        f"**-> Tempo:** {_fmt_secondi(usage.get('secondi'))}"
    )


def _chiama_claude_code(prompt_sistema: str, testo: str, effort: str) -> tuple[str, dict]:
    """Chiama il motore di analisi (abbonamento, nessun costo a consumo).
    --restricted toglie Bash/PowerShell/REPL/esecuzione codice; riabilitiamo
    WebSearch (ricerca) e WebFetch (lettura diretta dei link nei messaggi).
    Niente --dangerously-skip-permissions: quel flag è documentato dalla CLI
    stessa come adatto solo a sandbox senza accesso a internet, l'opposto del
    nostro caso (contenuto pubblico non fidato da canali Telegram).
    --output-format json ci dà anche il conteggio esatto dei token e il
    tempo impiegato, non solo il testo."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)  # forza il login abbonamento, mai billing a consumo

    cmd = [
        "claude", "-p",
        "--model", CLAUDE_MODEL,
        "--effort", effort,
        "--output-format", "json",
        "--restricted",
        "--allowedTools", "WebSearch,WebFetch",
        "--append-system-prompt", prompt_sistema,
    ]
    risultato = subprocess.run(
        cmd,
        input=testo,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_PER_EFFORT.get(effort, _TIMEOUT_DEFAULT),
        env=env,
    )
    if risultato.returncode != 0:
        raise RuntimeError(
            f"claude -p uscito con codice {risultato.returncode}: {risultato.stderr[:500]}"
        )
    dati = json.loads(risultato.stdout)
    output = (dati.get("result") or "").strip()
    if not output:
        raise RuntimeError("Risposta vuota da claude -p")

    u = dati.get("usage", {})
    usage = {
        "ingresso": u.get("input_tokens", 0)
        + u.get("cache_creation_input_tokens", 0)
        + u.get("cache_read_input_tokens", 0),
        "ragionamento": u.get("output_tokens_details", {}).get("thinking_tokens", 0),
        "uscita": u.get("output_tokens", 0),
        "secondi": dati["duration_ms"] / 1000 if "duration_ms" in dati else None,
    }
    return output, usage


def _genera(
    prompt_sistema: str, testo: str, effort: str = "medium", on_progress: ProgressCallback = None
) -> str:
    """Solleva AnalisiFallitaError (con notifica all'owner) se Claude Code
    non risponde. Nessun fallback: niente report quel giorno piuttosto che
    uno parziale/generato da un modello meno affidabile."""
    if on_progress:
        on_progress(f"Ok, analizzo subito con: {CLAUDE_MODEL}, attendi...")
    try:
        risposta, usage = _chiama_claude_code(prompt_sistema, testo, effort)
    except Exception:
        log.exception("Claude Code non disponibile")
        if on_progress:
            on_progress("❌ Claude Code non disponibile, analisi saltata.")
        notifica_owner("❌ Claude Code non disponibile: analisi saltata, riprova più tardi.")
        raise AnalisiFallitaError("Claude Code non ha risposto")
    if on_progress:
        on_progress(f"✅ Risposta ricevuta da {CLAUDE_MODEL}, la preparo...")
    return f"{risposta}\n\n{_footer_info_ai(usage)}"


def genera_report(testo: str, effort: str = "medium", on_progress: ProgressCallback = None) -> str:
    return _genera(PROMPT_FRAMEWORK, testo, effort, on_progress)


def _costruisci_testo(voci: list[tuple[str, str]], contesto: str = "") -> str:
    blocchi = [f"### {fonte}\n{testo_msg}" for fonte, testo_msg in voci]
    testo = "\n\n---\n\n".join(blocchi)
    return f"{contesto}\n\n---\n\n{testo}" if contesto else testo


def genera_report_con_ricerca(
    voci: list[tuple[str, str]],
    contesto: str = "",
    effort: str = "medium",
    on_progress: ProgressCallback = None,
) -> str:
    """voci: lista di (etichetta_fonte, testo_messaggio). contesto (opzionale)
    viene anteposto a tutto (es. i report dei giorni precedenti, per la
    continuità). Claude Code cerca/legge online da solo (WebSearch/WebFetch)."""
    return _genera(PROMPT_FRAMEWORK, _costruisci_testo(voci, contesto), effort, on_progress)


def genera_riepilogo(testo: str, effort: str = "medium", on_progress: ProgressCallback = None) -> str:
    return _genera(PROMPT_RIEPILOGO, testo, effort, on_progress)
