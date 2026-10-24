# Printarr status, 2026-10-24

## Done

- Printing: ESC/POS over TCP 9100, 512-dot raster, partial cut, strip cutting for a person's pile.
- Ticket API: plain, held, scheduled, slot and composed tickets, with idempotency keys and hold keys.
- Composed tickets draw through the strip renderer (PR #43): ten block types, spans, Home Assistant values at print time, notes for cut text.
- Agent-facing errors (PR #45): every 4xx returns a detail, a hint and an example.
- Person piles: one strip per person per release, claim before print, failed prints keep the pile.
- Log with timings, moods and strip ids; CSV and JSON export.
- Backup export and import; health and metrics for monitoring.
- OpenAPI export regenerated (`docs/openapi.json`).
- Briefings and notes draw as cards in the shared shell (PR #54). Briefing metrics get 24 h Home Assistant sparklines.
- Greeting starts a new strip at each release (PR #53).
- Schedule-creation control removed from the web UI. The container holds scheduled tickets but never creates schedules.
- Test suite: 281 tests, all passing on main.

## Still to fix or build

- Setup wizard and database-held credentials (setup-wizard thread).
- Home Assistant token must be entered in settings by Yannic.
- Telegram bot token and chat id.
- Voice button and intake: deferred by Yannic. No hardware is being bought.
- Decision model choosing block type and mood (currently rules and `neutral`).
- Evening rundown contents (missed messages, dogs, daily summary).
- Simulator as printer: confirm the config over raw TCP 9100.
- Grayscale and CJK or emoji output are unverified or unsupported.

## Decided on 2026-10-24

- The API is LAN-only, with no API key. The web UI may be exposed later behind Yannic's own auth portal.
- The shopping list lives in Home Assistant and is managed by Hermes. It prints only on request or when the agent schedules it.
- printarr never creates schedules. The agent (Hermes) sets all timed and recurring jobs through the API. The container only holds a ticket until it is due.
- The voice button is deferred. No hardware is being bought. Messages can come from Hermes directly or from a Telegram bot.
- Spoken notes will print straight away. Reminders go on the scheduled slip. The sender is inferred from the addressee.
- URLs, tokens and printer addresses are set in the first-run setup wizard, never in environment variables.
- The paper is an 80 mm roll, with 512 dots printable at 180 dpi (about 72 mm). The first roll arrives Monday.

## Model timeouts and alerts (2026-10-24)

Root cause of the "decision model / LLM not available" Telegram alerts: the model timeout was 5 s, and Ollama unloads a model after about 5 idle minutes. The first call after an unload waited 15.7 s for d1 (8.8 s for granite), so it timed out, and each cold call alerted.

What changed:
- The timeout defaults to 45 s, the most a cold d1 or granite load needs with margin. The API accepts up to 60 s. Migrations 7 and 8 move a stored 5 s or 30 s seed to 45 s. A value set by hand is kept.
- Models are not kept warm. Yannic ruled out keeping them in memory, because it exhausts his server's RAM. No warm-up runs, and no keep_alive is sent, so Ollama unloads as it likes.
- A model failure is logged at once but alerts only after 3 failures within 15 minutes. A success clears the count. The alert gives the real cause: the HTTP status, the timeout, or the network error.
- A failed model never blocks a print. The rules choose, and the text is printed as sent.
- Granite calls send max_tokens 1024. A small budget left the answer empty.

Known limit: a cold text clean-up followed by a cold decision call can run past the 60 s ticket limit. The rules fallback still prints.
