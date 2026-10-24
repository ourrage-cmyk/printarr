# Conformance: what the printed tickets must match

This page lists the design choices the printed tickets are checked against, where each comes from, and what is still open.
The arena and lab results that drove the choices are in the design folder. The current source of truth is the code:
`app/render/system/blocks.json` (grid, shell, moods) and `app/render/strips.py` (sizes and per-mood outlines).

## 1. Fonts

| Role | Font | Where |
|---|---|---|
| Titles and headlines | 5x7 dot matrix, centred | native glyph table in `app/render/glyphs.py` (no file) |
| Body, labels, numbers | 5x7 solid, body scale 3 (cap 21 dots) | `BODY = 3` in `app/render/strips.py` |
| Captions | scale 2 (cap 14 dots), the minimum | `CAPTION = 2` |

- The dot-matrix font is used for titles only. Body text and numbers use the solid font.
- Inter (`app/render/fonts/Inter.ttf`, SIL Open Font License 1.1) is in the repo as the alternative for dense text. The renderer does not use it yet.
- The licence text is in `app/render/fonts/OFL.txt`.

## 2. Tiles, rules and spacing

| Item | Value | Where |
|---|---|---|
| Layout | three-column grid, one tile per block, tiles pack together | `blocks.json` (`grid`, `grid_rules`) |
| Tile outline | 2 dots by default, heavier for some moods (see tones) | `STROKE`, `STROKE_BY_MOOD` |
| Tile corner | 4 dots by default; soft moods round (8 to 12), heavy moods square (2) | `RADIUS`, `RADIUS_BY_MOOD` |
| Mood band | one band across the top of a tile, 28 dots tall | `BAND_H` in `app/render/strips.py` |
| Kind mark | one per block type that has one, top-right corner | `KIND_MARKS` |
| Ticket edges | no blank is drawn at the top or bottom of a composed ticket (`TICKET_MARGIN = 0`) | `app/compose.py` |
| Cut | the feed before the cut is sent with the partial-cut command, never drawn into the picture | `CUT_FEED` in `app/escpos.py` |

The strip margins are Yannic's rule and are not in the design tokens.

## 3. Moods, ornaments and icons

The mood catalogue and what each mood looks like are in [`tones.md`](tones.md). The icons come from the
26 system pieces in `app/render/system/ornaments/`, or from drawings in code where a piece is missing.
The "question" icon for `confused` has not been voted on in an arena.

## 4. Taste rules (from the lab ratings)

From the taste guide and the taste profile. Mean score, +1 like and -1 dislike.

| Choice | Result | Count |
|---|---|---|
| Outlined card | +0.83 | 36 |
| Hello header | +0.92 | 24 |
| Rows with dot leaders | +0.67 | 24 |
| Segmented bars | +0.86 | 14 |
| Filled card | -0.88 | 16 |
| Elevated card | -1.00 | 8 |
| Text-only sparkline | -1.00 | 10 |
| Big numerals | -0.75 | 8 |
| Frame decoration | -0.41 | 17 |

Yannic's later rules that are not in the lab data: no stars, no footers, no filled cards, no salutations such as "Hello love",
dog counts in words ("3 PEE", not codes), and no repeated content on one ticket.

## 5. Status against the earlier checks

Checked against the code on main on 2026-10-24. Earlier mismatches that are now fixed:

- Body size: body is scale 3, cap 21, as the font arena's tier B chose.
- Dog counts: printed as words, not letter codes.
- Ornament source: the system pieces are used where one exists. Names without a piece keep their drawing in code.
- Card corners and outlines: set per mood, as in the table above.

## 6. Open items

1. **Dot style.** The tokens ask for 2 by 2 dot squares on a 3-dot pitch for outlines and rules. This was not re-checked after the tile redesign, so check it on the paper.
2. **Rules.** Solid and dotted rules are not re-checked. Check them on the paper.
3. **Printer dpi.** The tokens use 203 dpi, and the printer runs at 180 dpi. Confirm which one the margins use.
4. **Numerals.** Display numerals are not arena-tested. Check the size on the paper.
5. **Alert barcode and top margin.** Check on the real paper when the printer arrives.
6. **Grayscale.** Unverified. CJK and emoji are unsupported.

## 7. Where the numbers come from

- Arena and lab results: the design folder (`docs/design/`) and the taste guide.
- Tokens: `docs/design/system/tokens.json`, and the copy on main at `app/render/system/tokens.json`.
- Mood catalogue and grid: `app/render/system/blocks.json`.
