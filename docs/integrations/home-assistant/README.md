# Home Assistant integration

Home Assistant (HA) talks to printarr only through its REST API. Nothing else touches the printer.

Files in this folder:

| File | What it is |
|---|---|
| `rest_commands.yaml` | `rest_command` entries that call printarr. Paste into `configuration.yaml` or a package. |
| `sensors.yaml` | Health and queue-size sensors, with a binary sensor for printarr being up. |
| `scripts.yaml` | Buttons for the shopping list and for leaving a message for the other person. |
| `automations.yaml` | Morning (phone unplugged), evening rundown (arriving home, after 16:00), and a notification-to-print. |

Replace `PRINTARR_URL` with the printarr address, for example `http://192.168.1.10:8000`, and
`printarr` in the examples below is the name used in `rest_commands.yaml`.

## Before you start

1. Open printarr's web UI, then Settings, then Home Assistant. Enter the HA URL and a long-lived access
   token. Yannic enters the token himself, and it is never written into these files.
2. Check `GET /api/v1/settings/ha/test` returns `{"reachable": true}`.
3. Fill in the placeholder entity IDs (marked `# CONFIRM`) before enabling an automation.

## Recipients

| Person | printarr id | Notes |
|---|---|---|
| Yannic | `yannic` | Phone: `binary_sensor.yannic_pixel_is_charging` |
| Allyson | `wife` | Phone: `binary_sensor.allyson_pixel_is_charging` |

Always use `wife` for Allyson in the API. The display name is "Allyson" on the ticket.

## Endpoints HA calls

| Call | Used for | Idempotent? |
|---|---|---|
| `POST /api/v1/tickets` | Create a ticket. Body fields are listed below. | Yes, when `idempotency_key` is sent. A repeat returns the first ticket. |
| `POST /api/v1/tickets/{id}/release` | Release one held ticket. | Yes. A ticket that is not held returns an error, so do not repeat it. |
| `POST /api/v1/holds/{hold_key}/release` | Release every held ticket with a key, for example `morning-yannic-2026-10-26`. | Yes. A second call finds nothing held and returns `[]`. |
| `POST /api/v1/tickets/{id}/cancel` | Cancel a pending ticket. | Only from `pending`. |
| `GET /api/v1/health` | Health sensor. Returns 200 when up, 503 when the printer or database is down. | Read only. |
| `GET /api/v1/tickets?status=pending&limit=200` | Queue size. Capped at 200. | Read only. |
| `GET /api/v1/log?recipient=wife&since_hours=24` | History. | Read only. |

### Ticket body fields HA uses

| Field | Example | Meaning |
|---|---|---|
| `recipient` | `yannic` | Required. `yannic` or `wife`. |
| `message` | `Dinner is at 7.` | Required, up to 2000 characters. |
| `kind` | `morning`, `evening`, `note`, `shopping`, `todo`, `alert`, `fun`, `reminder` | What the ticket is for. |
| `tone` | `neutral`, `loving`, `reminder`, `playful`, `gentle`, `firm`, `urgent` | How it sounds. |
| `template` | `auto` | Let the decision model choose. |
| `sender` | `home-assistant` | Shown in the log. |
| `from_user`, `to_user` | `yannic`, `wife` | Both set makes an inbox item. |
| `hold` | `true` | Keep until released. Cannot be combined with `send_at`. |
| `hold_key` | `morning-yannic-2026-10-26` | Needs `hold: true`. Use one key per day and person. |
| `send_at` | `2026-10-27T07:00:00` | Print at a time. Cannot be combined with `hold`. |
| `idempotency_key` | `morning:yannic:2026-10-26` | Use one key per logical ticket so retries are safe. |
| `blocks` | see `automations.yaml` | Live HA values, read at print time. |

## Timing

Templates and the decision model run when the ticket is created. Live HA values are read when the
ticket prints. So a held morning ticket created at 05:30 still shows the sleep score as it is at
7:10, when the phone is unplugged.

## Failure behaviour

- printarr unreachable: the `rest_command` raises an error in HA. The automations below use
  `continue_on_error`, so one failure does not stop the rest of a script.
- printer unreachable at print time: printarr retries with backoff and alerts through Telegram.
- HA unreachable at print time: the ticket prints with `NO DATA` placeholders rather than being dropped.
