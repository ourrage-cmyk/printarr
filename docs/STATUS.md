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
- Test suite: 255 tests, all passing on main.

## Still to fix or build

- Setup wizard and database-held credentials (setup-wizard thread).
- Home Assistant token must be entered in settings by Yannic.
- Telegram bot token and chat id.
- Voice intake and the parser (PR #44 design, waiting for Yannic's answers).
- Decision model choosing block type and mood (currently rules and `neutral`).
- Graph series from Home Assistant history.
- Evening rundown contents (missed messages, dogs, daily summary).
- Shopping list: where it lives, and how it prints.
- Simulator as printer: confirm the config over raw TCP 9100.
- Grayscale and CJK or emoji output are unverified or unsupported.
- No API key: fine on a trusted LAN, not for the open internet.
