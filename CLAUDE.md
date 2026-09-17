# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot (Finance Digest Bot) that reads finance/crypto Telegram channels via
Telethon, analyzes messages with Claude Code (via `claude -p`, subscription-based, no
per-token billing) and produces italian-language reports as PDF. See README.md for the
user-facing feature description and setup steps — this file focuses on things you need
to know to safely modify the code.

## Commands

No build step (pure Python, stdlib `sqlite3` + a few packages). No test suite exists yet.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in real credentials before running anything

# quick syntax check after edits (there is no test suite):
python3 -m py_compile *.py

# one-time Telethon login (interactive: phone number + OTP + optional 2FA password)
.venv/bin/python login_telethon.py

# run components manually
.venv/bin/python bot.py             # long-running, Bot API long-polling
.venv/bin/python main.py            # oneshot: daily report
.venv/bin/python weekly_summary.py  # oneshot: weekly summary
.venv/bin/python monthly_summary.py # oneshot: monthly summary
```

The `claude` CLI must be installed and already logged in (`claude login`) as whichever
OS user runs these scripts — `analyzer.py` shells out to it and explicitly strips
`ANTHROPIC_API_KEY` from the subprocess environment so the subscription session is used
instead of metered API billing (see below).

Deploy uses the systemd units in `deploy/` (one long-running service for `bot.py`, four
oneshot service+timer pairs for the daily/weekly/monthly/yearly scripts) — see
README.md for the `systemctl` commands. The unit files hardcode the VPS path
(`/home/amal/progetti/Alfred-Report`), which is deliberately different from wherever you
develop locally — no code hardcodes a filesystem path anywhere (`config.py`/`db.py`
resolve `DB_PATH`/`LOG_PATH`/`TELETHON_SESSION_PATH` relative to `.env` or the module's
own directory), so cloning the repo to a different absolute path never breaks anything
as long as the unit files' `WorkingDirectory`/`EnvironmentFile`/`ExecStart` match where
it actually lives.

**Every unit file also sets `Environment=PATH=...` explicitly**, including the VPS's
nvm-managed Node bin directory (`/home/amal/.nvm/versions/node/v24.19.0/bin`) ahead of
the standard system paths. This is required, not cosmetic: `claude` (the CLI
`analyzer.py` shells out to) was installed via `npm install -g` under nvm, so it lives
outside systemd's default minimal `PATH` — without this, every `subprocess.run(["claude",
...])` call would fail with "command not found" the moment a job runs unattended. If
Node is ever upgraded via `nvm install`, this path needs updating in all five `.service`
files to match the new version directory (`nvm current` on the VPS shows the active one).

## Architecture

**Two independent process types that never share Telethon's session concurrently:**
- `bot.py` — long-running, Telegram Bot API long-polling only (no Telethon). Handles
  `/aggiungi`, `/rimuovi`, `/lista`, the on-demand queue (`/analizza_messaggi`, `/scarta`),
  and `/backup`. Long-polling is mandatory, not a choice — the deployment target (a VPS
  reachable only via Tailscale) cannot receive webhooks.
- `main.py` / `weekly_summary.py` / `monthly_summary.py` — oneshot scripts triggered by
  systemd timers. Only `main.py` touches Telethon (`collector.py`), once a day.

**Claude Code is the only analysis engine — there is no fallback.** `analyzer.py`'s
`_genera()` shells out to `claude -p` (`_chiama_claude_code()`) with `--restricted`
(disables Bash/PowerShell/REPL/code execution) and `--allowedTools "WebSearch,WebFetch"`
re-enabled explicitly, so Claude Code can search the web and open links found in
messages by itself but can't execute arbitrary commands — deliberately *not*
`--dangerously-skip-permissions`, which the CLI's own `--help` describes as suitable
only for sandboxes with no internet access (the opposite of this case: a VPS with
internet access processing untrusted public Telegram content, where that flag would
give a crafted prompt-injection post full Bash/filesystem access with no confirmation
gate). If `claude -p` fails (non-zero exit, timeout, empty output), `_genera()` logs it,
notifies the owner, and raises `AnalisiFallitaError` — **no report is generated or sent
that day**, on purpose, rather than falling back to a less capable/less trusted model.
OpenRouter/Gemini/`ddgs` were deliberately removed in favor of this (see git history);
don't reintroduce a fallback chain without an explicit user decision to do so.
`--output-format json` (not `text`) is used specifically to get exact token counts and
elapsed time from the response (`usage`/`duration_ms`), not just the answer text.

**Effort levels**: `main.py`/`weekly_summary.py`/`monthly_summary.py` all pass
`effort="high"` — the digest job now starts at 05:00 specifically to give Claude Code an
hour of slack for a more thorough analysis; `bot.py`'s `/analizza_messaggi` passes
`effort="low"` since the user is waiting live in chat for a small on-demand batch.

**Delivery is always exactly at 06:00 Europe/Rome, never earlier** — confirmed
requirement, not a default. `notifiche.attendi_fino_alle(ora="06:00", giorno_dopo=False)`
computes the wait using `FUSO_ITALIA = ZoneInfo("Europe/Rome")` explicitly, never the
host's system timezone (a VPS defaulting to UTC would otherwise send/timestamp things
1-2 hours off). `giorno_dopo=True` is for jobs that start the evening/night before their
target morning (`weekly_summary.py`); `main.py`/`monthly_summary.py` start same-day and
use the default. Because the process sleeps (`time.sleep`) for up to ~1 hour waiting for
that window, all three oneshot systemd `.service` files need `TimeoutStartSec=infinity`
(systemd's default 90s would otherwise kill them mid-wait) — don't remove that when
touching the units.

**`pipeline.py` factors out the shared oneshot flow**: `main.py`, `weekly_summary.py`,
`monthly_summary.py`, and `yearly_summary.py` each only build their own input
text/context, then call `pipeline.genera_e_invia(etichetta, chiama_analyzer, salva_db,
nome_file, titolo_pdf, didascalia, ora_invio, giorno_dopo)`, which handles calling the
analyzer (catching `AnalisiFallitaError`), saving to the DB, rendering the PDF, waiting
until the delivery time, sending it, and logging — in that order, always. Don't
duplicate this flow inline in a caller; add a parameter to `pipeline.genera_e_invia`
instead if a future report type needs something slightly different.

**Report hierarchy for continuity, not just archival**: `report_giornalieri` (daily) →
`report_settimanali` (generated Sunday night from the last 7 daily reports) →
`report_mensili` (generated on the 1st from that month's weekly summaries) →
`report_annuali` (generated Jan 1st from that year's 12 monthly summaries). `main.py`'s
`_contesto_continuita()` picks what context to prepend: on Mondays it's *only* the
latest weekly summary (not raw daily reports), other days it's the last 7 daily reports
— this is intentional, not a bug. `db.report_ultimi_n_giorni()` returns rows
most-recent-first (`ORDER BY data DESC`, needed for the `LIMIT`); both `main.py` and
`weekly_summary.py` explicitly `reversed()` them before building the prompt text, so the
model reads oldest-to-newest like a real timeline — don't drop that `reversed()` if you
touch either function. `db.report_settimanali_mese()`/`db.report_mensili_anno()` (used
by `monthly_summary.py`/`yearly_summary.py`) are already ascendant by their date column,
no reversal needed there. `yearly_summary.py` follows the exact same shape as
`monthly_summary.py` (job starts same-day at 00:00 on Jan 1st, no `giorno_dopo`) — both
reuse `PROMPT_RIEPILOGO`/`analyzer.genera_riepilogo()`, since compressing weekly reports
into a month or monthly reports into a year is the same kind of narrative synthesis.

**Report format is a strict per-item `->` framework, not free prose** (`PROMPT_FRAMEWORK`
in `analyzer.py`): each item opens with an unlabeled plain-prose summary sentence, then
`**-> Fact check:**` / `**-> Riflessione:**` / `**-> Conseguenze:**` / `**-> Fonti:**` /
`**-> Canali telegram:**`, each on its own line, bold label. **Riflessione and
Conseguenze are always written, even when Fact check is FALSO/NON VERIFICABILE** —
deliberately, oriented toward *why a false claim might be circulating* (pump-and-dump,
disinformation) rather than being skipped; this is a explicit design choice, not a gap.
Fonti/Canali telegram live inside each item (no more numbered `[1][2]` + one master
list at the end) so an item is self-contained. A single optional `**-> Spiegazioni:**`
glossary can appear once at the very end of the whole report, never per-item. The valid
verdict strings (`VERO`/`FALSO`/`NON VERIFICABILE`) are defined once as `pdf_report.VERDETTI`
and imported into the prompt (`_VERDETTI_SLASH`/`_VERDETTI_VIRGOLA` in `analyzer.py`) so
the prompt and the PDF's color-coding can't silently drift apart — if you ever add a
verdict, add it to `pdf_report._COLORE_VERDETTO` and both sides pick it up automatically.
The completeness rule (every input message must appear in at least one item, even as
"non pertinente") has no numbered-note wording anymore since the `[1][2]` scheme is gone
— don't reintroduce numbered citations, they were deliberately dropped.

**`pdf_report.py` renders the model's markdown into PDF** (`markdown` → HTML →
`xhtml2pdf`, pure Python + reportlab, no heavy system deps like Pango/Cairo — chosen for
a 2GB RAM VPS). Verdict coloring (green=VERO, red=FALSO, gray=NON VERIFICABILE) is done
by regex on the raw markdown before HTML conversion, deterministically, never left to the
model. `_rimuovi_separatori_manuali()` strips any `---`/`***`/`___` the model writes on
its own (it sometimes does despite being told not to) *before* `_separa_voci()` inserts
its own horizontal rule between items — anchored on `**-> Fact check:**` (the only
always-present labeled field per item, since the opening summary is unlabeled prose) and
walking backward through unlabeled paragraphs to place the rule before an item's title/
summary rather than in the middle of it. `_forza_a_capo_su_frecce()` + the `nl2br`
markdown extension force every `**->` field onto its own visual line — a single `\n` in
markdown is otherwise just a space, and this was an earlier bug report (see git history).
The footer (`**-> Info sull'AI:**` block with model/token counts/elapsed time) is built
entirely in code (`analyzer._footer_info_ai()`) from the exact `usage`/`duration_ms`
fields Claude Code returns, never estimated.

**On-demand queue is deliberately two-phase**: forwarded messages land silently in
`messaggi_pendenti` (bot.py never replies to a forward) and are only read, analyzed as a
batch, and deleted from the chat when `/analizza_messaggi` runs. `bot.py` runs the actual
LLM call via `asyncio.to_thread` + `asyncio.run_coroutine_threadsafe` to edit a status
message in place without blocking the bot's event loop — don't replace this with a direct
`await` of a sync/blocking call. `db.svuota_coda()` unconditionally deletes the entire
`messaggi_pendenti` table (not just the rows that were actually analyzed) — this means a
message forwarded while a previous `/analizza_messaggi` call is still running (it can
take minutes) is silently dropped without being analyzed. This is a known, accepted
tradeoff (explicit user decision), not an oversight — don't "fix" it without asking.
`bot.py`'s on-demand response is plain chat text, not a PDF: `_testo_semplice()` strips
the `**`/`->` markdown markers before sending (the "rich" markdown text is still what
gets logged to `analisi_on_demand`).

**`collector.py` strips channel self-signatures** (`_rimuovi_firma_canale`): channels with
Telegram's "sign messages" enabled append a bare line with their own username to every
message, which otherwise pollutes the prompt with orphan lines with no timestamp. Message
timestamps are converted with `msg.date.astimezone(FUSO_ITALIA)` (imported from
`notifiche.py`), never bare `.astimezone()` — same rationale as the delivery-time
timezone above, so the "ore HH:MM" labels in the prompt match Europe/Rome regardless of
the server's system timezone.

**Access control**: `bot.py`'s `solo_owner` decorator silently drops any update not from
`config.TELEGRAM_OWNER_ID` — no reply at all, not even an error. This is intentional
(anti-enumeration), not an oversight; don't add a rejection message.

## Sensitive files kept out of git

`.gitignore` excludes `.env`, `*.session`, `*.db`, `*.log`, generated `report_*.pdf` /
`riepilogo_*.pdf` (and legacy `report_*.txt`), `prompt_esempio.txt` (a debug artifact),
and three project-notes files that predate the code (`master.txt`,
`vps-netcup-scheda-tecnica.txt`, `domande.txt`) — these contain real VPS/network details
and should never be committed.
