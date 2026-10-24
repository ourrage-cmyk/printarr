# Printarr status

Current build: 0.2.200 or later (the running version and commit are in `/healthz` and in Settings).

## Done

- **Printing:** ESC/POS over TCP 9100, 512-dot raster, partial cut. One release prints a person's pile as strips, cut after each strip.
- **Tiles:** every block is its own bordered tile on a three-column grid. Tiles pack together dynamically, so a pile forms one cohesive ticket.
- **Composed tickets:** ten block types (greeting, metric, metric rows, graph, dog counts, message, alert, checklist, tip, fact), up to 16 blocks per ticket. Home Assistant values are read at print time.
- **Briefing preset:** `POST /api/v1/tickets/compose` with `preset: "briefing"`. A time-of-day greeting, three metrics with sparklines, one graph, a body and a fun fact.
- **Pile rules:** the greeting-led ticket (a briefing) goes on top, a strip is cut after 12 tickets or when too tall, and a new greeting starts a new strip. The cut feed is sent with the cut command and is never drawn into the picture.
- **Per-person release triggers:** `POST /api/v1/people/{person}/release` with `morning`, `evening`, `arrival` or `request`.
- **Mood bands and kind marks:** one band across the top of each card (none, sparse dots, zigzag, ticks, stipple, hatch, blocks, barcode, solid bar). Kind marks on five block types: envelope, bolt, clock, bulb and cart.
- **Classifier for plain text:** a text model cleans unformatted text, and a decision model (Ollama, `/v1/systemone`) picks the layout. Fixed word rules take over when a model fails. A failed model never blocks a print.
- **Ticket images:** a PNG of each printed or failed ticket, the newest 250, through `GET /api/v1/ticket-images` and `GET /api/v1/tickets/{id}/image`.
- **Setup:** the setup wizard at `/` holds every setting, saved in the data folder. The compose file has no `environment` section.
- **Deploy:** TrueNAS at `http://<nas-ip>:30100` (port 8000 is taken on that NAS). Data in `/mnt/SSDCAGE/printarr`, uid 568.
- **Telegram ping for threads:** `POST /api/v1/notify`, one message a minute per caller.
- **Hermes skill:** `docs/agents/hermes-skill/SKILL.md`, with copies in `skills/printarr/` and `docs/integrations/hermes/`. `tests/test_docs.py` keeps the copies equal.
- **Health, metrics and backups:** `/api/v1/health`, `/api/v1/metrics`, export and import.
- **Schedule creation:** not in printarr. The container holds scheduled tickets but never creates schedules. Hermes and Home Assistant set the timing.

## Still to fix or build

- Printer: confirm the real TM-T88V over TCP 9100 (the laptop simulator stands in until it arrives). Check the alert barcode and the top margin on paper.
- Yannic enters the Home Assistant token and the Telegram bot token in the setup wizard.
- Decision model choosing a block's mood (`auto` prints as `neutral` for now).
- Evening rundown contents (missed messages, dogs, daily summary).
- Logging for diagnosis. Hermes should be able to find out why something went wrong from printarr's logs alone. Not started; the first step is a written list of events.
- Grayscale is unverified. CJK and emoji are unsupported.
- Voice button and intake: deferred. No hardware is being bought.

## Decided

- **2026-10-24:** the API is LAN-only, with no API key. The web UI may be exposed later behind Yannic's own auth portal.
- **2026-10-24:** the shopping list lives in Home Assistant and is managed by Hermes. It prints only on request or when the agent schedules it.
- **2026-10-24:** printarr never creates schedules. Hermes sets all timed and recurring jobs through the API. The container only holds a ticket until it is due.
- **2026-10-24:** URLs, tokens and printer addresses are set in the setup wizard, never in environment variables.
- **2026-10-24:** briefings use one fixed block set per person. printarr fetches Home Assistant values at release. If Home Assistant is down at release, the ticket still prints, with `--` for the missing values.
- **2026-10-24:** a fun fact is never printed under a label such as "Did you know" or "Fun fact". The words are not forbidden inside a sentence, but the fact stands alone.
- **2026-10-24:** the paper is an 80 mm roll, with 512 dots printable at 180 dpi (about 72 mm).

## Model timeouts and alerts (2026-10-24)

The "decision model / LLM not available" Telegram alerts came from a 5 s model timeout. Ollama unloads a model after about 5 idle minutes, and the first call after an unload took 15.7 s for d1 (8.8 s for granite), so each cold call timed out and alerted.

What changed:
- The timeout defaults to 45 s. The API accepts up to 60 s. Migrations 7 and 8 move a stored 5 s or 30 s seed to 45 s. A value set by hand is kept.
- Models are not kept warm. Yannic ruled out keeping them in memory, because it exhausts the server's RAM. No warm-up runs, and no `keep_alive` is sent.
- A model failure is logged at once but alerts only after 3 failures within 15 minutes. A success clears the count. The alert gives the real cause: the HTTP status, the timeout, or the network error.
- A failed model never blocks a print. The rules choose, and the text prints as sent.
- Granite calls send `max_tokens` 1024. A small budget left the answer empty.

Both model calls on one ticket share a 50 s budget, leaving 10 s for rendering inside the 60 s ticket limit.
