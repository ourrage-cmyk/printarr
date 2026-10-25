# Printarr status, 2026-10-25

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
- One release is one piece of paper per person: the briefing leads, the rest follow in queue order with no gap, one cut at the end, up to 12 tickets per strip. The blank before the cut is fed with the cut command (CUT_FEED, 4 lines), never drawn in a ticket.
- Every block is its own tile on the three-column grid; only a briefing nests (PR #100). One dot size for every title, up to three lines (PR #105). Strips are cut by height, not by block count (PR #101). Tall pictures are sent in bands of at most 1000 rows (PR #106).
- Briefing preset on the compose API (PR #104); a metric label is at most 20 characters; characters the printer cannot draw print as `?` and the response lists them under `warnings`.
- The running version is shown in Settings and in `/healthz` as `version` and `git_sha`. CI bakes the commit sha into the image; a local build shows `dev`.
- Telegram ping for threads: `POST /api/v1/notify`, one message a minute per caller (PR #80).
- Ticket PNGs kept for printed and failed tickets: `GET /api/v1/ticket-images` and `GET /api/v1/tickets/{id}/image` (PR #78).
- Docs refreshed for the NAS install on port 30100 (README, TrueNAS guide, compose with restart and pull_policy always).
- Hermes skill at `docs/agents/hermes-skill/SKILL.md`, with copies in `skills/printarr/` and `docs/integrations/hermes/`. `tests/test_docs.py` keeps the copies equal.
- READY8 on main: kind marks at the top-right (envelope, bolt, clock, bulb, cart) and tone outlines. The docs describe them.
- Schedule-creation control removed from the web UI. The container holds scheduled tickets but never creates schedules.
- Briefings: the greeting is never dropped; a briefing without one is headed by the addressee (`SAM MORNING`), and the preset appends the name (PR #116). The briefing reads its Home Assistant values at print time, not at queue time (PR #111).
- Print time and a short code under the cut, and `GET /api/v1/prints/{code}` to find a piece (PR #114).
- Graph titles keep a unit with its number (`24 H` never splits across lines), and the README sample uses a title that fits one line.
- Docs and the Hermes skill brought up to date, with personal names and private addresses replaced by placeholders (PR #118 and follow-up).
- Test suite: 523 tests, all passing on main.

## Still to fix or build

- Home Assistant token must be entered in settings by the owner.
- Telegram bot token and chat id.
- Voice button and intake: deferred by the owner. No hardware is being bought.
- Decision model choosing block type and mood (currently rules and `neutral`).
- Evening rundown contents (missed messages, dogs, daily summary).
- Simulator as printer: confirm the config over raw TCP 9100.
- Grayscale and CJK or emoji output are unverified or unsupported.
- Logging for diagnosis. Hermes must be able to find out why something went wrong from printarr's logs alone, without shell access. Log every ticket and release through its stages (queued, rendered, sent, printed, failed), with ids, timings, the printer and model outcomes, and the reason for each failure. Log setup and settings changes, without secrets. Keep the logs readable from the API. Not started; the first step is a written list of events.

## Decided on 2026-10-24

- The API is LAN-only, with no API key. The web UI may be exposed later behind the owner's own auth portal.
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
- Models are not kept warm. the owner ruled out keeping them in memory, because it exhausts his server's RAM. No warm-up runs, and no keep_alive is sent, so Ollama unloads as it likes.
- A model failure is logged at once but alerts only after 3 failures within 15 minutes. A success clears the count. The alert gives the real cause: the HTTP status, the timeout, or the network error.
- A failed model never blocks a print. The rules choose, and the text is printed as sent.
- Granite calls send max_tokens 1024. A small budget left the answer empty.

Both model calls on one ticket share a 50 s budget, leaving 10 s for rendering inside the 60 s ticket limit. The decision gets what the text clean-up left. When the budget runs out, the rules choose and the text prints as sent.
