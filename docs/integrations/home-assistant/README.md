# Home Assistant integration

Home Assistant (HA) talks to printarr only through its REST API. Nothing else touches the printer.

Files in this folder:

| File | What it is |
|---|---|
| `rest_commands.yaml` | `rest_command` entries that call printarr. Paste into `configuration.yaml` or a package. |
| `sensors.yaml` | Health and queue-size sensors, with a binary sensor for printarr being up. |
| `scripts.yaml` | Buttons for the shopping list, and for leaving a message for the other person. |
| `automations.yaml` | Morning strip (phone unplugged), evening strip (arriving home, from 16:00), and notification-to-print. |

Replace `PRINTARR_URL` with the printarr address, for example `http://192.168.1.10:8000`.

## Before you start

1. Open printarr's web UI, then Settings, then Home Assistant. Enter the HA URL and a long-lived access
   token. Yannic enters the token himself, and it is never written into these files.
2. Check `GET /api/v1/settings/ha/test` returns `{"reachable": true}`.
3. Fill in the placeholder entity IDs (marked `# CONFIRM`) before enabling an automation.

## Strips, not shared paper

Each person gets their own strip. Nothing is shared between Yannic and Allyson on one strip.

- **Phone unplugged** (morning, 04:00 to 11:00): that person's morning briefing is created and released.
  Their strip holds the briefing plus any messages waiting for them, cut after each strip.
- **Arriving home** (from 16:00): that person's evening rundown is created and released, with the same
  waiting messages.
- **Standalone items** (shopping lists, reminders, a note at a set time, alerts) print at once, or at
  `send_at`, and are never merged into a strip.

Messages between the two of you use `delivery: on_release`. They wait in the recipient's pile until
their next strip.

## Recipients

| Person | printarr id | Notes |
|---|---|---|
| Yannic | `yannic` | Phone: `binary_sensor.yannic_pixel_is_charging` |
| Allyson | `wife` | Phone: `binary_sensor.allyson_pixel_is_charging` |

Always use `wife` for Allyson in the API. The display name is "Allyson" on the ticket.

## Endpoints HA calls

| Call | Used for | Repeat-safe? |
|---|---|---|
| `POST /api/v1/tickets/slots` | Create a briefing (template 101) with `delivery: on_release` and a per-day `idempotency_key`. | Yes. A repeat returns the first ticket. |
| `POST /api/v1/tickets` | Create a plain ticket: shopping list, message, alert. | Yes, with `idempotency_key`. |
| `POST /api/v1/people/{yannic\|wife}/release` | Print that person's strip. Body: `{"trigger": "morning"\|"evening"\|"arrival"\|"request"}`. | Yes. Only items still in the pile print. |
| `POST /api/v1/holds/{hold_key}/release` | Release a held ticket group by key. | Yes. |
| `POST /api/v1/tickets/{id}/cancel` | Cancel a pending ticket. | Only from `pending`. |
| `GET /api/v1/health` | Health sensor. 200 when up, 503 when the printer or database is down. | Read only. |
| `GET /api/v1/tickets?status=pending&limit=200` | Queue size. Capped at 200. | Read only. |

### Ticket fields HA uses

| Field | Example | Meaning |
|---|---|---|
| `recipient` | `yannic` | Required. `yannic` or `wife`. |
| `message` | `Dinner is at 7.` | Required for plain tickets, up to 2000 characters. |
| `kind` | `morning`, `evening`, `note`, `shopping`, `todo`, `alert`, `fun`, `reminder` | What the ticket is for. |
| `tone` | `neutral`, `loving`, `reminder`, `playful`, `gentle`, `firm`, `urgent` | How it sounds. |
| `delivery` | `now`, `at`, `on_release` | `now` prints at once. `at` prints at `send_at`. `on_release` waits for the recipient's next strip. |
| `send_at` | `2026-10-27T07:00:00` | With `delivery: at`. Local time, no offset. |
| `from_user`, `to_user` | `yannic`, `wife` | Both set makes an inbox item. |
| `idempotency_key` | `morning:yannic:2026-10-26` | One key per logical ticket, so retries are safe. |
| `blocks` | see `automations.yaml` | Live HA values, read at print time. |

Held tickets (`hold`, `hold_key`) still work for groups that must release together, but briefings and
messages use `delivery: on_release` so that they join the pile.

## Timing

Templates and the decision model run when the ticket is created. Live HA values are read when the
ticket prints. Because a briefing is created on its trigger and released straight after, the sleep score
or body battery is read at the moment the phone is unplugged.

## Failure behaviour

- printarr unreachable: the `rest_command` raises an error in HA. The automations use `continue_on_error`,
  so one failure does not stop the rest of a script.
- printer unreachable at print time: the strip stays in the pile and printarr retries, then alerts through Telegram.
- HA unreachable at print time: the ticket prints with `NO DATA` placeholders rather than being dropped.
