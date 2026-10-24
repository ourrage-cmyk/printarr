# Mood and tone language

A mood tells the reader how a tile feels before they read it. The mood is set on each block. The catalogue is
`app/render/system/blocks.json` (`moods`), and `tests/test_tones.py` covers the catalogue.

A tone is the ticket-level setting (`tone` on a ticket). Printed tickets never print the tone name or the mood name.

## Moods

Each mood has one band across the top of its card, one icon, and an outline. The band is drawn once, 28 dots tall,
with no second ornament and no mood word. Ink rises with urgency.

| Mood | Band | Icon | Outline |
| --- | --- | --- | --- |
| neutral | none (plain card) | box | standard |
| factual | none (plain card) | thermometer | standard |
| happy | sparse dots | sun | rounder corner |
| loving | sparse dots | heart | rounder corner (the only mood with a heart) |
| excited | zigzag | star | standard |
| playful | zigzag | bone | rounder corner |
| reminder | upright ticks | clock | standard |
| sad | dense stipple | drop | standard |
| confused | dense stipple | question | standard |
| gentle_warning | diagonal hatch | cloud | rounder corner |
| upset | diagonal hatch | warning | heavy square outline |
| firm_complaint | blocks | warning | heavy outline (3 dots) |
| urgent | barcode | warning | heavy square outline |
| critical | solid black bar | warning | heaviest outline (5 dots) |

Rules:
- The band carries the mood. Moods in one family (for example upset and gentle_warning) differ by their icon and outline.
- The inverted title (white on black) is used only by `critical`, so it is the one mood that reads as urgent before the words.
- A heart appears only for `loving`.
- Fun facts use the `playful` mood, not `reminder`. They are printed without a label such as "Did you know" or "Fun fact" above them.
  The fact stands alone, and a reminder or note never carries one. The words "Did you know" are not forbidden inside a sentence.

## Kind marks

Five block types wear a small mark at the top-right corner of their card. The mark follows the block, not the ticket's `kind`:

| Block | Mark |
| --- | --- |
| `message` (a note from a person) | envelope |
| `alert` | bolt |
| `tip` (a reminder) | clock |
| `fact` | bulb |
| `checklist` (a shopping or to-do list) | cart |

## Tones

Tones (`tone` on a ticket) set the ticket's default feel: `loving`, `neutral`, `reminder`, `playful`, `gentle`, `firm`, `urgent`.
A block's own mood still decides its band, icon and outline.

## Outlines and corners

The outline follows the mood. `urgent`, `upset` and `firm_complaint` draw a heavy square outline, `critical` the heaviest.
The soft moods (`loving`, `gentle_warning`, `playful`, `happy`) draw rounder corners. The rest use the standard two-dot outline.

## Where the numbers come from

The mood catalogue is the source of truth. It is in `app/render/system/blocks.json`, and the renderer reads it at start-up.
The stroke and corner values for each mood are in `app/render/strips.py` (`STROKE_BY_MOOD`, `RADIUS_BY_MOOD`).
