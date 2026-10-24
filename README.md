# printarr

A Docker container that queues receipt tickets and prints them on an Epson TM-T88V
(80 mm, ESC/POS). You post a ticket with a recipient, a message and an optional send
time. A background scheduler prints it when it is due, and retries if the printer is
unavailable. Home Assistant and Hermes will call the API later.

The web UI for writing and previewing receipts is planned for a later stage. The API
already exposes the rendered receipt as text and as raw ESC/POS bytes so it can be
built on.

## Install on TrueNAS (one file)

1. In TrueNAS, go to Apps > Install Custom App and paste [`docker-compose.yml`](docker-compose.yml).
2. Open the app's Logs and copy the **setup code** printed at start.
3. Open `http://<nas-ip>:8000/`, enter the setup code and finish the setup wizard: printer,
   Home Assistant, model server, Telegram, names and timezone. Each one has a Test button.
   Secrets are stored in the data folder, never in the YAML. See [docs/deploy/truenas.md](docs/deploy/truenas.md).

Everything the service saves (tickets, model and alert settings) lives in one folder,
`/data`. The YAML maps it to a folder on your SSD dataset, for example
`/mnt/pool/printarr`. Create that folder before you install.

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
- **Printer status bits:** taken from the ESC/POS Command Reference (`dle_eot`). Cover is
  bit 2 of status 2, autocutter error is bit 3 of status 3, and paper end is bits 5-6 of
  status 4. Check them on the real printer before trusting the alerts.
- **Model outage:** the request still succeeds with the rule-based template, and the
  ticket records `selection: rule`.
- **Rendering failure:** the API rejects the request with HTTP 500 and queues nothing,
  so the caller knows straight away.

## Live data from Home Assistant

Tickets can include `blocks`:
- `value`: an entity's current state, with a label and unit.
- `sparkline`: a 512-dot graph of an entity's history (`hours`, default 24), printed as a raster image.

Set the Home Assistant URL and a long-lived access token in the web page. The data is
fetched when the ticket prints, not when it is queued. A held or scheduled ticket
therefore prints current values. If Home Assistant can't be reached at print time, the
ticket still prints with "data unavailable" in place of the live data, and a Telegram
alert fires. Requests that include blocks are rejected with 422 if Home Assistant is not
configured, and the preview returns 502 if Home Assistant is unreachable.

## Holds and Home Assistant

A ticket with `"hold": true` is queued but does not print. The template is still chosen
when the request arrives. Release it with `POST /api/v1/tickets/{id}/release`, or release
every ticket with a hold name using `POST /api/v1/holds/{hold_key}/release`. Home Assistant
can call the hold endpoint when the user gets home. The ticket then prints at once.

Each request takes a few milliseconds to render. A decision model adds its own response
time, bounded by `PRINTARR_LLM_TIMEOUT` (default 5 s). The model is only used when the
ticket arrives, so release and print never wait on it.

## Configuration

All settings are set in the setup wizard at `/setup`, and saved in the data folder. The compose file
holds only the image, memory, CPUs, ports and storage. Secrets (Home Assistant token, Telegram
token) are typed into the wizard and stored in the database, never in environment variables.


## Data, upgrades and backups

- The database schema is versioned (SQLite `user_version`). Each start applies only the steps the
  database has not had yet, and never drops data. Before an upgrade of an existing database, a copy
  is written to `backups/pre-upgrade-v<n>-<time>.db` (the last five are kept).
- A database from a newer version is refused, so an older image cannot damage it. To go back to an
  older image, restore a backup taken by that version.
- Nightly copies go to `backups/nightly-<date>-<time>.db`.
- Download a copy at any time: `GET /api/v1/backup/export`.
- Replace the database from a copy: `POST /api/v1/backup/import?confirm=replace` with the file as
  the raw body. The current database is first kept as `backups/pre-import-*.db`.
- With the API stopped, restore from a file inside the container:
  `python -m app.backup restore /data/backups/<file>.db`

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

`recipient` is a fixed list: `yannic` or `wife` (shown as Allyson). Each recipient has a group of templates,
listed by `GET /api/v1/templates`.

Template choice happens when the ticket is queued:

1. If `template` is a number, it must belong to the recipient's group. Otherwise the request
   fails with 422.
   `template` defaults to `auto`.
2. If the decision model is configured and scores a template at least 0.5, it is used.
   The template's default decorations apply.
3. Otherwise a fixed rule picks the template. The rule is deterministic and works without
   the model. If the model is slow, unreachable, or returns something invalid, the rule
   is used and the ticket records `selection: rule`.

Every ticket stores `template_id`, `decorations` and `selection`, so you can see which
path chose it.

## Printer facts and verification

Layout constants come from the Epson TM-T88V Technical Reference Guide: 80 mm paper,
512 dots, Font A 42 columns, Font B 56 columns.

Command bytes are checked against the ESC/POS Command Reference (revision 3.40, TM printers):

- Verified: `GS !` (double size), `GS V 1` (partial cut), `GS ( L` function 112 (raster)
  and function 50 (print), and `DLE EOT` status 1 to 4.
- Not yet read: `ESC @`, `ESC E`, `ESC a`, `ESC d`, `ESC t`. These are in the command index
  and are standard, but their pages still need checking.
- Obsolete and not used by default: `GS v 0` (see `PRINTARR_RASTER_MODE`), and `ESC i` and
  `ESC m` for partial cuts.

Still to check on the real unit: the USB ID, the number of tone levels for multi-tone
images, and a status round trip.

## Simulator bridge

Point the service at the simulator over TCP, the same way as the real printer:

```bash
PRINTARR_PRINTER_MODE=tcp PRINTARR_PRINTER_HOST=<simulator-host> PRINTARR_PRINTER_PORT=9100
```

To send the sample jobs (text, raster, full receipt) to any target and check the output:

```bash
python -m app.send_sample <host> 9100
```

Golden-byte tests in `tests/test_golden.py` pin the exact bytes for these jobs. They are
regression tests against this encoder, not checks against Epson's Programming Guide.

The earlier `file` mode still works too: it writes each job as a `.bin` file in
`PRINTARR_OUTPUT_DIR`.

### Older note

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
