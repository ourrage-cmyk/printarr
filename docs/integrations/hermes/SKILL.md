# printarr: how Hermes prints a receipt

printarr is the receipt printer for Yannic (`yannic`) and Allyson (`wife`). Talk to it only through
its REST API at `http://PRINTARR_URL/api/v1`. Tool definition: `openapi.yaml`. Worked example: `example-morning-briefing.md`.

## Which operation to use

| Want to | Call |
|---|---|
| A morning or evening briefing | `GET /templates/101/schema`, then `POST /tickets/slots` with `template: 101` (add `hold` and keys for a held briefing) |
| A note or message between the two people | `POST /tickets/slots` with `template: 102`, or `POST /tickets` with plain `message` |
| Choose graph candidates for a briefing | `GET /insights/entities?person=...` |
| Cancel a pending ticket | `POST /tickets/{id}/cancel` |
| Read what was printed | `GET /log` |
| Check what is waiting | `GET /tickets?status=pending` or `?status=held` |

## Rules

1. Set `sender` to `hermes`.
2. Use `recipient` `yannic` or `wife`. The name "Allyson" only appears on the ticket.
3. Fetch the schema for a slot template before filling it, and fill only the slots it lists.
4. For a briefing, call `GET /insights/entities` first and choose the metrics from that list. Do not invent entity IDs.
5. Keep text inside the limits in the schema. Briefing paragraph is 400 characters, tip is 120, metric label is 20.
6. Use `send_at` to print at a time (local time, no offset, is the server timezone). Leave it out to print when queued.
7. If a call returns 422, read the problems list, fix the slots, and send again. Do not resend unchanged.

## Holds and retries on briefings

`POST /tickets/slots` accepts `hold`, `hold_key`, `idempotency_key` and `blocks`. For a briefing that Home
Assistant should release on phone unplug, send `hold: true`, `hold_key: morning-<person>-<date>` and
`idempotency_key: morning:<person>:<date>`. A retry with the same key returns the first ticket.

## Briefing shape

A morning briefing has four parts, in this order:

1. **Greeting**: by local time. Left out, printarr writes "Good morning, Yannic". Write your own only if it adds something.
2. **Up to four metrics**: each from `/insights/entities`, with a short label and unit. Choose the ones
   that are unusual (`z_score` above 2 or below -2), trending (`trend` not `flat`), or most relevant (`relevance` 3).
3. **Paragraph**: a few plain sentences covering the metrics and anything else worth knowing today. No markdown.
4. **Tip**: one line at the end. A useful tip, a reminder, or a light note.

Keep the paragraph calm and factual. Use `tone` for messages between the two people, not for briefings.

## Things not to do

- Do not send one person's health detail to the other person's ticket.
- Do not create two briefings for the same person and day.
- Do not use entity IDs that are not in the insights list without checking they exist.
