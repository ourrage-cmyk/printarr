# printarr

printarr is a small service that prints receipt-style strips on an Epson TM-T88V
(80 mm, ESC/POS). Home Assistant, Hermes and the web page send it messages, briefings,
lists and alerts. It lays them out as tiles on one design grid, keeps each person's
waiting items in their own pile, and prints the pile when Home Assistant releases it.

<p align="center">
  <img src="docs/images/strip-morning-briefing.png" alt="Morning briefing strip" width="200">
  <img src="docs/images/strip-shopping-list.png" alt="Shopping list strip" width="200">
  <img src="docs/images/strip-alert.png" alt="Urgent alert strip" width="200">
</p>

<p align="center"><sub>Sample strips drawn by the app's own renderer (<code>scripts/render_readme_samples.py</code>). The sample images may lag the current layout; the ticket PNGs from the running service are the reference.</sub></p>

## What it does

- **Two recipients**, `yannic` and `wife` (Allyson). Each has a pile of waiting items. A release prints the pile as one piece
  of paper, cut after each strip: in the morning when the phone is unplugged, and in the evening or on arrival when someone gets home.
- **Tiles.** Every block is its own bordered tile on a three-column grid. Tiles fall together and pack like puzzle pieces, so
  any pile of messages forms one cohesive ticket.
- **Composed tickets.** A ticket is an ordered list of typed blocks: greeting, metric, metric rows, graph, dog counts, message,
  alert, checklist, tip and fact. Each block has a mood, which shows as a band across the top of its tile.
- **Briefing preset.** One fixed layout for Hermes' briefings: a greeting with the time of day, three metrics with sparklines,
  one larger graph, a body and a fun fact.
- **Three deliveries.** `on_release` waits in the pile, `at` prints at a time, and `now` prints straight away.
- **Live data.** Entity values and sparklines are read from Home Assistant when the ticket prints, not when it is queued. A value Home Assistant does not give prints as `--`.
- **Simple text too.** Plain messages go through `POST /api/v1/tickets`, and a classifier picks the layout (see the API guide).
- **Web page** at `/` to write tickets, preview them, watch the inbox and history, and change settings.
- **Built for agents.** Every request is validated against a schema, and a 4xx says what is wrong with it. [`docs/agents/hermes-skill/SKILL.md`](docs/agents/hermes-skill/SKILL.md) teaches an agent (Hermes) the whole API.
- **Telegram pings** for threads that need Yannic to act: `POST /api/v1/notify`, one message a minute per caller.
- **Look at what printed.** Each ticket that reached the printer keeps a PNG, so a bad print can be checked from the API.
- **Safe for the paper.** A ticket interrupted by a crash is marked `failed` rather than printed twice. The queue
  pauses while the printer reports a fault, and held items wait until you release them.

## Architecture

```
  Home Assistant ──REST──┐                 ┌── SQLite (/data/printarr.db)
  Hermes agent ──REST────┼──► printarr API ─┼── scheduler (prints when due, releases piles)
  Web page ──────────────┘   (FastAPI)     ├── ticket PNGs (newest 250)
                                  │        └── backups (nightly, versioned schema)
                                  │
                                  ├── Ollama (decision model, text clean-up)
                                  └── raw TCP 9100 ──► TM-T88V printer
                                                       (or the simulator on the laptop)
```

- `app/main.py` holds the routes. `app/compose.py` validates blocks and the briefing preset. `app/templates.py` holds the
  classifier that picks a layout for plain text. `app/render/` draws the tiles from `app/render/system/blocks.json`
  (moods, mood bands, grid and rules).
- `app/scheduler.py` prints due tickets and releases piles. `app/status.py` decodes the printer's DLE EOT status.
- The SQLite store owns all state. Only one uvicorn worker may run, because the scheduler lives in the process.

## Quick start

### On a laptop with the simulator

```bash
docker compose -f docker-compose.dev.yml up --build
```

The web page is at <http://localhost:8000/>. The simulator is at <http://localhost:8080/>.
Data is kept in `./dev-data`. On a fresh install, finish the setup wizard at `/` first. Until setup is done, the
API answers only the setup routes and health.

### From source

```bash
pip install -r requirements-dev.txt
pytest
PRINTARR_PRINTER_MODE=file PRINTARR_OUTPUT_DIR=./out uvicorn app.main:app --port 8000
```

`file` mode writes each job as a `.bin` file in `PRINTARR_OUTPUT_DIR`, which needs no printer.

### Try the API (after setup)

```bash
curl -X POST localhost:8000/api/v1/tickets \
  -H 'Content-Type: application/json' \
  -d '{"recipient":"wife","sender":"yannic","title":"Dinner","message":"Pasta at 7","delivery":"on_release"}'
```

The ticket waits in Allyson's pile until her next release. Use `"delivery":"now"` to print it straight away.

## Install on TrueNAS

The one-file install, the upgrade steps and the rollback steps are in
[`docs/deploy/truenas.md`](docs/deploy/truenas.md). In short:

1. Create the data folder on your SSD dataset (the install uses `/mnt/SSDCAGE/printarr`) and give it to uid and gid 568, the TrueNAS app user:
   `chown -R 568:568 /mnt/SSDCAGE/printarr`.
2. In `docker-compose.yml`, change only the data folder if it is different. The file holds the image, memory, CPUs, ports and storage, and nothing secret. There is no `environment` section.
3. In TrueNAS, go to Apps, then Custom App (Install via YAML), and paste the file.
4. Open `http://<nas-ip>:30100/`. Port 30100 is published because port 8000 is taken on this NAS. The setup wizard asks for the printer, Home Assistant, the model server, Telegram, names and timezone. Each service has a Test button. Finishing setup saves everything in the data folder.
   The setup code is printed in the container log, and the API stays closed until setup is finished.

The image is built by [`.github/workflows/image.yml`](.github/workflows/image.yml) and pushed to
`ghcr.io/ourrage-cmyk/printarr` on every push to `main`. Its version is `0.2.<workflow run>`, and `/healthz` shows that version with the commit it was built from. The package must be public for TrueNAS to pull it
without a login. The compose file sets `pull_policy: always`, so a restart pulls the newest image.

## Connect Home Assistant and Hermes

- **Home Assistant:** create a long-lived access token, paste it into the setup wizard or the settings page, and press Test.
  The setup steps and the example automations are in [`docs/integrations/`](docs/integrations/SETUP-CHECKLIST.md).
- **Hermes:** give the agent [`docs/agents/hermes-skill/SKILL.md`](docs/agents/hermes-skill/SKILL.md) as its instructions and
  [`docs/integrations/hermes/openapi.yaml`](docs/integrations/hermes/openapi.yaml) as its tool definition.
  [`docs/integrations/hermes/example-morning-briefing.md`](docs/integrations/hermes/example-morning-briefing.md)
  shows one briefing from start to finish.

## API

The full schema is [`docs/openapi.json`](docs/openapi.json). The running service also serves `/docs`.
The main routes:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/blocks`, `/api/v1/blocks/{name}/schema` | Block types, moods and their slot schemas |
| `POST` | `/api/v1/tickets/compose` | Queue a ticket made of blocks, or the briefing preset |
| `POST` | `/api/v1/tickets/slots` | Queue a briefing (101) or note (102) from typed slots |
| `POST` | `/api/v1/tickets` | Queue plain text |
| `POST` | `/api/v1/tickets/preview` | See the text of a plain ticket without queueing it |
| `GET` | `/api/v1/tickets`, `/api/v1/tickets/{id}` | List tickets, or read one with its status and last error |
| `POST` | `/api/v1/tickets/{id}/cancel`, `/retry`, `/release` | Cancel, print again, or release a held ticket |
| `POST` | `/api/v1/people/{person}/release` | Print a person's pile now. `trigger`: `morning`, `evening`, `arrival` or `request` |
| `POST` | `/api/v1/holds/{hold_key}/release` | Release every held ticket with that key |
| `GET` | `/api/v1/insights/entities` | Ranked Home Assistant entities for a briefing |
| `GET` | `/api/v1/log`, `/api/v1/log/summary`, `/api/v1/log/export` | History |
| `GET` / `PUT` | `/api/v1/settings/ha`, `/settings/model`, `/settings/alerts` | Settings (tokens are never returned in full) |
| `POST` | `/api/v1/settings/ha/test`, `/alerts/test`, `/printer/test` | Check Home Assistant, Telegram and the printer |
| `GET` | `/api/v1/printer`, `/printer/self-check` | Printer status (the self-check prints nothing) |
| `GET` | `/api/v1/health`, `/api/v1/metrics`, `/healthz` | Health for Uptime Kuma, counters, liveness, and the build (`version`, `git_sha`) |
| `POST` | `/api/v1/notify` | Send a Telegram message to Yannic (one a minute per caller) |
| `GET` | `/api/v1/ticket-images`, `/api/v1/tickets/{id}/image` | Recent ticket PNGs (newest 250), and the PNG of one ticket as sent to the printer |
| `GET` / `POST` | `/api/v1/backup/export`, `/backup/import` | Download or restore the database |

Ticket statuses: `held`, `pending`, `printing`, `sent`, `failed`, `cancelled`.

**There is no authentication.** The API is for the home LAN only. Do not expose port 30100 to the internet.

## Design language

Every block is a tile: a bordered card on a three-column grid, one card per block, and tiles fall together so a
pile reads as one ticket. The grid, the rules and the mood bands come from `app/render/system/blocks.json`.

- **Titles** use the dot-matrix font. It is used only for titles and headlines, centred. Body text and numbers use the solid font.
- **Mood band:** one band across the top of a tile, 28 dots tall. Neutral and factual have none. Loving and happy show sparse dots,
  excited and playful zigzag, reminder upright ticks, sad and confused stipple, gentle warning and upset diagonal hatch,
  firm complaint blocks, urgent a barcode, and critical a solid black bar with an inverted title. The band carries the mood, so no mood word is printed.
- **Outline:** `urgent`, `upset` and `firm_complaint` draw a heavy square outline, `critical` the heaviest. `loving`, `gentle_warning`, `playful` and `happy` draw rounder corners.
- **Kind marks:** five block types wear a small mark at the top-right corner: a note (`message`) an envelope, an alert (`alert`) a bolt,
  a reminder (`tip`) a clock, a fun fact (`fact`) a bulb, and a shopping list (`checklist`) a cart. The mark follows the block, not the `kind` field.
- **Fun facts stand alone.** A fun fact is never printed under a label such as "Did you know" or "Fun fact". The message just stands
  by itself. The words are not forbidden inside the sentence.
- **Printed tickets never print the tone name** or the mood name.

The rules and the reasons behind them are in [`docs/design/README.md`](docs/design/README.md), the
mood and tone catalogue is in [`docs/design/tones.md`](docs/design/tones.md), the design tokens are in
[`docs/design/system/tokens.json`](docs/design/system/tokens.json), and the taste guide is in
[`docs/design/taste-guide/taste-guide.md`](docs/design/taste-guide/taste-guide.md).

## Configuration

Settings are entered in the setup wizard (the web page at `/`) and saved in the data folder. Secrets such as the
Home Assistant and Telegram tokens are stored there and are never returned by the API. Change them later at
`/setup` with the setup code from the log. The compose files hold only the image, memory, CPUs, ports and storage.

## Monitoring and alerts

- **Health for Uptime Kuma:** `GET /api/v1/health` returns 200 when the database and printer are fine, and 503
  when the printer is unreachable. Kuma polls the service, nothing is pushed.
- **Telegram alerts:** enter the bot token and chat ID in the setup wizard or the settings page, then press Send test message. Alerts cover
  an unreachable printer, paper out, cover open, autocutter error, a rendering failure, a ticket that failed after
  retries, and a decision model that is down. A model failure alerts only after three failures within 15 minutes.
  Each problem alerts once, and a recovery message follows.
- **Printer status:** read with DLE EOT every minute. The bit layout comes from the Epson ESC/POS Command Reference.

## Data, upgrades and backups

- The database schema is versioned (SQLite `user_version`). Each start applies only the steps that are missing, and
  never drops data. Before an upgrade, a copy is written to `backups/pre-upgrade-v<n>-<time>.db`.
- A database from a newer version is refused, so an older image cannot damage it.
- Download a copy at any time with `GET /api/v1/backup/export`. Restore with `POST /api/v1/backup/import?confirm=replace`.
- With the API stopped, restore from a file in the container: `python -m app.backup restore /data/backups/<file>.db`.
- Ticket PNGs are kept in `/data/tickets/images`, the newest 250.

## Printer facts

- 80 mm paper, 512 printable dots at 180 dpi, Font A at 42 columns. Text is CP437. Characters outside it print as `?`.
- Commands verified against the ESC/POS Command Reference: `GS !`, `GS V 1`, `GS ( L` function 112 and 50, and `DLE EOT` status 1 to 4.
- A strip is cut with the partial-cut command. The space before the cut is fed with that command, so the picture has no blank of its own.
- Still to check on the real unit: the USB ID, tone levels for multi-tone images, a status round trip, and the alert barcode and top margin.
- The simulator is a TCP target too. Enter its address as the printer in the setup wizard, and send the sample jobs with
  `python -m app.send_sample <host> 9100`.

## Development

```bash
pip install -r requirements-dev.txt
pytest
python -m app.openapi_export        # refreshes docs/openapi.json
python scripts/render_readme_samples.py   # refreshes docs/images (needs pillow)
```

Golden-byte tests in `tests/test_golden.py` pin the exact bytes for the sample jobs. They guard against changes
to this encoder. They are not checks against Epson's programming guide.

The test suite also checks that `docs/openapi.json` matches the code, that every route named in the README
and the agent skill exists, and that the three copies of the agent skill are identical.

## Documentation

- [`docs/STATUS.md`](docs/STATUS.md): what has been built, and what is still open.
- [`docs/agents/printarr-api.md`](docs/agents/printarr-api.md): how an agent uses the API, the pile rules and the classifier.
- [`docs/agents/hermes-skill/SKILL.md`](docs/agents/hermes-skill/SKILL.md): the agent skill for the API (copies in `skills/printarr/` and `docs/integrations/hermes/`).
- [`docs/deploy/truenas.md`](docs/deploy/truenas.md): install, upgrade, roll back and restore.
- [`docs/integrations/`](docs/integrations/SETUP-CHECKLIST.md): Home Assistant and Hermes setup.
- [`docs/design/`](docs/design/README.md): design system, tones, conformance and templates.
