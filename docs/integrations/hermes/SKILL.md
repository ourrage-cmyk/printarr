# printarr: how Hermes prints a receipt

printarr is the receipt printer for Yannic (`yannic`) and Allyson (`wife`). Talk to it only through
its REST API at `http://PRINTARR_URL/api/v1`. Tool definition: `openapi.yaml`. Example briefing: `example-morning-briefing.md`.

## Which operation to use

| Want to | Call |
|---|---|
| Print something now, or at a time | `createTicket` with `send_at` or no time |
| Prepare a briefing that prints on a trigger | `createTicket` with `hold: true` and a `hold_key` |
| See what fits a briefing | `listInsightEntities` for the person |
| Undo something not yet printed | `cancelTicket` on a `pending` ticket |
| Check what was printed before | `readHistory` |
| Check what is waiting | `listTickets` with `status=pending` or `status=held` |

## Rules

1. Always set `idempotency_key` for a briefing, for example `morning:yannic:2026-10-26`. A retry then
   returns the first ticket and prints nothing new.
2. Set `sender` to `hermes`.
3. Use `recipient` `yannic` or `wife`. Never use "Allyson" in the API; the name only appears on the ticket.
4. Use `hold_key` per person and day, for example `morning-yannic-2026-10-26`. Home Assistant releases it when the phone is unplugged.
5. Do not combine `hold` with `send_at`.
6. Keep `message` plain text, up to 2000 characters. For briefings, prefer the slot fields once API-core ships them.
7. Before a briefing: call `listInsightEntities` and choose from its list. Do not invent entity IDs.
8. If a call fails, read the error. A 422 means the request is wrong, so fix it and do not retry as is. A 5xx or timeout means retry with the same `idempotency_key`.

## Briefing shape

A morning briefing has four parts, in this order:

1. **Greeting**: by the local time. Morning before 12:00, afternoon before 17:00, evening after that. One short line.
2. **Four metrics**: four entities from `listInsightEntities`, each with a label and unit. The printer draws each as a graph. Choose the ones that are unusual (`z_score` far from 0), trending (`trend` not `flat`), or most relevant to this person (`relevance` 3). Say briefly why each one was chosen.
3. **Paragraph**: a few sentences in plain English, covering the four metrics and anything else worth knowing today. No markdown.
4. **Tip**: one line at the end. A useful tip, a reminder, or a light joke.

Tone: keep the paragraph calm and factual. Use the tone field for a message from one person to the other, not for briefings.

## Things not to do

- Do not print a second briefing for the same person and day. Use the key.
- Do not send private health detail to the other person's ticket. Each briefing is for its own recipient only.
- Do not use HA entities that are not in the insights list without checking they exist.
