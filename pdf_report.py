"""Rendering dei report in PDF: markdown -> HTML -> PDF (xhtml2pdf, puro Python
+ reportlab, nessuna dipendenza di sistema pesante come Pango/Cairo). La
colorazione del verdetto (VERO/FALSO/NON VERIFICABILE) è deterministica lato
codice via regex, non affidata al modello."""

import re

import markdown as md
from xhtml2pdf import pisa

_COLORE_VERDETTO = {
    "VERO": "#1a7f37",
    "FALSO": "#c0392b",
    "NON VERIFICABILE": "#595959",
}

# Fonte di verità unica per i verdetti validi: importata da analyzer.py per
# costruire il prompt, così prompt e colorazione non possono disallinearsi.
VERDETTI = list(_COLORE_VERDETTO)

_VERDETTO_RE = re.compile(
    r"(Fact check:\*{0,2}\s*)(" + "|".join(_COLORE_VERDETTO) + r")", re.IGNORECASE
)

_CSS = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; color: #1a1a1a; }
h1 { font-size: 16pt; color: #1a1a1a; border-bottom: 2px solid #1a1a1a; padding-bottom: 6px; }
strong { color: #111; }
p { line-height: 1.4; margin: 6px 0 12px 0; }
.verdetto { font-weight: bold; }
hr { border: none; border-top: 1px solid #999; margin: 18px 0; }
"""

_FACT_CHECK_RE = re.compile(r"^\*\*->\s*Fact check:", re.IGNORECASE)
_QUALSIASI_CAMPO_RE = re.compile(r"^\*\*->")


def _colora_verdetti(html: str) -> str:
    def sostituisci(m: re.Match) -> str:
        verdetto = m.group(2).upper()
        colore = _COLORE_VERDETTO.get(verdetto, "#1a1a1a")
        return f'{m.group(1)}<span class="verdetto" style="color:{colore}">{m.group(2)}</span>'

    return _VERDETTO_RE.sub(sostituisci, html)


_HR_MANUALE_RE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)


def _rimuovi_separatori_manuali(testo: str) -> str:
    """Il modello a volte inserisce righe '---' proprie nonostante il prompt
    lo vieti: le togliamo qui in modo deterministico, prima di inserire il
    nostro separatore lato codice, per evitare linee doppie."""
    return _HR_MANUALE_RE.sub("", testo)


def _forza_a_capo_su_frecce(testo: str) -> str:
    """Un singolo '\\n' in markdown è solo uno spazio per l'HTML risultante
    (a meno di una riga vuota o dell'estensione nl2br) — qui garantiamo
    comunque una riga vuota prima di ogni campo '**->' indipendentemente da
    come il modello ha effettivamente separato i campi nel testo grezzo."""
    return re.sub(r"\s*\*\*->", "\n\n**->", testo)


def _separa_voci(testo: str) -> str:
    """Inserisce una riga orizzontale tra una voce e la successiva (tranne
    prima della prima), lato codice: il modello non deve spendere token per
    marcare i confini tra le notizie. Il riassunto in apertura di voce è
    prosa libera senza etichetta '->', quindi l'unico campo sempre presente
    e riconoscibile è '**-> Fact check:**' — usato come ancora. Per ogni
    occorrenza (tranne la prima) si risale ai paragrafi liberi che la
    precedono (l'eventuale titolo/riassunto della voce) fino al primo
    paragrafo con un campo '->' (appartiene alla voce precedente) o
    all'inizio del testo, e si inserisce il separatore lì."""
    paragrafi = re.split(r"\n{2,}", testo)

    indici_fact_check = [i for i, p in enumerate(paragrafi) if _FACT_CHECK_RE.match(p.strip())]

    punti_di_taglio = set()
    for posizione, i in enumerate(indici_fact_check):
        if posizione == 0:
            continue  # prima voce: nessun separatore prima
        j = i - 1
        while j >= 0 and not _QUALSIASI_CAMPO_RE.match(paragrafi[j].strip()):
            j -= 1
        punto = j + 1
        if punto > 0:
            punti_di_taglio.add(punto)

    risultato = []
    for i, p in enumerate(paragrafi):
        if i in punti_di_taglio:
            risultato.append("---")
        risultato.append(p)
    return "\n\n".join(risultato)


def genera_pdf(testo_markdown: str, titolo: str) -> bytes:
    # la colorazione va fatta sul markdown grezzo, non sull'HTML: dopo la
    # conversione "Verifica:" è già avvolto in <strong>, e lo <span> inserito
    # qui sopravvive al passaggio di markdown.markdown() come HTML inline.
    testo_markdown = _rimuovi_separatori_manuali(testo_markdown)
    testo_markdown = _forza_a_capo_su_frecce(testo_markdown)
    testo_markdown = _separa_voci(testo_markdown)
    testo_markdown = _colora_verdetti(testo_markdown)
    corpo_html = md.markdown(testo_markdown, extensions=["nl2br"])
    html_completo = f"""<html>
<head><meta charset="utf-8"><style>{_CSS}</style></head>
<body>
<h1>{titolo}</h1>
{corpo_html}
</body>
</html>"""

    import io

    buffer = io.BytesIO()
    pisa.CreatePDF(html_completo, dest=buffer, encoding="utf-8")
    return buffer.getvalue()
