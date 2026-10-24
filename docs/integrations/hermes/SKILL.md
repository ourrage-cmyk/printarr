---
name: printarr
description: Print receipt strips on the printarr thermal printer through its REST API. Use for notes, shopping lists, reminders, briefings, alerts and messages between Yannic and Allyson, or to release a person's waiting strips.
---

# printarr: print receipts through the API

printarr queues receipts and prints them on an Epson TM-T88V (80 mm paper). You talk to it only through
its REST API. The base URL is `http://<printarr-host>:8000/api/v1`. The API has no authentication and runs
on the home LAN only.

Before anything else, check that setup is finished. Until Yannic completes the setup wizard at `/`, the API
answers only the setup routes and `GET /api/v1/health`. Every other call returns 503 with a pointer to the wizard.
Tell Yannic. Do not try to work around it.

Two people receive prints: `yannic` (Yannic) and `wife` (Allyson). Every request names one of them as
`recipient`. The name printed on the strip is "Allyson", but the API id is `wife`.

The live contract is `docs/openapi.json`, and the `/docs` page on the running service. When this page and
the schema disagree, the schema wins. Every call below was checked against the running API.

## 1. Choose a delivery first

| `delivery` | When it prints | Use it for |
|---|---|---|
| `on_release` | On the recipient's next strip. The ticket waits in their pile until Home Assistant releases it (phone unplugged in the morning, or arriving home in the evening). | Briefings, messages between Yannic and Allyson, anything that can wait |
| `at` | At `send_at` (local time, no offset). Its own strip. | "Remind me at 18:00", a timed note |
| `now` | Straight away, as its own strip. | Shopping lists, alerts, "print this now" |

- `at` needs `send_at`. Without it the call returns 422 `delivery at needs send_at`.
- `now` cannot take `send_at`. The call returns 422 `delivery now cannot take send_at; use delivery at`.
- With no `delivery`, the default is `at` if `send_at` is set, otherwise `now`.
- printarr never creates schedules. You decide when each ticket prints. Each timed item is its own ticket, with
  `delivery: at` and its own `send_at`. There are no recurring tickets. A repeating reminder is one ticket per
  occurrence, created by you or by a scheduled job of your own.
- Release a pile only when someone asks for paper now: `POST /people/{person}/release` with `{"trigger": "request"}`.
  Never release on a schedule. Home Assistant handles the scheduled releases.

## 2. Discover before you write

| Call | Returns |
|---|---|
| `GET /blocks` | The composable block types, their moods, span and unit limits, and a schema link for each |
| `GET /blocks/{type}/schema` | The JSON Schema for one block's `slots` |
| `GET /slot-templates` | The fixed layouts: 101 Briefing, 102 Note |
| `GET /templates/{id}/schema` | The JSON Schema for a slot template's `slots` |
| `GET /insights/entities?person=yannic&limit=12` | Numeric Home Assistant entities, most notable first. Returns 422 when Home Assistant is not configured |
| `GET /templates` | The plain-text layouts used by `POST /tickets` |

Fetch the schema before filling a block or a slot template for the first time. Use only the slots it lists.

## 3. Compose a strip (preferred)

`POST /tickets/compose` takes an ordered list of blocks, and draws them as one or more strips.

```json
{
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
    {"type": "message", "mood": "loving", "slots": {"paragraph": "Thank you for the cookies. I love you so much.", "from": "Yannic"}}
  ]
}
```

Top-level fields: `recipient` (required), `blocks` (required, 1 to 16 items), `kind`, `tone`, `from_user`,
`to_user`, `sender`, `delivery`, `send_at`, `hold`, `hold_key`, `idempotency_key`.

Each block is `{"type": ..., "mood": ..., "slots": {...}}`:

- **`mood` is required on every block.** Choose one of: `neutral`, `happy`, `excited`, `loving`, `playful`,
  `reminder`, `factual`, `sad`, `confused`, `upset`, `gentle_warning`, `firm_complaint`, `urgent`.
  `auto` is accepted but prints `neutral` until the decision model picks moods.
- **A greeting always starts a new strip.** By default a strip holds at most 5 blocks. A ticket with more blocks
  prints as several strips.

### Block types and their slots

| Type | Slots (required first) | Limits |
|---|---|---|
| `greeting` | `greeting`, `summary` | greeting 40 chars, summary 200 |
| `metric` | `label` and one of `value` or `entity_id`; `unit`, `series` | label 40, unit 12, series 2 to 48 numbers |
| `metric_rows` | `rows` (1 to 6 of `label` plus `value` or `entity_id`, `unit`); `title` | label 40, title 40 |
| `graph` | `title`, `series` (2 to 48 numbers); `unit` | title 40 |
| `dog_counts` | `dogs` (1 or 2 of `name`, `pee`, `poop`, `food`, `run`; counts are integers from 0) | name 20 |
| `message` | `paragraph`, `from`; `title`, `tip` | paragraph 800, from 20, title 40, tip 120 |
| `alert` | `label`, `paragraph`; `action` | label 40, paragraph 400, action 40 |
| `checklist` | `items` (1 to 8 of `text` plus `checked`); `title` | item text 120, title 40 |
| `tip` | `tip` | 120 |
| `fact` | `paragraph` | 200 |

An entity-backed slot (`entity_id`) is read from Home Assistant when the ticket prints. Configure
Home Assistant first. Without it, the value prints as `--` and the call still succeeds.

Pick moods to match the content: `loving` for messages between them, `reminder` for reminders,
`urgent` or `firm_complaint` for alerts, `factual` for numbers, `gentle_warning` for things to watch.

## 4. Simple text

`POST /tickets` takes plain text. The API picks the layout.

```json
{"recipient": "yannic", "sender": "hermes", "title": "Reminder", "message": "Bins out tonight",
 "kind": "reminder", "tone": "reminder", "delivery": "at", "send_at": "2026-10-25T18:00:00"}
```

For speech-to-text or other messy input, add `"text_state": "unformatted"`. The text model tidies it, and if
the model is down the text prints as sent. Message text is 2000 characters at most, and wraps at 42 columns.
Characters outside CP437 print as `?`.

## 5. Briefings (slot template 101)

Briefings are slot tickets: `POST /tickets/slots`. Use `on_release`, so the strip joins the person's pile.

```json
{
  "template": 101,
  "recipient": "yannic",
  "sender": "hermes",
  "kind": "morning",
  "delivery": "on_release",
  "idempotency_key": "morning:yannic:2026-10-26",
  "slots": {
    "greeting": "Good morning, Yannic",
    "metrics": [
      {"label": "SLEEP", "entity_id": "sensor.sleep_score", "hours": 168},
      {"label": "STEPS", "entity_id": "sensor.total_steps", "unit": "steps", "hours": 168}
    ],
    "paragraph": "Sleep was short, and steps are below your usual level. Take it easy today.",
    "tip": "Leave five minutes early."
  }
}
```

Slot limits: `greeting` 40, `title` 60, `paragraph` 400 with `formatted: true` (or raw speech with `formatted: false`),
`tip` 120, up to 4 `metrics`. Each metric has `label` at most 20 characters.

Briefing shape, in order: greeting, up to four metrics, a short paragraph, one tip. Choose metrics from
`/insights/entities`, preferring unusual values (`z_score` beyond ±2), clear trends, and relevance 3. Do not
invent entity IDs.

## 6. Recipes

**Shopping list now.** The shopping list lives in Home Assistant, and you manage it. printarr keeps no list,
so each print is a snapshot of the list you send.

```json
{"recipient": "yannic", "kind": "shopping", "sender": "hermes", "delivery": "now",
 "blocks": [
   {"type": "greeting", "mood": "neutral", "slots": {"greeting": "SHOPPING"}},
   {"type": "checklist", "mood": "neutral", "slots": {"title": "Groceries", "items": [
     {"text": "Milk (oat)"}, {"text": "Dog food, 2 bags"}, {"text": "Eggs x6", "checked": true}]}}
 ]}
```

**Shopping list at 17:00, for when Yannic gets home.** Create it yourself with `delivery: "at"` and `send_at`.
printarr does not print it on a timer of its own.

**Leave a message for the other person.** Use `from_user`, `to_user` and `on_release`. It arrives on their
strip at their next release, and it shows in their inbox as unread. Use the recipe in section 3.

**Alert now.**

```json
{"recipient": "yannic", "kind": "alert", "sender": "hermes", "delivery": "now",
 "blocks": [
   {"type": "alert", "mood": "urgent", "slots": {"label": "WATER LEAK", "paragraph": "Water under the kitchen sink. Turn off the stopcock now.", "action": "Stopcock"}}
 ]}
```

**Live numbers from Home Assistant on a note.** Use a `metric_rows` block with `entity_id`s. Entity-backed rows
read Home Assistant at print time, not when queued.

**Hold a ticket, release it later.** Set `"hold": true` and a `hold_key`, for example `"user-home"`. Release
one ticket with `POST /tickets/{id}/release`, or every ticket with that key with `POST /holds/{hold_key}/release`.
Do not hold strip items for a person. Let `on_release` do it.

**Check what happened.** `GET /tickets?status=held&recipient=wife`, `GET /tickets/{id}` (status, attempts, last_error),
`GET /log?limit=20` for the history.

**Cancel or reprint.** `POST /tickets/{id}/cancel` for a pending ticket. `POST /tickets/{id}/retry` prints a failed
or cancelled ticket again now.

**Check the layout first.** `POST /tickets/preview` returns the plain text of a plain-text ticket without queueing it.
Composed strips with a graph or raster show `[graph]` in the text preview, so the preview cannot show their
layout. Trust the schema and the limits in section 3 for those.

## 7. Errors, and how to fix each one

Validation errors come back as 422, and every error has a `hint` that says what to do next. Read the `hint`
and every item in `detail`, fix the request, and send it again. Do not resend the same body. An `example` is
included when one helps.

The shape is `{"detail": ..., "hint": "...", "example": {...}}`. `detail` takes one of three forms:

- A list of `{"slot": "...", "problem": "..."}`. The `slot` is a path into the request, for example
  `blocks[0].slots.label`. Fix that field.
- A string, for example `"delivery at needs send_at"`.
- A list with `loc` and `msg`, from schema validation. The `loc` names the field, for example `["body", "recipient"]`.

| Message contains | Fix |
|---|---|
| `mood must be one of` | Add a `mood` to every block, from the list in section 3 |
| `unknown block type` | Use a type from `GET /blocks` |
| `Field required` | Add the slot named in `slot`, for example `blocks[0].slots.paragraph` |
| `String should have at most N characters` | Shorten the text to N characters |
| `delivery at needs send_at` | Add `send_at` as local time, for example `2026-10-25T18:00:00` |
| `delivery now cannot take send_at` | Remove `send_at`, or use `delivery: at` |
| `Input should be 'yannic' or 'wife'` | Use the recipient id, not a name |
| `template N is not a slot template` | Use 101 (briefing) or 102 (note) |
| `Home Assistant is not configured` | Tell Yannic. Use literal values, or leave out the block that needs Home Assistant |
| 404 `ticket not found` | Check the id, or list tickets to find it |
| 502 on preview | Home Assistant could not be reached while building the preview. Try again later |
| 500 on create | The renderer failed. Nothing was queued. Simplify the blocks and try again |
| `status: failed` with `last_error` | The print failed after retries. Read `last_error`, then retry if it is safe |

Limits that come from the printer, not from the schema: 42 columns in Font A, 512 dots across, and CP437 text only.
CJK and emoji do not print.

## 8. Idempotency

Set an `idempotency_key` on anything that might be sent twice: a briefing, a message, a reminder created from
speech. A second request with the same key returns the first ticket and prints nothing new. Use a key that names
the event, for example `morning:yannic:2026-10-26` or `msg:yannic-wife:<timestamp>`.

## 9. Things not to do

- Do not put one person's health details on the other person's ticket.
- Do not create two briefings for the same person and day.
- Do not invent entity IDs. Use `/insights/entities`, or ask Yannic.
- Do not release a pile on a schedule. Home Assistant does that.
- Do not send Home Assistant tokens or any other secret in a ticket. The API never returns the Home Assistant token.
- Do not expose port 8000 to the internet.
- Do not use `hold` for strip content. Use `on_release`.

## 10. Who to ask

If the printer is down, `GET /api/v1/printer` and `GET /api/v1/health` say why. Tell Yannic. Do not work around it by
printing somewhere else.
