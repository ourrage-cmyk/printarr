# printarr status

As of 2026-10-24. This page lists what is built, what has been checked, and what is still open. The
history is in the merged pull requests (#1 to #43), and the code is the source of truth.

## What works today

**Printing**

- Plain-text tickets, with a rule-based template choice and an optional decision model (`d1` scoring).
- Composed strips: an ordered list of typed blocks, each with a mood, drawn as raster strips (#33, #36, #43).
- Three deliveries: `now`, `at` and `on_release`. Each person's pile prints on one strip per release (#30, #31, #35, #38).
- Slot templates: 101 Briefing and 102 Note, with typed slots and 422 messages for each problem (#21, #26, #27).
- Live Home Assistant data at print time: value blocks, sparklines, and entity metrics (#10, #18, #20).
- Holds, release by ticket or by hold key, idempotency keys, schedule rules (#15, #26, #37).
- Cancel and retry, with `last_error` and attempts on every ticket (#37).
- Raw TCP transport, chunked sends, and a fake printer for tests (#22).

**Safety and reliability**

- Crash safety: a ticket left in `printing` at restart is marked `failed`, not reprinted automatically.
- The queue holds while the printer reports a blocking fault (cover, cutter, unrecoverable error). It resumes by itself (#19).
- Versioned database migrations, pre-upgrade and nightly backups, and export and import (#17).
- Health for Uptime Kuma, a self-check that prints nothing, and in-memory metrics (#25).
- Telegram alerts for printer, paper, cutter, render failure, failed tickets and model outage (#39 kept the token out of error messages).

**Interfaces**

- Web page with Compose, Queue, History, Inbox, Insights and Settings tabs (#29). Compose writes plain-text tickets only.
- REST API under `/api/v1`. Schema in `docs/openapi.json`. Agent skill in `skills/printarr/SKILL.md`, also
  copied to `docs/integrations/hermes/SKILL.md`, and the Hermes tool definition in `docs/integrations/hermes/openapi.yaml`.
- Block catalogue and slot schemas served by `GET /api/v1/blocks` and `GET /api/v1/templates/{id}/schema`.

**Delivery and operations**

- Docker image built for amd64 and arm64, smoke-tested in CI, and pushed to GHCR on `main` (#23).
- TrueNAS one-file compose and an install, upgrade and rollback guide (#28).
- Laptop test setup with the simulator as the printer (#34).
- 255 tests pass, including the docs checks in `tests/test_docs.py`. Golden-byte tests pin the encoder.

**Design**

- Receipt design system with tokens, an ornament family, and build scripts (#12, #13).
- Morning design ported to Python and checked against Node (#9).
- Round 5 templates spec, ornament sets and taste guide (#41). The grid strip renderer is in (#42).

## How it was checked

- `pytest`: unit and integration tests, golden bytes, Home Assistant flows, printer transport, fake printer.
- The API was exercised end to end on a scratch database for this document: composing shopping lists and messages,
  briefings with idempotency, release of a pile, hold and release, and the 422 and 404 responses.
- Sample strips in the README were drawn by the app's own renderer. The simulator was not used for them.

## Open: needs Yannic

- **Home Assistant token.** Enter the URL and long-lived token in Settings, then press Test. Printarr keeps the token.
- **Telegram.** Enter the bot token and chat ID, then press Send test message.
- **GHCR.** Make the `printarr` package public, or TrueNAS cannot pull the image without a login.
- **Hermes.** Give Hermes `docs/integrations/hermes/SKILL.md` and `docs/integrations/hermes/openapi.yaml`.
- **Simulator.** `docker-compose.dev.yml` points at a placeholder image `ghcr.io/ourrage-cmyk/printer-simulator`.
  The simulator source is not in this repository yet. Pushing it needs Yannic's go-ahead.

## Open: printer checks on Monday 2026-10-26

- Confirm the status bits on the real unit: cover (status 2), autocutter error (status 3), paper end (status 4).
- Grayscale: the number of tones on the real unit is unverified. Multi-tone images are drawn in 1-bit for now.
- USB ID, and a status round trip. USB and serial are placeholders (`UnbuiltTransport` in `app/printer.py`).
- ESC/POS commands `ESC @`, `ESC E`, `ESC a`, `ESC d` and `ESC t` are not yet checked against the reference pages.
- Confirm the TCP raster path (`GS ( L` function 112) on the real unit. Use `PRINTARR_RASTER_MODE=gs_v0` only if it refuses.
- Cut behaviour: one cut per strip (the default), or once per day. Yannic to decide.

## Open: product and code

- **First-run setup wizard.** Yannic asked for a wizard that configures Home Assistant, the model and the
  Telegram settings in the web page, and opens the API only after setup. It is not built. Settings exist,
  but there is no wizard and the API is open before configuration.
- **Shopping list and to-do state.** printarr stores no list. Hermes (or another agent) keeps the list and
  sends a snapshot each time. A persistent list in printarr is not designed yet.
- **Google Nest or Home voice input.** Yannic wants to speak a message at a speaker or a button. No design exists yet.
  The voice path would need a speech-to-text step and a route from the speaker to the API. Open question.
- **Composing blocks in the web page.** Only the API composes block strips. The Compose tab writes plain text.
- **Preview of strips.** `POST /tickets/preview` shows `[graph]` for any raster line, so the text preview cannot show a
  composed strip's layout. A picture preview is not in the API.
- **Error shapes are not one shape.** Some 422s return a list of `{slot, problem}`, some a string, and some FastAPI's
  `loc` and `msg`. The skill documents all three. One shape is the goal.
- **Entity metrics without Home Assistant.** `POST /tickets/compose` accepts an `entity_id` metric when Home Assistant is
  not configured, and prints `--`. The plain-text and slot paths return 422 in the same case. Make them agree.
- **No text cleanup on composed strips.** `text_state` is available on `POST /tickets` and the briefing `formatted` flag
  on slots. Composed messages are printed as sent.
- **Decision model moods.** `mood: auto` prints `neutral` until the decision model is wired to pick moods.
- **Retries while the printer is unreachable.** A long power cut counts each failed attempt. Roughly seven minutes
  without power dead-letters tickets. Attempts should not count while the printer is unreachable.
- **Paper length.** Paper-length accounting is not built.
- **Job states.** The job state machine has no `queued` or `rendering` states.
- **Transports.** USB and serial are placeholders.
- **Scripts.** `scripts/strip_demo.py` drew a six-block morning strip, which the renderer refuses (a strip holds five by
  default). Fixed by splitting it into strips, in the same change as this document.
- **Not supported.** CJK text and emoji do not print. Characters outside CP437 print as `?`.
- **Design work on the laptop.** The design arena, the rating lab and the taste guide live on the laptop, not in this
  repository, except the taste guide copy in `docs/design/taste-guide/`.

## Decisions on record

- A crash can happen after the bytes reach the printer, so an interrupted ticket is marked `failed`, not reprinted.
  Retry on purpose with `POST /tickets/{id}/retry`.
- Home Assistant data is read at print time, so held and scheduled tickets print current values.
- Briefings and messages between the two people are `on_release`. Only a request releases a pile early.
- Printer status is decoded in one place, `app/status.py`.
- There is no authentication. The service is for the home LAN only.
