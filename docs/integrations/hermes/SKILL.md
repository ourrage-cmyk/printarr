# printarr: how Hermes prints a receipt

printarr is the receipt printer for Yannic (`yannic`) and Allyson (`wife`). Talk to it only through
its REST API at `http://PRINTARR_URL/api/v1`. Tool definition: `openapi.yaml`. Worked example: `example-morning-briefing.md`.

## The main idea: strips per person

Nobody shares a strip. Each person's pile prints on their own strip, released by Home Assistant when
their phone is unplugged (morning) or when they arrive home (evening). Anything Hermes queues for a person
waits in that person's pile until then, unless it is standalone.

So when Hermes writes something for a person, it chooses one of three deliveries:

| `delivery` | Meaning | Use for |
|---|---|---|
| `on_release` | Waits in the person's pile. Prints on their next strip. | Briefings, messages between the two of them |
| `at` | Prints at `send_at` (local time, no offset). Standalone. | "Remind me at 3pm", a timed note |
| `now` | Prints and cuts at once. Standalone. | Shopping lists, reminders, alerts, a print on request |

Default is `now`, or `at` when `send_at` is given.

## Who owns the schedule

printarr does not make schedules. It holds each item until it is due, then prints it. Every schedule comes
from outside: Hermes, or Home Assistant on its triggers. So:

- Hermes decides when something prints by choosing `delivery` and `send_at`, and it creates one ticket per moment.
  There are no recurring tickets. For a repeating reminder, Hermes creates each occurrence (or a scheduled job of its own does).
- Shopping lists print only when someone asks for one, or when Hermes or a scheduled job of its own asks for one.
- Briefings and messages wait for the person's strip. Home Assistant releases the strip on the phone and arrival triggers.
- Addresses (printarr, the laptop simulator, the LLM server) come from the setup wizard. Never hard-code them.

## Which operation to use

| Want to | Call |
|---|---|
| A briefing for the next strip | `GET /templates/101/schema`, then `POST /tickets/slots` with `template: 101`, `delivery: on_release`, and an `idempotency_key` |
| A message from one person to the other | `POST /tickets` with `from_user`, `to_user`, `delivery: on_release` |
| A standalone item now | `POST /tickets` with `delivery: now` |
| A standalone item at a time (a reminder, a timed note) | `POST /tickets` with `delivery: at` and `send_at` |
| Print a person's pile now, on request | `POST /people/{yannic\|wife}/release` with `{"trigger": "request"}` |
| Choose graph candidates for a briefing | `GET /insights/entities?person=...` |
| Cancel a pending ticket | `POST /tickets/{id}/cancel` |
| Read what was printed | `GET /log` |

## Rules

1. Set `sender` to `hermes`.
2. Use `recipient` `yannic` or `wife`. The name "Allyson" only appears on the ticket.
3. Briefings are `on_release`. Do not release the pile yourself on a schedule: Home Assistant does that on the
   phone and arrival triggers. Only call the release endpoint when someone asks for paper now, with `trigger: request`.
4. Set an `idempotency_key` on every briefing, for example `morning:yannic:2026-10-26`. A retry returns the first ticket.
5. Fetch the schema for a slot template before filling it, and fill only the slots it lists.
6. For a briefing, call `GET /insights/entities` first and choose the metrics from that list. Do not invent entity IDs.
7. Keep text inside the limits in the schema. Briefing paragraph is 400 characters, tip is 120, metric label is 20.
8. If a call returns 422, read the problems list, fix the request, and send again. Do not resend unchanged.
9. Avoid `hold` and `hold_key` for anything in a person's strip. They still work, but they do not join the pile.

## Briefing shape

A briefing has four parts, in this order:

1. **Greeting**: left out, printarr writes one from the time of day, with the person's name at the top.
2. **Up to four metrics**: each from `/insights/entities`, with a short label and unit. Choose the ones
   that are unusual (`z_score` above 2 or below -2), trending (`trend` not `flat`), or most relevant (`relevance` 3).
3. **Paragraph**: a few plain sentences covering the metrics and anything else worth knowing today. No markdown.
4. **Tip**: one line at the end.

Keep the paragraph calm and factual. Use `tone` for messages between the two people, not for briefings.

## Things not to do

- Do not put one person's health detail on the other person's ticket.
- Do not create two briefings for the same person and day.
- Do not use entity IDs that are not in the insights list without checking they exist.
