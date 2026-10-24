---
name: printarr
description: Print receipt strips on the printarr thermal printer through its REST API. Use to queue notes, shopping lists, reminders, briefings, alerts and messages between Yannic and the second person, to schedule or cancel a print, to release a person's waiting strips, to check the queue or printer, to look at a printed ticket image, or to ping Yannic on Telegram.
---

# printarr: print strips through the API

printarr queues receipt strips and prints them on an Epson TM-T88V (80 mm paper). You talk to it only
through its REST API.

- Base URL: `http://192.0.2.231:30100/api/v1`. Health and version are at `http://192.0.2.231:30100/healthz`.
- No authentication. The API is for the home LAN only. Never expose it to the internet.
- Two recipients: `yannic` (Yannic) and `wife` (the second person). Every request names one as `recipient`.
  The strip shows the name set for that person, but the API id is `wife`.
- The live contract is `http://192.0.2.231:30100/docs` (or its openapi.json file). If this page and the schema
  disagree, the schema wins.

Before anything else, check that setup is finished: `GET /api/v1/health`. Until Yannic has finished the
setup wizard, every other call returns 503. Tell Yannic. Do not work around it.

## 1. Check the system

| Call | Use it to |
|---|---|
| `GET /healthz` | Read the build: `{"status": "ok", "version": "...", "git_sha": "..."}`. A local build says `dev` |
| `GET /api/v1/health` | 200 when the database and printer are fine, 503 when the printer is down |
| `GET /api/v1/printer` | Printer state and any fault |
| `POST /api/v1/printer/test` | Print a test strip. Only when Yannic asks |
| `GET /api/v1/tickets?status=held&recipient=wife` | The queue. Filters: `status`, `recipient`, `limit` (max 200), `offset` |
| `GET /api/v1/tickets/{id}` | One ticket: status, attempts, `last_error` |
| `GET /api/v1/log?limit=20` | History with timings and moods. `GET /api/v1/log/summary` for counts |

Ticket statuses: `held`, `pending`, `printing`, `sent`, `failed`, `cancelled`.

## 2. Discover before you write

| Call | Returns |
|---|---|
| `GET /api/v1/blocks` | The block types, their moods, spans and limits |
| `GET /api/v1/blocks/{type}/schema` | The JSON Schema for one block's `slots`. Read it before the first use of a type |
| `GET /api/v1/slot-templates` | The fixed layouts: 101 Briefing, 102 Note |
| `GET /api/v1/templates/{id}/schema` | The schema for a slot template's `slots` |
| `GET /api/v1/insights/entities?person=yannic&limit=12` | Numeric Home Assistant entities, most notable first. Returns 422 when Home Assistant is not set up |

Use only the slots a schema lists. Do not invent entity IDs. Take them from `/insights/entities`, or ask Yannic.

## 3. Compose a strip (the default)

`POST /api/v1/tickets/compose` takes an ordered list of blocks, or a fixed preset, and draws each block as its own tile on a strip.

```bash
curl -sS -X POST http://192.0.2.231:30100/api/v1/tickets/compose \
  -H 'Content-Type: application/json' \
  -d '{
    "recipient": "wife",
    "kind": "note",
    "tone": "loving",
    "from_user": "yannic",
    "to_user": "wife",
    "sender": "hermes",
    "delivery": "on_release",
    "idempotency_key": "msg:yannic-wife:2026-10-24:cookies",
    "blocks": [
      {"type": "greeting", "mood": "loving", "slots": {"greeting": "HELLO ALLYSON"}},
      {"type": "message", "mood": "loving", "slots": {"paragraph": "Thank you for the cookies. I love you.", "from": "Yannic"}}
    ]
  }'
```

Top-level fields: `recipient` (required), `blocks` or `preset` (one of them, 1 to 16 blocks), `slots` (with `preset` only), `kind`, `tone`, `from_user`, `to_user`,
`sender`, `delivery`, `send_at`, `hold`, `hold_key`, `idempotency_key`.

- `kind`: `morning`, `evening`, `note`, `shopping`, `todo`, `alert`, `fun`, `reminder`. Default `note`.
- `tone`: `loving`, `neutral`, `reminder`, `playful`, `gentle`, `firm`, `urgent`. Default `neutral`. Printed tickets never print the tone name.
- Each block is `{"type", "mood", "slots"}`. **`mood` is required on every block.** Use one of:
  `neutral`, `happy`, `excited`, `loving`, `playful`, `reminder`, `factual`, `sad`, `confused`, `upset`,
  `gentle_warning`, `firm_complaint`, `critical`, `urgent`. `auto` is accepted but prints as `neutral` for now.
- Up to 16 blocks per ticket. Each block is its own bordered tile. Tiles sit side by side when they fit, and a strip is cut by height, not by block count.
- **Mood band.** Every card has at most one band across its top edge, and the band carries the mood. Neutral and factual have none. Sparse dots: `loving`, `happy`. Zigzag: `excited`, `playful`. Upright ticks: `reminder`. Dense stipple: `sad`, `confused`. Diagonal hatch: `gentle_warning`, `upset`. Blocks: `firm_complaint`. Barcode: `urgent`. Solid black bar with an inverted title: `critical`. Do not print mood names or tone names in the text.
- **Outline.** `urgent`, `upset` and `firm_complaint` draw a heavy square outline, and `critical` the heaviest. `loving`, `gentle_warning`, `playful` and `happy` draw rounder corners.
- Kind marks: a small mark sits at the top-right of a card for five block types: `message` (envelope), `alert` (bolt),
  `tip` (clock), `fact` (bulb) and `checklist` (cart). The mark follows the block, so pick the block type that fits.
- A release prints one person's pile as one piece of paper. The ticket with a greeting (the briefing) goes on top, and the other queued tickets follow in order, one tile apart, with no cut between them. A strip is cut after 12 tickets or when it gets too tall, and a new greeting starts a new strip. The cut is made after each strip. The blank before the cut is fed with the cut command, never drawn in a ticket. A metric label is at most 20 characters; characters the printer cannot draw print as `?` and the response lists them under `warnings`.

### Block types

| Type | Slots | Limits |
|---|---|---|
| `greeting` | `greeting`, `summary`, `from` | greeting 40 chars, summary 200, from 20 |
| `metric` | `label` and `value` or `entity_id`; `unit`, `series`, `range`, `as_of`, `scope` | label 40, unit 12, series 2 to 48 numbers |
| `metric_rows` | `rows` (1 to 6 of `label` plus `value` or `entity_id`, `unit`, `scope`); `title`, `as_of` | label 40, title 40 |
| `graph` | `title`, `series` (2 to 48 numbers); `unit`, `range` | title 40 |
| `dog_counts` | `dogs` (1 or 2 of `name`, `pee`, `poop`, `food`, `run`, integer counts) | name 20 |
| `message` | `paragraph`, `from`; `title`, `tip` | paragraph 800, from 20, title 40, tip 120 |
| `alert` | `label`, `paragraph`, `from`; `action` | label 40, paragraph 400, action 40 |
| `checklist` | `items` (1 to 8 of `text` plus `checked`); `title` | item text 120, title 40 |
| `tip` | `tip` | 120 |
| `fact` | `paragraph` | 200 |

An `entity_id` is read from Home Assistant when the strip prints, not when you send it. A missing value prints `--`.

### Simple text

`POST /api/v1/tickets` takes one plain message and picks the layout:

```bash
curl -sS -X POST http://192.0.2.231:30100/api/v1/tickets \
  -H 'Content-Type: application/json' \
  -d '{"recipient": "yannic", "sender": "hermes", "title": "Bins", "message": "Bins out tonight",
       "kind": "reminder", "tone": "reminder", "delivery": "on_release"}'
```

For messy speech-to-text input, add `"text_state": "unformatted"`. A text model then cleans spelling and speech errors, and a decision model picks the template. If either model fails, the text prints as sent. Message text is 2000 characters at most.
`POST /api/v1/tickets/preview` returns the plain text of a plain ticket without queueing it.

### Briefings (the briefing preset)

Hermes builds the morning (or evening) briefing with the briefing preset. The preset fixes the layout, so every
briefing looks the same: a headline with the time of day, three metrics with sparklines, one larger graph, a body and a fun fact.
Send `preset` and `slots` to `POST /api/v1/tickets/compose` instead of `blocks`. Use `delivery: "on_release"`
and a fixed `idempotency_key`, for example `morning:yannic:2026-10-26`:

```bash
curl -sS -X POST http://192.0.2.231:30100/api/v1/tickets/compose \
  -H 'Content-Type: application/json' \
  -d '{"recipient": "yannic", "sender": "hermes", "kind": "morning", "preset": "briefing",
       "delivery": "on_release", "idempotency_key": "morning:yannic:2026-10-26",
       "slots": {"time_of_day": "morning",
                 "metrics": [{"label": "Steps", "entity_id": "sensor.steps", "unit": "steps"},
                             {"label": "Inside", "entity_id": "sensor.living_room_temperature", "unit": "C"},
                             {"label": "Battery", "entity_id": "sensor.body_battery", "unit": "%"}],
                 "graph": {"title": "Heart rate", "entity_id": "sensor.heart_rate", "hours": 12},
                 "body": "Two dogs walked before breakfast. Rain after lunch, so the run is at 4.",
                 "fun_fact": "Octopuses have three hearts.", "from": "hermes"}}'
```

- `time_of_day` is `morning`, `afternoon` or `evening`. The headline reads GOOD MORNING, GOOD AFTERNOON or GOOD EVENING.
- `scope` is `inside` or `outside` and prints as IN or OUT after the label. `as_of` prints as AS OF 08:15 under the readings.
- `metrics` is exactly three. Each has an `entity_id` (its value and sparkline come from Home Assistant) or a fixed `value`. `hours` (1 to 168, default 24) sets how far back the sparkline reaches.
- `graph` has a `title` and an `entity_id` (its history) or `series` (fixed values, oldest first). If Home Assistant has no history, the graph is left out and the rest still prints.
- `body` is the text, up to 800 characters. `fun_fact` is one line, up to 200 characters. Printarr adds no heading or label to a fun fact; write the fact as one sentence. The words can appear inside the sentence when they read naturally.
- Do not send `blocks` with `preset`. A bad slot returns 422 and names it as `preset.slots.field`.

The older slot briefing (template 101, `POST /api/v1/tickets/slots`) still works, but use the preset for new briefings.

## 4. Schedule, release, cancel

printarr never creates schedules. It holds a ticket until it is due. You decide when things print.

| `delivery` | When it prints | Use it for |
|---|---|---|
| `on_release` | On the recipient's next release (morning when the phone is unplugged, evening or arrival when home) | Briefings, messages between Yannic and the second person |
| `at` | At `send_at` (local time, no offset, for example `2026-10-25T18:00:00`) as its own strip | "Remind me at 18:00", a shopping list for when Yannic gets home |
| `now` | Straight away, as its own strip | Shopping lists on request, alerts |

- `at` needs `send_at`. `now` must not have `send_at`.
- No recurring tickets exist. A repeating reminder is one ticket per occurrence, each with its own `send_at`.
- Scheduled releases belong to Home Assistant. Release a pile yourself only when someone asks for paper now:
  `POST /api/v1/people/{person}/release` with `{"trigger": "request"}`. Triggers: `morning`, `evening`, `arrival`, `request`.
- Hold and release: set `"hold": true` with a `hold_key` such as `user-home`. Release one ticket with
  `POST /api/v1/tickets/{id}/release`, or every ticket with that key with `POST /api/v1/holds/{hold_key}/release`.
  Do not hold strip content for a person. Use `on_release`.
- Cancel a waiting ticket: `POST /api/v1/tickets/{id}/cancel`.
- Print a failed or cancelled ticket again: `POST /api/v1/tickets/{id}/retry`.

### Shopping list

The shopping list lives in Home Assistant, and you manage it. printarr keeps no list. Send a snapshot each time:

```bash
curl -sS -X POST http://192.0.2.231:30100/api/v1/tickets/compose \
  -H 'Content-Type: application/json' \
  -d '{"recipient": "yannic", "kind": "shopping", "tone": "neutral", "sender": "hermes", "delivery": "now",
       "blocks": [
         {"type": "greeting", "mood": "neutral", "slots": {"greeting": "SHOPPING"}},
         {"type": "checklist", "mood": "neutral", "slots": {"title": "Groceries", "items": [
           {"text": "Milk (oat)"}, {"text": "Dog food, 2 bags"}, {"text": "Eggs x6", "checked": true}]}}
       ]}'
```

For a list that prints when Yannic gets home, send it with `delivery: "at"` and a `send_at` you choose.

## 5. Ping Yannic on Telegram

`POST /api/v1/notify` sends a short plain-text message to his Telegram chat:

```bash
curl -sS -X POST http://192.0.2.231:30100/api/v1/notify \
  -H 'Content-Type: application/json' \
  -d '{"text": "Printarr is on build 86. The next test can run."}'
```

- Body: `{"text": "..."}`, 1 to 1000 characters. Unknown fields are rejected.
- One message per caller every 60 seconds. A second message inside the minute returns 429 with `Retry-After`.
- 400 means Telegram is not set up. Tell Yannic. 502 means Telegram refused it. Try later.
- Send only when Yannic needs to act. Routine news is not a reason to message him.

## 6. Look at a printed ticket

Printarr keeps a PNG of each ticket as it reached the printer, and of each ticket whose print failed. Use it to check
what the paper showed. The newest 250 are kept.

- `GET /api/v1/ticket-images?limit=50` lists them, newest first. Each row has `id`, `kind`, `template`, `recipient`,
  `status`, `created_at`, `printed_at` and `image_url`.
- `GET /api/v1/tickets/{id}/image` returns the PNG (`image/png`). Save it to a file and look at it:

```bash
curl -sS -o ticket.png http://192.0.2.231:30100/api/v1/tickets/<id>/image
```

A ticket still waiting, cancelled before printing, or older than the kept images returns 404 with a hint.
Text is drawn from an approximation of Font A, so check the wording against the real paper or the simulator.

To diagnose a ticket that looks wrong: find its id, fetch the image, and compare it with
`GET /api/v1/tickets/{id}` (the blocks, moods and `last_error`).

## 7. Writing rules for tickets

- **Say the headline once.** Use `title` or the block's heading, and do not repeat it in the body.
- **Title plus a short body.** One message in one box. Do not split a single message across two blocks.
- **Greetings belong to briefings.** A single-topic ticket (bins, a reminder, a note) has no greeting block.
- **A fun fact is a `fact` block with mood `playful`.** Printarr prints its text alone, with no "Did you know" or "FUN FACT" label. Do not use a `fact` block for a reminder, note or alert.
- **Shopping lists are checklists**, one item per block entry. Never put items in one paragraph.
- **Pick the mood to match the intent.** Read the mood list in section 3 and choose what the paper will say at a glance:
  - `loving` (sparse dots): messages between Yannic and the second person.
  - `reminder` (upright ticks): times and to-dos.
  - `gentle_warning` (diagonal hatch, rounder outline): a soft heads-up.
  - `urgent` (barcode): needs attention.
  - `critical` (solid bar): needs attention now, and only then.
  - `factual`: numbers and status. `happy`, `excited`, `playful`: good news and fun.
- **Keep text short for 42 columns.** Font A prints 42 characters per line. Long words wrap badly, so prefer short sentences.
- **Characters outside CP437 print as `?`.** CJK and emoji do not print. Use plain ASCII where you can.
- **Dates and times in local time**, without an offset, for `send_at`.
- **No credentials, tokens or health details** in a ticket. Never put one person's private details on the other person's paper.
- **Use idempotency keys** on anything that could be sent twice. A repeat with the same key returns the first ticket and prints nothing new.

## 8. Errors, and how to fix each one

Every 4xx returns `{"detail": ..., "hint": "...", "example": {...}}`. Read the `hint` and every item in `detail`,
fix the request, and send it again. Do not resend the same body.

| Message contains | Fix |
|---|---|
| `mood must be one of` | Add a valid `mood` to every block |
| `unknown block type` | Use a type from `GET /api/v1/blocks` |
| `Field required` | Add the slot named in `slot`, for example `blocks[0].slots.paragraph` |
| `String should have at most N characters` | Shorten the text |
| `delivery at needs send_at` | Add `send_at` in local time |
| `delivery now cannot take send_at` | Remove `send_at`, or use `delivery: "at"` |
| `Input should be 'yannic' or 'wife'` | Use the recipient id, not a name |
| `template N is not a slot template` | Use 101 (briefing) or 102 (note) |
| `Home Assistant is not configured` | Tell Yannic, or use literal values |
| 404 on a ticket | Check the id, or list tickets |
| 503 on everything | Setup is not finished. Tell Yannic |
| 502 on preview or print | Home Assistant or the printer could not be reached. Try later, then check `GET /api/v1/printer` |
| `status: failed` with `last_error` | Read `last_error`. Retry only if it is safe |

## 9. Things not to do

- Do not release a pile on a schedule. Home Assistant does that.
- Do not invent entity IDs.
- Do not send tokens or other secrets in any request. The API never returns the Home Assistant token.
- Do not print somewhere else when the printer is down. Report it to Yannic.
- Do not expose port 30100 to the internet.
