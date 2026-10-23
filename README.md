# printarr

A Docker container that queues receipt tickets and prints them on an Epson TM-T88V
(80 mm, ESC/POS). You post a ticket with a recipient, a message and an optional send
time. A background scheduler prints it when it is due, and retries if the printer is
unavailable. Home Assistant and Hermes will call the API later.

The web UI for writing and previewing receipts is planned for a later stage. The API
already exposes the rendered receipt as text and as raw ESC/POS bytes so it can be
built on.

## Run it

```bash
PRINTER_HOST=192.168.1.50 docker compose up -d --build
```

The API is on port 8000. Interactive docs are at `/docs`, and the schema is also in
[`docs/openapi.json`](docs/openapi.json).

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
| `PRINTARR_LLM_BASE_URL` | _(empty)_ | OpenAI-compatible base URL, for example `http://ollama:11434/v1`. Empty means rules only. |
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

1. If `template` is given, it must belong to the recipient's group. Otherwise the request
   fails with 422.
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
