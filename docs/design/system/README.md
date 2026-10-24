# Receipt design system (draft 0.1)

Built from Yannic's arena results: 261 font duels, 133 ornament duels, 87 template duels, the sizes and pairs rounds. Values are in `tokens.json`. This page explains them. Status: draft, pending the confirmation round (System tab in the arena).

## 1. Pitch and grid

- **Dot pitch: 3 dots per unit.** Each logical pixel is a 2x2 dot square with a 1-dot gap. This is the dot style of the winning 5x7 dot matrix.
- **Grid unit: 3 dots.** Spacing and radii are multiples of it.
- **Ticket: 512 dots wide.** Margin 24 dots (8 units), so the content is 464 dots wide.

Spacing scale (dots): xs 3, s 6, m 12, l 18, xl 24, xxl 36.

## 2. Type roles

Only one typeface is used for the main design: the 5x7 dot matrix, drawn at whole-number scales. Each scale gives a cap height in dots.

| Role | Font | Scale | Cap height | Evidence |
|---|---|---|---|---|
| Display numerals | 5x7 dot matrix | 6 | 42 | Not tested. Chosen as moderate, because big numerals lost in the lab. |
| Headline | 5x7 dot matrix | 4 | 28 | Pair duels used it. Other headline sizes were not tested. |
| Body | 5x7 dot matrix | 3 | 21 | Top font in font pass 1 (7-0). Won the pair pass 7-1. |
| Body, alternative | Inter | cap 20 | 20 | Sizes pass: cap 18 to 22 won. Use for dense text only. |
| Caption | 5x7 dot matrix | 2 | 14 | The minimum text height in the brief. |

Rules:
- Body at cap 21 gives about 25 characters per 464-dot line.
- Sizes 24 and above lost in the sizes pass, so body text stays at 21 or below.
- Bold weight lost, so there is no bold.
- Barlow Condensed, IBM Plex Serif and Source Code Pro lost, so they are not used.

## 3. Strokes and rules

- **Dot line (1 logical pixel):** outlines and every ornament.
- **Solid rule:** 2 dots tall, content width.
- **Dotted rule:** 2-dot squares every 3 dots.
- **Heavy strokes:** not used.

## 4. Radii

- Cards: 12 dots (medium). Corners are cut at the card inset.
- Nothing else is rounded. Pills and full radii are not used.

## 5. Cards and header

- **Card:** outlined only, dot-line stroke, radius 12. No fills, tones or elevation (all lost in the lab).
- **Header:** hello style. Caption, then headline, then the display number. Centred, wordmark, band, boxed and rule headers lost.

## 6. Decoration

- **At most one ornament per card.** Stacking was not tested, so this is a limit I chose.
- Slots: divider under the caption (full width), strip under the caption (replaces the solid rule), icon in the top-right corner (39 dots), stamp in the top-right corner (72 dots), corners inside the card inset.
- The ornament family is in `design-lab/system/assets/ornaments/`. Pieces: dotted rule, perforation, tape ticks, barcode, wave, horizon sun strip, battery, heart, star, house, bell, dog, bone, warning triangle, check circle, stamp, sun, moon, bolt, drop, cloud, coffee, plant, arrow, corner L, card outline. Each is drawn on the 3-dot pitch with the same stroke.

## 7. Colour

1-bit only. Ink black, paper white. No tones, dithering or filled areas.

## 8. Open points

1. The lab renderer (`design-lab/lib/raster.js`, `text()`) draws 5x7 glyphs as solid squares. The arena winner used squares with a 1-dot gap. The spec follows the arena winner. Switching the renderer to the gap style is a one-line change, but it has not been made here.
2. Numerals (42) and the headline size (28) are not tested against other sizes. A numerals and headline round would settle them.
3. The confirmation round compares the system family with the old family, not one piece against another. Results will show in the arena's System tab.
4. The templates result said footers and stars are slightly positive in the taste notes but lost in the template duels. This spec follows the template duels and drops footer and star decoration.

## Licences

Everything here is original work for this project, except Inter (SIL Open Font License 1.1), which appears only in the body_alt role and in the old twin tickets. See `LICENCES.md` in this folder.
