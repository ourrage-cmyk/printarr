# Tone language

A tone tells the reader how a ticket feels before they read it. Each tone has one ornament
family and one icon, so the paper says the feeling at a glance. The catalogue is
`app/render/system/blocks.json` (`moods`); `tests/test_tones.py` checks the rules below.

| Tone | Feeling | Header ornament | Icon | Title | Notes |
| --- | --- | --- | --- | --- | --- |
| neutral | plain information | hairline | box | dot matrix | no ornament beyond the rule |
| factual | a number or status | doubleHairline | box | dot matrix | |
| happy | good news | sunStrip | sun | dot matrix | |
| playful | light, fun | dottedWave | star | dot matrix | |
| excited | enthusiasm | sunStrip | star | dot matrix | |
| loving | affection | heart | heart | dot matrix | the only tone with a heart |
| gentle_warning | a soft heads-up | dottedWave (zigzag) | drop | dot matrix | the zigzag is the gentle, cute motif |
| reminder | a time cue | tapeTicks | check | dot matrix | no heart; tape reads as a note to self |
| sad | sympathy | dashedRule | drop | dot matrix | |
| confused | a question | dashedRule | question | dot matrix | |
| upset | a complaint | perforation | warn | dot matrix | |
| firm_complaint | a firm complaint | doubleHairline | warn | dot matrix | |
| urgent | needs attention | barcode border | warn | dot matrix | the barcode border signals urgency |
| critical | needs attention now | barcode border | warn | inverted (white on black) | the only inverted title; super urgent only |

Rules:
- Header, icon and title accent together are unique per tone, so no two tones look the same.
  `urgent` and `critical` share the barcode border and warn icon; only the inverted title tells them apart.
- The inverted (pill) title is used only by `critical`.
- A heart appears only for `loving`.
- Fun facts use the playful tone, not reminders. A fun fact prints its text alone: no "Did you know" heading
  and no "FUN FACT" label is added. The words may appear in the sender's own text.
- Printed tickets never print the tone name.

Outline weight: the card outline also carries the tone. `urgent`, `upset` and `firm_complaint`
draw a heavy (4 dot) square-cornered outline, `critical` the heaviest (5 dots), and soft tones
(`loving`, `gentle_warning`, `playful`, `happy`) draw a rounder corner. The rest use the shell's own
2-dot outline. Each kind of ticket also wears its own mark at the top-right: envelope for a note,
bolt for an alert, clock for a reminder, bulb for a fun fact and cart for a shopping list.

## Mood bands (one per card, at the top)

The band carries the mood; it is drawn once at the top of the card, 28 dots tall, with no second ornament and no mood words. Ink rises with urgency.

| Band | Moods |
| --- | --- |
| none (plain card) | neutral, factual |
| sparse dots | loving, happy |
| zigzag | excited, playful |
| upright ticks | reminder |
| dense stipple | sad, confused |
| diagonal hatch | gentle_warning, upset |
| barcode | firm_complaint, urgent |
| solid black bar (plus inverted title) | critical |

Moods in one family differ by their icon, and by outline weight (firm 3, urgent 4, upset 4, critical 5). The older header/footer table above is superseded for the ornament column.
