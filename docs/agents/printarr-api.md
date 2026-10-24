# Printarr API: how an agent uses it

Printarr prints receipt tickets on an Epson TM-T88V. Everything talks to its REST API under `/api/v1`. The API is
LAN-only and has no API key by decision. It is reachable only on Yannic's own network. If the web UI is ever exposed,
Yannic puts his own authentication portal in front of it. The full schema is at `/openapi.json`, and `/docs` shows it interactively.

On the NAS the service is at `http://192.168.1.231:30100`. Examples below use `/api/v1` paths relative to that base.

## Start here, in this order

1. `GET /api/v1/health` returns 200 when the database and printer are reachable. Until setup is finished, it is the only route that answers.
2. `GET /api/v1/blocks` lists the composed block types, their moods and their span and unit ranges.
3. `GET /api/v1/blocks/{type}/schema` gives the slots of one block type.
4. `GET /api/v1/templates` and `GET /api/v1/slot-templates` list the templates. Slot templates are 101 (briefing, older form) and 102 (note).
5. `GET /api/v1/tickets` and `GET /api/v1/log` show what was queued and printed.
6. `GET /healthz` returns the build: `version` (`0.2.<workflow run>`) and `git_sha`. A local build says `dev`.

## Errors teach you the fix

Every 4xx has the same shape:

```json
{"detail": "...", "hint": "...", "example": {...}}
```

- `detail` says what is wrong. For block and slot problems it is a list, one entry per wrong field, with `slot` such as `blocks[1].slots.label`.
- `hint` says what to do next.
- `example` is a request body that works, when one helps.

Schema errors (a missing or wrongly typed field) return FastAPI's `detail` list, with `loc` giving the field path, and a `hint` that names the lists to check.

## Scheduling is the agent's job

printarr is deliberately dumb about time. It stores tickets, assigns templates and blocks to
text, draws them, and holds a ticket until it is due:

- `delivery: "at"` with `send_at` holds one ticket until that time, then prints it.
- `delivery: "on_release"` (or `hold: true`) holds a ticket until someone releases it.
- `POST /api/v1/people/{person}/release` prints a person's waiting tickets, when the caller says so.

printarr never creates a recurring schedule, has no calendar, and the web UI has no schedule
control. Any job that prints on a time or on arrival is set up by the agent (Hermes) outside printarr,
or by Home Assistant. It calls the API when the job runs, or sends the ticket with `send_at` ahead of time.
A ticket with no schedule prints only when it is sent or released.

## Sending a ticket

### A plain message, printed now

```json
POST /api/v1/tickets
{"recipient": "yannic", "message": "Bins go out tonight.", "delivery": "now"}
```

### A message held for a person's release

Use `delivery: "on_release"`. The ticket waits in that person's pile until
`POST /api/v1/people/{person}/release` is called with a `trigger` of `morning`, `evening`, `arrival` or `request`.

**How a release prints.** One release prints one person's pile as strips, and each strip is cut after it:

- The greeting-led ticket (a briefing) goes on top. The rest follow in the order they were queued.
- Tickets sit one tile apart. There is no cut between tickets on the same strip, and no blank is drawn into the picture.
  The space before the cut is fed with the cut command, so it is not part of the rendered strip.
- A strip holds up to 12 tickets (`STRIP_MAX_BLOCKS`), and is also cut when it gets too tall (about 1100 dots of cards).
  A new greeting always starts a new strip.
- A repeat release prints only tickets that are not yet printed. A failed print puts its claimed tickets back on hold.

### A scheduled message

Use `delivery: "at"` with `send_at` as local ISO 8601, for example `2026-10-30T10:00:00`. It prints at that time.

### A held message with a hold key

Use `hold: true` with `hold_key`. Release it with `POST /api/v1/holds/{hold_key}/release`. A repeat with the same
`idempotency_key` returns the existing ticket and prints nothing new.

### A composed ticket

Writing tickets, for agents:
- Say the headline once. Use `title` or the block's heading, and do not repeat it in the body text.
- Greetings ("GOOD MORNING", "HELLO ALLYSON") belong to briefings or to a note to a person. A greeting block takes an optional `from` sign-off. A single-topic ticket (bins, a reminder, a note) has no greeting block.
- Fun facts stand alone. Use a `fact` block with mood `playful` and write the fact as one sentence. Do not put a label such as "Did you know" or "Fun fact" above it. The words are not forbidden inside the sentence, but a fact never goes on a reminder, a note or an alert.
- A shopping list is a `checklist` block with one item per entry. Do not put the items in one paragraph.
- Keep one message in one tile: do not split a single message across two blocks.

`POST /api/v1/tickets/compose` takes `recipient` and either `blocks` or `preset`. `blocks` is an ordered list of `{type, mood, span, slots}`,
up to 16 blocks. Each block is its own bordered tile on a three-column grid. Tiles that fit sit side by side, and the layout packs them together
like puzzle pieces. `span` is 1 to 3 columns, defaulting to the type's own span. `mood` is one of the listed moods, or `auto`.

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

`entity_id` values are read from Home Assistant when the ticket prints. A value that is missing prints `--`. Text that is too long
for its tile is shortened with `...`, and the response lists each cut in `notes`.

### A briefing preset

`POST /api/v1/tickets/compose` with `preset: "briefing"` and `slots` instead of `blocks`. It lays out one fixed briefing:

1. a greeting with the time of day (`time_of_day`: `morning`, `afternoon` or `evening`, printed as GOOD MORNING and so on),
2. three `metrics` with sparklines (exactly three; each with an `entity_id` or a fixed `value`, and `hours` for the sparkline),
3. one larger `graph` (an `entity_id` for its history, or `series`), which is left out when Home Assistant has no history,
4. a `body` in a message card (up to 800 characters), and
5. a `fun_fact` (up to 200 characters), printed as a fact card that stands alone.

Each part is its own tile. Use the preset for every Hermes briefing so they all look the same. The full example is in the Hermes skill.
A preset ticket is kind `morning` unless `kind` is sent. Do not send `blocks` with a preset.

### A slot ticket

`POST /api/v1/tickets/slots` with `template` 101 or 102 and `slots` checked against `GET /api/v1/templates/{id}/schema`.
It also accepts `blocks`, printed after the slots.

## Kinds, tones, moods and marks

- **Kinds** (`kind`): `morning`, `evening`, `note`, `shopping`, `todo`, `alert`, `fun`, `reminder`. Default `note`. A kind is logged and sent with the ticket.
- **Tones** (`tone`): `loving`, `neutral`, `reminder`, `playful`, `gentle`, `firm`, `urgent`. Default `neutral`. Printed tickets never print the tone name.
- **Moods** (per block): `neutral`, `happy`, `excited`, `loving`, `playful`, `reminder`, `factual`, `sad`, `confused`, `upset`,
  `gentle_warning`, `firm_complaint`, `critical`, `urgent`. `auto` is accepted and prints as `neutral` until the decision model picks moods.
- **Mood band:** each card carries one band across its top edge, 28 dots tall. Neutral and factual have none. Loving and happy: sparse dots.
  Excited and playful: zigzag. Reminder: upright ticks. Sad and confused: dense stipple. Gentle warning and upset: diagonal hatch.
  Firm complaint: blocks. Urgent: barcode. Critical: a solid black bar, with an inverted title.
  The band carries the mood, so no mood word is printed.
- **Outline:** `urgent`, `upset` and `firm_complaint` draw a heavy square outline, `critical` the heaviest. The soft moods
  (`loving`, `gentle_warning`, `playful`, `happy`) draw a rounder corner.
- **Kind marks:** the top-right corner carries an envelope on `message`, a bolt on `alert`, a clock on `tip`, a bulb on `fact` and a cart on `checklist`.
  The mark follows the block, not the `kind` field. Choose the block type that fits the content.

## Classifier: how a plain ticket gets its layout

`POST /api/v1/tickets` (plain text) and the slot forms pick a template when the caller does not name one. A fixed recipient
has its own template group, and only that group is used.

1. If `text_state` is `unformatted`, a text model (`granite4.2:3b` by default) cleans spelling and speech errors. The meaning and language stay the same.
2. A decision model (`d1:latest` by default, through Ollama's structured `/v1/systemone` endpoint) scores yes/no questions about the message: alert or urgent, morning or evening briefing, a short personal note, a list, a personal message, and whether it has numbers.
3. The first kind whose questions reach a score of 0.5 decides the kind (alert, morning, evening, list, then note). The recipient's template of that kind is used.
4. If the model is missing, slow or answers badly, fixed word rules choose the kind instead. A failed model never blocks a print, and the text prints as sent.

Both model calls on one ticket share one time budget (45 seconds per call by default). Models are not kept warm.

## Reading back

- `GET /api/v1/tickets/{id}`: one ticket.
- `GET /api/v1/log` and `GET /api/v1/log/summary`: what happened, with timings, moods and strip ids.
- `GET /api/v1/log/export?format=csv`: the same as a file.
- `GET /api/v1/tickets/{id}/preview`: the text of the printed ticket.

### Looking at what a ticket looked like

Printarr keeps a PNG of every ticket as it reached the printer: each printed ticket, and each ticket whose print failed. The picture is decoded
from the exact bytes sent to the printer, so tiles, mood bands, marks and charts are exact. Text lines are drawn with an approximation of Font A,
so check text on the real paper or the simulator. A ticket inside a strip is saved on its own, without the cut or the gap around it.

- `GET /api/v1/ticket-images?limit=50`: recent tickets that have an image, newest first. Each row gives `id`, `kind`, `template_id`, `template`, `recipient`, `status`, `created_at`, `printed_at` and `image_url`. Up to 250 are kept, and older ones are deleted.
- `GET /api/v1/tickets/{id}/image`: the PNG (`image/png`) for one ticket. A ticket still waiting, cancelled before printing, or older than the kept images returns 404 with a hint.
- The printer log names the image path when a print fails, so a failure can be opened straight away.

To diagnose a ticket that looks wrong: find its id in the log or the ticket list, fetch the image, and compare it with the blocks in `GET /api/v1/tickets/{id}`.

## Telling Yannic on Telegram

`POST /api/v1/notify` sends a short message to his Telegram chat, through the bot set up in the wizard. Use it when a thread needs him to act.

- Body: `{"text": "..."}`, plain text, 1 to 1000 characters. Control characters are removed. Unknown fields are rejected.
- One message per caller every 60 seconds. A caller is the address the request comes from, so threads on the same machine share the limit. A second message inside the minute returns 429 with a `Retry-After` header.
- 400 means Telegram is not set up: save the bot token and chat ID in the setup wizard or with `PUT /api/v1/settings/alerts`.
- 502 means Telegram did not accept the message. The reply never includes the bot token, and the log records only the kind of error.

```
curl -sS -X POST http://192.168.1.231:30100/api/v1/notify \
  -H 'Content-Type: application/json' \
  -d '{"text": "The evening strip did not print. The printer is unplugged."}'
```

Send only when someone needs to act. A routine update is not a reason to message him.

## Where scope and AS OF work

- `metric`: `scope` ("inside" or "outside", printed as IN or OUT after the label) and `as_of` (printed as AS OF 08:15 under the chart).
- `metric_rows`: `scope` on each row, and one `as_of` for the whole block.
- Template 101 (briefing): the same two fields on each `metrics[]` entry.
- A metric or row backed by an `entity_id` is stamped with the time it was read when `as_of` is not sent.

## Settings

- Home Assistant: `GET` and `PUT /api/v1/settings/ha`, then `POST /api/v1/settings/ha/test`. The token is stored in the data folder, never in an environment variable, and is never returned by the API.
- Decision model: `GET` and `PUT /api/v1/settings/model`.
- Alerts (Telegram): `GET` and `PUT /api/v1/settings/alerts`, and `POST /api/v1/alerts/test`.

## Printer

- `GET /api/v1/printer` reports the transport and its state.
- `POST /api/v1/printer/test` prints a test strip.
- `GET /api/v1/printer/self-check` runs a self-check.

For the simulator on a laptop, point the printer at the laptop's address on TCP port 9100.

## Shopping list

The shopping list lives in Home Assistant and is managed by Hermes. It prints when someone asks for it, or when the agent
schedules a print. printarr does not hold the list and does not decide when to print it.

## Voice and leave-a-message

Deferred. No hardware is being bought. Messages come from Hermes directly, or from a Telegram bot later.

## Setup

URLs, tokens and the printer address are entered in the first-run setup wizard in the web UI, and changed later at `/setup`
with the setup code from the log. They are saved in the data folder (`/data` in the container), not in environment variables or the compose file.
Nothing in this guide needs them. The Hermes skill is at `docs/agents/hermes-skill/SKILL.md`.

## Printer paper

The printer takes an 80 mm roll. The print width is 512 dots at 180 dpi, about 72 mm.

## Not built yet

- Voice intake (`POST /api/v1/intake`): deferred. The voice button is not being bought.
- The decision model choosing a block's mood: `auto` resolves to `neutral` until it is built.
- Shopping list intake: not built. The list lives in Home Assistant, and Hermes sends it as a checklist ticket when asked, or when it schedules one.
