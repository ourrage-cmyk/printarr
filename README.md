# printarr

A Docker container that queues receipt tickets and prints them on an Epson TM-T88V
(80 mm, ESC/POS). You post a ticket with a recipient, a message and an optional send
time. A background scheduler prints it when it is due, and retries if the printer is
unavailable. Home Assistant and Hermes will call the API later.

The web UI for writing and previewing receipts is planned for a later stage. The API
already exposes the rendered receipt as text and as raw ESC/POS bytes so it can be
built on.

## Install on TrueNAS (one file)

1. Open [`docker-compose.yml`](docker-compose.yml) and change `PRINTARR_PRINTER_HOST` to
   your printer's IP address.
2. In TrueNAS, go to Apps > Install Custom App and paste the whole file.
3. Open `http://<nas-ip>:8000/` to write tickets and change the decision model.

Everything the service saves (tickets, model and alert settings) lives in one folder,
`/data`. The YAML maps it to a folder on your SSD dataset, for example
`/mnt/ssd/apps/printarr`. Create that folder before you install.

The image is built and pushed to `ghcr.io/ourrage-cmyk/printarr` by
`.github/workflows/image.yml` on every push to `main`. The package must be public for
TrueNAS to pull it without a login.

Docs: `http://<nas-ip>:8000/docs`, and the schema is in [`docs/openapi.json`](docs/openapi.json).

## Monitoring and alerts

- **Health for Uptime Kuma:** `GET /api/v1/health`. It returns 200 when the database and
  printer are fine, and 503 when the printer is unreachable. Add an HTTP monitor on that URL.
  Nothing is pushed out. Kuma polls the service.
- **Telegram alerts:** set the bot token and chat ID in the web page, then press Send test
  message. Alerts are sent for: printer unreachable, paper out, cover open, autocutter
  error, rendering failure, ticket failed after retries, and decision model down. Each
  problem alerts once, and a recovery message follows when it clears. The printer's own
  status (paper, cover, cutter) is read every minute with DLE EOT.
- **Printer status bits are unverified:** the TRG lists the error categories but not the
  status byte layout. The bit masks in `app/main.py` (`PRINTER_FAULTS_BITS`) follow the
  standard ESC/POS layout. Check them against the ESC/POS Application Programming Guide
  and against the real printer before trusting the paper, cover and cutter alerts.
- **Model outage:** the request still succeeds with the rule-based template, and the
  ticket records `selection: rule`.
- **Rendering failure:** the API rejects the request with HTTP 500 and queues nothing,
  so the caller knows straight away.

## Holds and Home Assistant

A ticket with `"hold": true` is queued but does not print. The template is still chosen
when the request arrives. Release it with `POST /api/v1/tickets/{id}/release`, or release
every ticket with a hold name using `POST /api/v1/holds/{hold_key}/release`. Home Assistant
can call the hold endpoint when the user gets home. The ticket then prints at once.

Each request takes a few milliseconds to render. A decision model adds its own response
time, bounded by `PRINTARR_LLM_TIMEOUT` (default 5 s). The model is only used when the
ticket arrives, so release and print never wait on it.

## Configuration

All settings are environment variables with the `PRINTARR_` prefix.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PRINTARR_PRINTER_MODE` | `tcp` | `tcp` sends to the printer. `file` writes `.bin` files to `PRINTARR_OUTPUT_DIR` (used for the simulator and tests). |
| `PRINTARR_PRINTER_HOST` | _(empty)_ | Printer IP or hostname in `tcp` mode. |
| `PRINTARR_PRINTER_PORT` | `9100` | Raw TCP port. |
| `PRINTARR_PRINTER_TIMEOUT` | `5` | Seconds to wait for connect and send. |
| `PRINTARR_TIMEZONE` | `Europe/London` | Used for naive `send_at` values and for the date on the receipt. |
| `PRINTARR_DB_PATH` | `/data/printarr.db` | SQLite database file. |
| `PRINTARR_OUTPUT_DIR` | `/data/output` | Where `file` mode writes jobs. |
| `PRINTARR_POLL_INTERVAL` | `5` | Seconds between scheduler checks. |
| `PRINTARR_MAX_ATTEMPTS` | `5` | Print attempts before a ticket is marked `failed`. |
| `PRINTARR_RETRY_BASE_SECONDS` | `30` | First retry delay. It doubles on each attempt. |
| `PRINTARR_PAPER_WIDTH` | `42` | Characters per line in Font A on 80 mm paper. Epson TRG: 512 dots, Font A 12 dots wide, so 42 columns. |
| `PRINTARR_LLM_BASE_URL` | _(empty)_ | OpenAI-compatible base URL, for example `http://ollama:11434/v1`. Empty means rules only. Used on first start only; then change it in the web page. |
| `PRINTARR_LLM_MODEL` | `llama3.2:3b` | Model name sent to that endpoint. |
| `PRINTARR_LLM_ENABLED` | `on` | The decision model is used when a base URL is set. Set to `off` to disable it. |
| `PRINTARR_LLM_TIMEOUT` | `5` | Seconds before the model is skipped. |
| `PRINTARR_SCHEDULER` | `on` | Set to `off` to disable the background printing worker. |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/tickets` | Queue a ticket. Returns 201 with the ticket. |
| `GET` | `/api/v1/tickets` | List tickets. Filter with `status`, `recipient`, `limit`, `offset`. |
| `GET` | `/api/v1/tickets/{id}` | One ticket, including `status`, `attempts` and `last_error`. |
| `POST` | `/api/v1/tickets/{id}/cancel` | Cancel a pending ticket. |
| `POST` | `/api/v1/tickets/{id}/retry` | Print a failed or cancelled ticket again, now. |
| `GET` | `/api/v1/tickets/{id}/preview` | The receipt as plain text. |
| `GET` | `/api/v1/tickets/{id}/escpos` | The exact ESC/POS byte stream. |
| `POST` | `/api/v1/tickets/preview` | Render a ticket body without queueing it. |
| `POST` | `/api/v1/tickets/{id}/release` | Release a held ticket so it prints now. |
| `POST` | `/api/v1/holds/{hold_key}/release` | Release every held ticket with that name. |
| `GET` | `/api/v1/templates` | Templates and the recipient group each belongs to. |
| `GET` / `PUT` | `/api/v1/settings/model` | Decision model URL, model name, on/off and timeout. Saved in the database. |
| `GET` | `/api/v1/health` | Health for Uptime Kuma. 503 when the printer or database is down. |
| `GET` / `PUT` | `/api/v1/settings/alerts` | Telegram bot token and chat ID. The token is never returned in full. |
| `POST` | `/api/v1/alerts/test` | Send a test Telegram message. |
| `GET` | `/` | Web page for writing tickets and changing the settings. |
| `GET` | `/api/v1/printer` | Whether the printer is reachable. |
| `POST` | `/api/v1/printer/test` | Print a test receipt now. Returns 502 if the printer is down. |
| `GET` | `/healthz` | Liveness check. |

Ticket statuses: `pending`, `printing`, `sent`, `failed`, `cancelled`.

The API has no authentication. It is meant for the home LAN only, so do not expose
port 8000 to the internet. `sender` is a free-text ID for the log, for example
`home-assistant` or `hermes`.

Example:

```bash
curl -X POST localhost:8000/api/v1/tickets \
  -H 'Content-Type: application/json' \
  -d '{"recipient":"Anna","sender":"Yannic","title":"Dinner","message":"Pasta at 7","send_at":"2026-10-24T18:00:00"}'
```

Limits: `sender` 40 characters, `title` 80, `message` 2000. Text is word-wrapped to
42 columns. Characters outside the printer's code page (CP437) print as `?`.

## Recipients and templates

`recipient` is a fixed list: `yannic` or `wife`. Each recipient has a group of templates,
listed by `GET /api/v1/templates`.

Template choice happens when the ticket is queued:

1. If `template` is a number, it must belong to the recipient's group. Otherwise the request
   fails with 422.
   `template` defaults to `auto`.
2. If the decision model is configured and answers with a valid template, it is used.
   It may only add decorations the template allows.
3. Otherwise a fixed rule picks the template. The rule is deterministic and works without
   the model. If the model is slow, unreachable, or returns something invalid, the rule
   is used and the ticket records `selection: rule`.

Every ticket stores `template_id`, `decorations` and `selection`, so you can see which
path chose it.

## Printer facts and verification

Layout constants come from the Epson TM-T88V Technical Reference Guide
(`tmt88v_trg_reve.pdf`): 80 mm paper, 72 mm printable width, 512 dots, Font A 42
columns, Font B 56 columns. The TRG does not contain the byte-level command tables.
Those are in the separate ESC/POS Application Programming Guide. So the command bytes
in `app/escpos.py` are still unconfirmed against Epson. Confirm them against the
Programming Guide, or on the real printer, before relying on them.

## Simulator bridge

Run with `PRINTARR_PRINTER_MODE=file`. Each job lands in `PRINTARR_OUTPUT_DIR` as a
`.bin` file, and `GET /api/v1/tickets/{id}/escpos` returns the same bytes. The printer
simulator can use either source.

## Development

```bash
pip install -r requirements-dev.txt
pytest
python -m app.openapi_export   # refreshes docs/openapi.json
```

Run one uvicorn worker only. The scheduler lives inside the process, so a second worker
would print each ticket twice.
