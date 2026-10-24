# Printarr API: how an agent uses it

Printarr prints receipt tickets on an Epson TM-T88V. Everything talks to its REST API under `/api/v1`. There is no API key yet, so run it on a trusted network only. The full schema is at `/openapi.json`, and `/docs` shows it interactively.

## Start here, in this order

1. `GET /api/v1/health` returns 200 when the database and printer are reachable.
2. `GET /api/v1/blocks` lists the composed block types, their moods and their span and unit ranges.
3. `GET /api/v1/blocks/{type}/schema` gives the slots of one block type.
4. `GET /api/v1/templates` and `GET /api/v1/slot-templates` list the templates. Slot templates are 101 (briefing) and 102 (note).
5. `GET /api/v1/tickets` and `GET /api/v1/log` show what was queued and printed.

## Errors teach you the fix

Every 4xx has the same shape:

```json
{"detail": "...", "hint": "...", "example": {...}}
```

- `detail` says what is wrong. For block and slot problems it is a list, one entry per wrong field, with `slot` such as `blocks[1].slots.label`.
- `hint` says what to do next.
- `example` is a request body that works, when one helps.

Schema errors (a missing or wrongly typed field) return FastAPI's `detail` list, with `loc` giving the field path, and a `hint` that names the lists to check.

## Sending a ticket

### A plain message, printed now

```json
POST /api/v1/tickets
{"recipient": "yannic", "message": "Bins go out tonight.", "delivery": "now"}
```

### A message held for a person's release

Use `delivery: "on_release"`. The ticket waits in that person's pile until `POST /api/v1/people/{person}/release` is called with a `trigger` of `morning`, `evening`, `arrival` or `request`. The pile prints as one strip per person.

### A scheduled message

Use `delivery: "at"` with `send_at` as local ISO 8601, for example `2026-10-30T10:00:00`. It prints at that time.

### A held message with a hold key

Use `hold: true` with `hold_key`. Release it with `POST /api/v1/holds/{hold_key}/release`. A repeat with the same `idempotency_key` returns the existing ticket and prints nothing new.

### A composed ticket

`POST /api/v1/tickets/compose` takes `recipient` and `blocks`, an ordered list of `{type, mood, span, slots}`. Up to 16 blocks. A greeting always starts a new strip, and a strip holds at most five blocks. `span` is 1 to 3 columns, defaulting to the type's own span. `mood` is one of the listed moods, or `auto`.

```json
{
  "recipient": "yannic",
  "blocks": [
    {"type": "greeting", "mood": "happy", "slots": {"greeting": "GOOD MORNING", "summary": "Two dogs walked."}},
    {"type": "metric", "mood": "factual", "slots": {"label": "Body battery", "entity_id": "sensor.body_battery", "unit": "%"}},
    {"type": "checklist", "mood": "reminder", "slots": {"title": "Shopping", "items": [{"text": "Milk"}, {"text": "Bread", "checked": true}]}}
  ]
}
```

`entity_id` values are read from Home Assistant when the ticket prints. A value that is missing prints `--`. Text that is too long for its card is shortened with `...`, and the response lists each cut in `notes`.

### A slot ticket

`POST /api/v1/tickets/slots` with `template` 101 or 102 and `slots` checked against `GET /api/v1/templates/{id}/schema`.

## Reading back

- `GET /api/v1/tickets/{id}`: one ticket.
- `GET /api/v1/log` and `GET /api/v1/log/summary`: what happened, with timings, moods and strip ids.
- `GET /api/v1/log/export?format=csv`: the same as a file.
- `GET /api/v1/tickets/{id}/preview`: the text of the printed ticket.

## Settings

- Home Assistant: `GET` and `PUT /api/v1/settings/ha`, then `POST /api/v1/settings/ha/test`. The token is stored in the database, never in an environment variable.
- Decision model: `GET` and `PUT /api/v1/settings/model`.
- Alerts (Telegram): `GET` and `PUT /api/v1/settings/alerts`, and `POST /api/v1/alerts/test`.

## Printer

- `GET /api/v1/printer` reports the transport and its state.
- `POST /api/v1/printer/test` prints a test strip.
- `GET /api/v1/printer/self-check` runs a self-check.

For the simulator on a laptop, point the printer at the laptop's address on TCP port 9100.

## Not built yet

- The setup wizard and credentials stored in the database only: in progress in its own thread.
- Voice intake (`POST /api/v1/intake`): proposed in draft PR #44 (`docs/design/voice-button.md`), not built.
- Graphs from Home Assistant history: graphs take a `series` list for now.
- The decision model choosing block type and mood: `auto` resolves to `neutral` until it is built.
- Shopping list and a Hermes integration: undecided, see the outstanding questions.
