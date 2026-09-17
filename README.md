# Alfred-Report

Bot Telegram che legge quotidianamente i canali finanza/crypto seguiti
dall'utente, li analizza con Claude Code applicando un framework critico
per notizia (riassunto, fact check verificato con ricerca web, riflessione
critica e conseguenze sempre presenti, fonti e canale di origine), e
restituisce un report in PDF. Include un flusso on-demand per analizzare al
volo messaggi inoltrati manualmente.

## Come funziona

- **Raccolta**: [Telethon](https://docs.telethon.dev) (Client API) legge solo
  i canali salvati in `canali` — mai la lista completa delle chat dell'utente.
  Finestra mobile di 24 ore, solo testo: audio/vocali e immagini vengono
  ignorati, i link YouTube vengono ignorati, la firma automatica del canale
  (se attiva) viene ripulita dal testo. Gli orari dei messaggi sono sempre in
  ora italiana (Europe/Rome), indipendentemente dal fuso orario del server.
- **Analisi**: unico motore **Claude Code** (`claude -p`, tramite abbonamento
  personale — nessun costo a consumo), eseguito in modalità `--restricted`
  (niente Bash/esecuzione codice) con `WebSearch` e `WebFetch` riabilitati,
  così verifica le notizie e apre da solo i link trovati nei messaggi,
  dando priorità a un elenco di fonti finanziarie affidabili (Milano
  Finanza, Yahoo Finance, Repubblica, ANSA, Investing.com). **Nessun
  fallback**: se Claude Code non risponde (errore, timeout), quel report non
  viene generato — arriva solo una notifica di errore, mai un report
  parziale o prodotto da un motore meno affidabile. Ogni report riporta in
  fondo il consumo esatto di token (ingresso, ragionamento, uscita) e il
  tempo impiegato, letti direttamente dalla risposta di Claude Code (mai
  stimati).
- **Framework per notizia**: ogni voce del report ha un riassunto in prosa
  libera, poi `Fact check` (VERO/FALSO/NON VERIFICABILE), una `Riflessione`
  critica e le `Conseguenze` — **sempre presenti, anche sulle notizie false
  o non verificabili** (es. ipotesi sul perché una notizia falsa circola) —
  e infine `Fonti` e `Canali telegram` di origine direttamente dentro la
  voce, senza rimandi a fine report. Un'unica sezione `Spiegazioni`
  (glossario dei termini tecnici usati) può comparire una sola volta a fine
  report, se serve.
- **Output in PDF**: markdown leggero (grassetto sulle etichette `->`)
  convertito in PDF con il verdetto di ogni notizia colorato (verde=VERO,
  rosso=FALSO, grigio=NON VERIFICABILE) e una riga di separazione tra una
  voce e l'altra — vedi `pdf_report.py`.
- **Consegna sempre alle 6:00 (ora italiana)**: i job notturni partono prima
  (05:00 per il digest giornaliero) per dare tempo a un'analisi più
  approfondita, ma l'invio effettivo su Telegram avviene sempre esattamente
  alle 6:00, mai prima — vedi `notifiche.attendi_fino_alle()`.
- **Continuità narrativa**: ogni report giornaliero riceve come contesto gli
  ultimi 7 giorni in ordine cronologico (o il riepilogo della settimana
  precedente, se è lunedì). Ogni domenica sera viene generato un riepilogo
  settimanale; il primo di ogni mese un riepilogo mensile; il 1° gennaio un
  riepilogo annuale che comprime i 12 riepiloghi mensili dell'anno appena
  chiuso — tutti inviati come PDF, sempre alle 6:00 del mattino
  successivo/dello stesso giorno.
- **On-demand**: i messaggi inoltrati al bot restano in coda senza essere
  analizzati finché non arriva `/analizza_messaggi`, che li analizza tutti
  insieme (deduplicando le notizie ripetute) mostrando lo stato di
  avanzamento in tempo reale, risponde in chat come testo semplice (il
  markdown viene ripulito, qui non c'è PDF) e poi elimina i messaggi
  inoltrati dalla chat.
- **Whitelist**: solo `TELEGRAM_OWNER_ID` può usare il bot. Chiunque altro
  viene ignorato del tutto, senza alcuna risposta.

## Struttura del progetto

```
db.py               - SQLite: canali, archivio report (giornalieri/
                       settimanali/mensili), coda on-demand, log analisi
config.py           - caricamento .env, fail-fast se manca una variabile
notifiche.py        - logging su file, invio documenti/notifiche di errore,
                      attendi_fino_alle() per la consegna alle 6:00 italiane
collector.py        - Telethon: raccolta messaggi ultime 24h (Europe/Rome)
analyzer.py         - genera_report()/genera_report_con_ricerca()/
                      genera_riepilogo(): unico motore Claude Code, nessun
                      fallback, conteggio token esatto
pdf_report.py       - rendering markdown -> PDF con colorazione del verdetto
                      e separatori tra voci
pipeline.py         - flusso comune ai job oneshot (analizza -> salva DB ->
                      PDF -> attesa 6:00 -> invio), usato da main.py/
                      weekly_summary.py/monthly_summary.py/yearly_summary.py
login_telethon.py   - login one-time interattivo di Telethon (una tantum)
bot.py              - servizio long-running: comandi Telegram e coda on-demand
main.py             - oneshot (timer 5:00, invio 6:00): report giornaliero
weekly_summary.py   - oneshot (timer domenica sera, invio 6:00): riepilogo
                      settimanale
monthly_summary.py  - oneshot (timer 1° del mese, invio 6:00): riepilogo
                      mensile
yearly_summary.py   - oneshot (timer 1° gennaio, invio 6:00): riepilogo
                      annuale
deploy/             - unit systemd (bot + quattro timer) pronti per la VPS
```

## Setup locale

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # poi compila .env con le tue credenziali
```

Serve anche la [Claude Code CLI](https://docs.claude.com/claude-code) installata
e autenticata con `claude login` (abbonamento personale) sulla macchina che
esegue il bot — è il motore di analisi primario, invocato come sottoprocesso
da `analyzer.py`. Verifica che `ANTHROPIC_API_KEY` non sia impostata
nell'ambiente: se presente verrebbe usata al posto del login abbonamento,
con fatturazione a consumo separata.

Variabili richieste in `.env`:

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_ID` — bot Telegram (BotFather) e il
  tuo user id (non lo username), per la whitelist.
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — Client API da
  [my.telegram.org](https://my.telegram.org), usata da Telethon.

Login one-time di Telethon (numero di telefono + OTP, e password 2FA se
attiva) — va fatto una sola volta, il file di sessione risultante
(`TELETHON_SESSION_PATH`) va poi copiato anche sulla VPS al momento del
deploy:

```bash
.venv/bin/python login_telethon.py
```

Avvio manuale dei componenti:

```bash
.venv/bin/python bot.py             # servizio comandi, sempre attivo
.venv/bin/python main.py            # report giornaliero (va poi schedulato)
.venv/bin/python weekly_summary.py  # riepilogo settimanale
.venv/bin/python monthly_summary.py # riepilogo mensile
```

## Comandi del bot

| Comando | Descrizione |
|---|---|
| `/aggiungi @canale` | Aggiunge un canale da monitorare (accetta anche il link `t.me/...`) |
| `/rimuovi @canale` | Rimuove un canale monitorato |
| `/lista` | Mostra i canali attualmente monitorati |
| `/analizza_messaggi` | Analizza subito i messaggi inoltrati finora e svuota la coda |
| `/scarta` | Svuota la coda senza analizzare |
| `/backup` | Invia una copia del database (canali + archivio report) |
| `/help` | Elenco comandi con spiegazione |

## Deploy (VPS, systemd)

I file in `deploy/` sono pensati per una VPS raggiungibile solo via
[Tailscale](https://tailscale.com) (il bot usa long-polling, non serve alcun
webhook/porta esposta). Adatta i percorsi (`WorkingDirectory`,
`EnvironmentFile`, `ExecStart`) alla tua installazione, poi:

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now finance-digest-bot.service
sudo systemctl enable --now finance-digest-daily.timer
sudo systemctl enable --now finance-digest-weekly.timer
sudo systemctl enable --now finance-digest-monthly.timer
sudo systemctl enable --now finance-digest-yearly.timer
```

Assicurati che l'utente con cui girano questi servizi abbia già eseguito
`claude login` (sessione salvata, riusabile senza terminale interattivo) e
che il file di sessione Telethon sia stato copiato nella cartella del
progetto sulla VPS.

## File esclusi dal repository

`.env`, il file di sessione Telethon (`*.session`), il database SQLite
(`*.db`) e i PDF/log generati a runtime restano solo in locale/sulla VPS: non
vengono mai versionati (vedi `.gitignore`).
