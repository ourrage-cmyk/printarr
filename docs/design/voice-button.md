# Voice button: leave a message, add to the shopping list

Status: parked. Design only. No hardware is bought or built, and no endpoint is added. Revisit when Yannic asks for it.

## Decisions (Yannic, 2026-10-24)

- **Hardware:** on hold. Nothing is purchased. Until then, messages go to Hermes directly, or to a separate Telegram bot that Hermes manages. Neither needs new hardware.
- **Release:** hold to record, and on release the transcript is formatted, the template is chosen, and the note prints **instantly**. The point is that the note can be picked up and stuck on the fridge or a bathroom mirror.
- **Reminders:** a reminder does not print on its own. It goes on the scheduled slip that already comes out at its time.
- **Sender:** filled in automatically from the button or phone used. The sender is inferred from the addressee, since it is easy to tell who is speaking by who is being addressed. Not built now.
- **Shopping list:** lives in Home Assistant and is managed by Hermes. It prints only when requested or when scheduled.
- **Scheduling lives outside the container.** The printarr container does not hold a calendar or a schedule UI. It stores tickets, assigns templates and text, and holds a schedule until it runs. The agent (Hermes) creates and manages every schedule through the API. Keeping it that way means every ticket has a known source.
- **Network:** LAN only. No API key. Server and laptop addresses, and the URLs and tokens, are set in the setup wizard in the web UI, not in the Docker stack.
- **Paper:** 80 mm wide, which matches the TM-T88V documentation. A roll arrives Monday.

The rest of this document describes the option space for later. The decisions above override anything that disagrees with them.

## The idea

A button sits next to the printer in the living room. Press and hold, speak, release. The speech becomes one of two things:

- "Leave a message for my wife: thank you for the cookies, I love you." Prints on the second person's next strip, as a message from Yannic.
- "Add oat milk to the shopping list." Adds oat milk to the shopping list, and the list can be printed on request or at a time.

The shape is a tape recorder. Nothing is typed, and the printer does not need to understand speech itself.

## Recommendation

Use **Home Assistant Assist** as the voice layer. Use **an ESP32-S3 satellite with a button** or **Home Assistant Voice Preview Edition** as the hardware. Use **a new printarr intake endpoint** that turns the transcript into an existing ticket or list item. Do not route free dictation through Google Nest.

Minimal first build, in order:

1. Hold-to-talk satellite connected to HA Assist, with Whisper (faster-whisper on the LAN) for speech-to-text.
2. A HA script that sends the transcript to printarr as `POST /api/v1/intake` (new, below).
3. Printarr parses the transcript with fixed rules, asks the decision model only when the rules are unsure, and queues either a message ticket (the existing `printarr_leave_message` path) or a shopping list change.

This reaches the goal with no cloud service in the path, and the parts that already exist (messages, shopping list, release) are reused.

## Hardware options

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Home Assistant Voice Preview Edition** | HA's own voice satellite with mic, speaker, and a button. | Built for Assist. Wake word and button both work. Nothing to flash. | Costs money and needs its own power point. Enclosure may not suit a shelf by a TV. |
| **B. ESP32-S3 with mic and button (ESPHome)** | Small board with an I2S mic, a speaker or none, and one push button. ESPHome's `voice_assistant` component streams audio to HA. | Cheap. The button can be a plain push button on a wire, placed anywhere. Fits a box by the printer. | Needs flashing and some ESPHome YAML. Quality depends on the mic board. |
| **C. Phone shortcut** | iOS or Android shortcut that records and posts the transcript to the intake endpoint. | Zero hardware. Works now. | Not a button by the printer. Needs the phone. Good as a fallback and for testing. |
| **D. Wyoming satellite on a Pi or spare box** | `wyoming-satellite` with a USB mic and button. | Same as B, using a computer rather than a microcontroller. | Bigger. Needs a power supply and a network cable or Wi-Fi. |

Recommendation: **B** for the real button, **C** to test the flow this week. **A** is the choice if you would rather buy than build.

## Speech to text

| Option | Notes |
|---|---|
| **faster-whisper via the Wyoming add-on in HA** | Runs on the LAN, no cloud. A `small` or `base` model is enough for short English messages on CPU. Use `medium` if accents or names fail. |
| HA Cloud speech | Works, but sends audio to a cloud. Avoid for private messages. |

Recommendation: faster-whisper, `small` model, on the same box as HA. Measure latency before choosing a larger model.

Names matter: "the second person" should be recognised. Add it to the Whisper initial prompt or to HA's custom sentences so the recipient is not misheard as "Alison" or "Ellison".

## From transcript to structured input

The printarr API already takes the shape it needs. The voice path only has to fill it in.

| Field | Source |
|---|---|
| `recipient` (`yannic` / `wife`) | Parsed from "for my wife", "for the second person", "for Yannic", or the sender is the other person. |
| `from_user` | The speaker. First version: set by which satellite heard it, so one satellite per person, or one shared satellite that asks. |
| `message` | The text after the colon, or the whole phrase after the verb. |
| `kind` | `note` for a message, `shopping` for a list item. |
| `tone` | Left as `neutral`. The decision model may pick `loving` for messages later. |
| `text_state` | `unformatted`, so Granite cleans the speech. |

### Who does the parsing

Use **fixed rules first**. The phrases people use are few and predictable:

- Message: "leave a message for <name>", optionally followed by a colon or "saying".
- Shopping: "add <item(s)> to the shopping list", "put <item> on the list".

Rules are cheap, testable, and never invent a recipient. When the rules fail, use the decision model.

**d1 is a scoring endpoint, not a chat model.** Use it the way it is already used for templates: ask it yes/no or 0 to 1 questions such as "Is this a request to add to a shopping list? 0 to 1." It does not write text.

**Granite (granite4.2:3b) cleans prose.** Use it only for the message body, through `text_state: unformatted`, never to decide who the message is for.

Order for each transcript:

1. Rules match a message or shopping pattern: use it.
2. No rule matches, or the recipient is unclear: ask d1 for the kind and the recipient. Accept only a clear answer.
3. Still unclear: reject with a teaching error (below). Do not guess a recipient, because a message in the wrong pile is a mess to undo.

## New endpoint

`POST /api/v1/intake`

```json
{
  "transcript": "leave a message for my wife thank you for the cookies I love you",
  "sender": "voice-living-room",
  "speaker": "yannic",
  "dry_run": false
}
```

Response, for a message (201):

```json
{
  "action": "message",
  "recipient": "wife",
  "from_user": "yannic",
  "message": "Thank you for the cookies. I love you.",
  "delivery": "on_release",
  "ticket_id": "...",
  "parsed_by": "rules"
}
```

Response, for a shopping item (201): `"action": "shopping_add"`, `"items": ["oat milk"]`, and whether the list entity was updated.

Rules for the endpoint:

- `dry_run: true` returns the interpretation without queuing or writing. Use it in the web UI and in tests.
- Shopping items are written to the HA list, managed by Hermes, not to printarr's database (see below).
- The same transcript sent twice in one day should not make two tickets. Use an `idempotency_key` derived from the transcript and the day, as the HA script already does.
- An unknown or unclear transcript returns 422, with `detail` and a `how_to_fix` field.

### Teaching errors

The API is also used by agents, so a 422 must say what to send. Example:

```json
{
  "error": "intent_unclear",
  "detail": "No recipient and no shopping phrase found in the transcript.",
  "how_to_fix": "Start with 'leave a message for my wife' or 'add <item> to the shopping list'. Or send 'recipient' ('yannic' or 'wife') and 'message' explicitly, then call POST /api/v1/tickets.",
  "accepted": {"action": ["message", "shopping_add"], "recipient": ["yannic", "wife"]}
}
```

This is the pattern the rest of the API should follow. Keep it in the endpoint, and copy it to any new error.

## Shopping list

**Recommendation: keep the list in Home Assistant (`todo.shopping_list`), not in printarr. Hermes manages it through HA.**

Why:

- Yannic confirmed the list lives in Home Assistant and stays managed by Hermes.
- Assist already writes to a shopping list. Hermes can read and write the same list through HA, and so can the phone app.
- Printarr already prints it: `printarr_print_shopping_list` reads the entity and sends a `shopping` ticket with `delivery: now`.
- A second copy in printarr would drift.

Printing:

- On request: the voice path says "print the shopping list" → HA script → printarr.
- At a time: an HA automation at 17:00, or the arrival trigger for Yannic, calls the same script. The list prints standalone, not on the strip.
- From Hermes: Hermes calls the existing ticket endpoint with the list items read from HA.

Check the HA version first. Newer HA uses the `todo` integration for shopping lists, and Assist's built-in shopping intent may write to the older `shopping_list` integration. Confirm which one Assist writes to before relying on it.

## Google Nest

Short answer: **Nest speakers cannot print, and they are poor at free dictation.** Do not build the voice button on Nest.

What is realistically possible:

| Option | How it works | Pros | Cons |
|---|---|---|---|
| **HA Google Assistant integration (Nabu Casa)** | Exposes HA scripts to Google Home as fixed phrases or routines. | Official. Works with the Nest speakers. | Fixed phrases only. Free text like a message body is not passed through. Needs Nabu Casa or a self-hosted setup. |
| **"Ask Home Assistant" through Google (Nabu Casa)** | Google sends the spoken query to HA Assist. | Could carry free text to HA. | Availability depends on region and account. Check before relying on it. |
| **IFTTT or Google Home routine calling a webhook** | Fixed phrase → webhook → printarr. | Simple. | Fixed phrases only. Cloud in the path. Routines cannot capture a message body. |
| **Nest as a speaker only** | HA plays a reply through the Nest. | Keeps the Nest in use. | Not needed for the printing path. |

Recommendation: **do not depend on Nest** for the first build. Use the satellite for dictation. Use the Nest, if at all, only for fixed phrases such as "print the shopping list", via HA's Google integration. Expose printarr through your domain only if you need a webhook from outside. Keep the intake endpoint on the LAN otherwise.

Open check for Yannic: does your Nabu Casa subscription (or self-hosted setup) enable Google's "Ask Home Assistant"? If yes, the Nest can carry free dictation too, and this section changes.

## Security and privacy

- Audio stays on the LAN when using faster-whisper. The transcript is logged with the ticket, like any other message.
- The API is LAN-only, and that stays the rule. No API key is added for `/intake` or the rest of the API. The API is not exposed to the internet by this project.
- If Yannic later exposes the web UI through his domain, he decides that himself, and puts an authentication portal in front of it. That portal, not an API key, is the control for remote access.
- Messages between the two of you are private. The printed strip is visible to anyone in the room, so a message is printed only on that person's own strip.

## What this needs from the API thread

- A new route `POST /api/v1/intake` with the response and error shape above. This doc is the spec.
- A pure parser module (rules + d1 classifier + fallback) with unit tests, separate from the route.
- A `dry_run` mode the web UI can call to preview how a transcript will be read.

Not built here. Adding the route touches `app/main.py`, which other threads are changing, so it should be scheduled with the API thread.

## Open questions for Yannic

1. Which hardware: Voice Preview Edition (buy), ESP32-S3 (build), or the phone first?
2. One satellite that asks who is speaking, or one per person?
3. Should a message to the other person ever print at once instead of on their next strip? The doc assumes on their next strip.
4. Shopping list: is the HA `todo.shopping_list` the right list, or do you want a separate one for the second person?
5. Is "Ask Home Assistant" available on your Google account, and do you want it at all?
6. Is it OK for the printed message to be the cleaned-up version from Granite, or should it be exactly what was said?

## Related

- [`docs/integrations/home-assistant/README.md`](../integrations/home-assistant/README.md): the existing message and shopping scripts.
- [`docs/integrations/hermes/SKILL.md`](../integrations/hermes/SKILL.md): how Hermes chooses delivery.
- [`docs/design/ha-entities.md`](ha-entities.md): the shopping list entity as it currently stands.
