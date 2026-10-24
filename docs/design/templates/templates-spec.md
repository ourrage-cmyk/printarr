# Templates spec: round 5 (one design language)

For the API thread. Port these to Python under `docs/design/templates/`. Each template is a 1-bit bitmap, 512 dots wide, sent with the GS ( L raster command (see `docs/design/handoff-image-templates.md`).

Reference renders: `receipt-lab/renders5/B5-001.png` to `B5-029.png`. Source: `receipt-lab/lib/round5.js`, `lib/round2.js`, `lib/raster.js`, `lib/ornaments.js`. Ornament data: `design-system/ornament-sets.json`.

## Design language (all templates)
- **Type:** the 5x7 dot-matrix font, drawn as dot blocks (glyph table in `lib/raster.js`). Headline scale 3 (21 dots tall). Numerals scale 3 to 5. Body and labels scale 2 (14 dots). No scale below 2.
- **Secondary type:** a mono or sans at cap 18 to 22 dots, only where a line needs it. Not used in round 5 mockups.
- **Weight:** light. Body text is not doubled.
- **Cards:** outlined, 2-dot stroke, corner radius 4 or 8 dots, 14-dot inner padding, 10 dots between cards.
- **Header:** a hello header (greeting at scale 3, one summary line) or none.
- **Ornaments:** one set per tone, from `ornament-sets.json`. Header, divider and footer come from the set. The grid and fonts never change.
- **Not used:** bands, rules across the page, boxed headers, centred or wordmark headers, dot/star/footer decorations, filled cards, Font B.
- **Filled pill:** allowed only for one alert label (for example WATER LEAK), with the label cleared to white.

## Templates (29 mockups)
| Family | Tone | Variants | Content |
|---|---|---|---|
| morning | neutral | 3 | Battery and sleep tiles for Yannic and the second person, steps, energy now and next, inside and outside, outdoor 24-hour line graph, dogs, calendar (optional) |
| evening | neutral | 3 | Hello, dogs today, daily summary, missed messages from the other person |
| personal, loving | loving | 2 | Heart header, dotted wave divider, sign-off |
| personal, neutral | neutral | 2 | Hairline header, plain text, sign-off |
| personal, reminder | reminder | 2 | Tape-tick header, dashed divider, sign-off |
| personal, playful | playful | 2 | Sun strip header, tape-tick divider, fun line |
| personal, gentle warning | gentle_warning | 2 | Dotted wave header, calm line |
| personal, firm complaint | firm_complaint | 2 | Perforation header, double hairline, barcode footer. Says the problem and the ask, no insults |
| shopping list | neutral | 2 | Checkbox rows (optional dividers) |
| to-do list | reminder | 2 | Boxes or ticks, with a date or day on the right |
| alert, normal | gentle_warning | 2 | Drop icon, calm line, DOOR SHUT row |
| alert, urgent | urgent | 2 | Barcode header, filled WATER LEAK pill, one action row |
| note, fun fact | playful | 3 | Playful header and divider, fun fact line |

## Tone to ornament table
| Tone | Header | Divider | Footer | Icons | d1 questions |
|---|---|---|---|---|---|
| loving | heart | dotted wave | dashed rule | heart, sun | is_loving, is_positive |
| neutral | hairline | hairline | dashed rule | box | is_neutral |
| reminder | tape ticks | dashed rule | tape ticks | check, box | is_reminder |
| playful | sun strip | tape ticks | dotted wave | star, bolt | is_playful, is_fun_fact |
| gentle_warning | dotted wave | dashed rule | hairline | drop, warn | is_gentle_warning |
| firm_complaint | perforation | double hairline | barcode | warn | is_negative, is_complaint |
| urgent | barcode | perforation | barcode | warn, bolt | is_urgent |

## d1 decision questions
The d1 model is called at `POST http://192.0.2.231:11434/v1/systemone` (see `receipt-lab/notes/d1-model-api.md`). Each question is a 0 to 1 likelihood. For each message, ask all of these in one call, then pick the tone with the highest score above a threshold of 0.5, and fall back to `neutral` when none is above it:

- is_loving: "Does the message express love or warm affection?"
- is_positive: "Is the message positive or grateful?"
- is_neutral: "Is the message a plain, emotionless note?"
- is_reminder: "Is the message a reminder about a task or a time?"
- is_playful: "Is the message light-hearted or joking?"
- is_fun_fact: "Does the message share a fun fact?"
- is_gentle_warning: "Is the message a calm heads-up about something to check?"
- is_negative: "Is the message negative or critical?"
- is_complaint: "Does the message complain about something and ask for a change?"
- is_urgent: "Does the message need action right away?"
- is_alert: "Is the message an alert about the home, such as a leak, smoke, a door or an appliance?"
- is_list: "Is the message a list of items?"
- is_briefing: "Is the message a summary of the day or a briefing?"
- is_evening: "Is this message meant for the evening?"

Questions are independent. A message can score as both loving and negative. Keep the highest tone and the next one as a fallback.

## Data fields
- Morning and evening: body battery (`sensor.body_battery_most_recent` and `_2`), sleep score (`sensor.sleep_score` and `_2`), steps, energy rates, indoor and outdoor temperature, dog counters, calendar (optional, print "NONE SET" when absent).
- Personal messages: the message text (ASCII only), sign-off name, tone.
- Lists: items from `todo.shopping_list` or the note text. Print "LIST EMPTY" when there are none.
- Alerts: alert text, the trigger value, and an action line. Urgent alerts use the urgent set.
- Use "NO DATA" in place of any missing value, so the layout stays fixed.

## Port notes
- The glyph table is 5x7 bitmaps, one string per row, `#` for a dot. Copy it from `lib/raster.js`.
- Dithered tints use a Bayer 4x4 matrix. Only empty pixels get the tint, so text and strokes stay solid.
- Ornament drawers are in `lib/ornaments.js`. Each one takes an x range and a y and returns the height it used.
- Sprites are 9-pixel grids drawn at 3 dots per pixel, in `lib/raster.js` (`SPRITES`).
- The bitmap uses 1 for black and rows packed MSB first. The raster command width is in bytes times 8 (512 dots).
