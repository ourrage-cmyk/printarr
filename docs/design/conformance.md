# Conformance: what the printed receipts must match

This page sets out the choices the arena and the taste ratings made, and checks the renderer against them. Every value has its source: a leaderboard, a vote count, a lab rating, or the system tokens on main (`docs/design/system/tokens.json`). Numbers come from the data files on 2026-10-24 (leaderboards generated 00:55 to 01:01 UTC, 847 duels in total).

Scope: the **winners** and the **token values**. Where the two disagree, both are shown and flagged. Where the renderer disagrees with either, that is listed under Mismatches.

## 1. Fonts

Font files the renderer needs:

| Role | Font | File | Licence |
|---|---|---|---|
| Headline, body, label, value, numerals, caption | 5x7 dot matrix | native glyph table in `app/render/glyphs.py` (no file) | Original work for this project |
| Body alternative (dense or long text only) | Inter | `app/render/fonts/Inter.ttf` (added on this branch) | SIL Open Font License 1.1 |

The 5x7 dot matrix is not a font file. It is a glyph table drawn for this project, so it needs no licence file. Inter is the only third-party font the tokens name. Its file is added here. The OFL text itself (`OFL.txt`) is not in the repo yet, so the licence is referenced in `app/render/fonts/LICENSE.md`, and the full text needs adding before a public release.

### Font choice
- **Font arena, winner:** Dot matrix 5x7 **B**, Elo 1647, 7-0. Next: IBM Plex Mono B (1637, 6-0), Chivo Mono B (1600, 5-1).
- **Pair arena, winner:** 5x7 headline + 5x7 dot matrix body, Elo 1723, 39-8. Next: 5x7 headline + IBM Plex Mono (1658, 33-19).
- **Tier:** tier B won. Tier B means body cap 20, headline 30, numerals 56 (`arena/build/build_assets.py`, `TIERS`). Tier A (body 14, headline 22, numerals 40) lost.
- **Tokens (main):** body alternative is Inter, cap 20, for dense or long text only. Not used for headlines or numerals.
- **Avoid (tokens):** Barlow Condensed, IBM Plex Serif, Source Code Pro. They lost in the pair or font arena.

### Font sizes (per role)
| Role | Scale | Cap height (dots) | Source |
|---|---|---|---|
| Headline | 4 | 28 | Tokens. Pair arena used this size against all top body fonts (5x7 headline won 7 of 8 pair duels). Headline size against other sizes was not tested. |
| Body | 3 | 21 | Tokens. Font arena tier B (cap 20 to 21). |
| Label | 3 | 21 | Tokens, upper case. |
| Caption | 2 | 14 | Tokens, minimum only. |
| Display numerals | 6 | 42 | Tokens. **Not arena-tested** (`tested: false`). |

**Conflict to decide:** the size arena ranks the dot matrix body at cap 14 above cap 21 (Elo 1572 at 3-0 against 1545, which has fewer games). The tokens chose cap 21 from the font arena, not the size arena. Both are small samples. Decide cap 14 or cap 21 for body, and test it in the arena.

### Dot style
- Winning dot style, from tokens: one ink pixel is a **2 x 2 dot square** on a **3-dot pitch**, with a 1-dot gap. Every outline and ornament uses this dot line.
- The renderer draws solid blocks, so the dot matrix look is lost. This is the largest visual mismatch.

## 2. Cards, rules and spacing

| Item | Winner or token | Source |
|---|---|---|
| Card | outlined, no fill, no elevation, light weight | Tokens. Outlined 84% and outline 78% in the templates pass. Light 63% against bold 38%. |
| Card radius | 12 dots | Tokens (`radius.card`). |
| Card stroke | dot line (2-dot squares on the 3-dot pitch) | Tokens. |
| Solid rule | 2 dots tall, full content width | Tokens (`stroke.rule_solid`). |
| Dotted rule | 2-dot squares every 3 dots | Tokens (`stroke.rule_dotted`). |
| Heavy frames | not used | Tokens. Heavy frames lost in the lab. |
| Ticket margin | 24 dots, content width 464 | Tokens (`ticket`). |
| Card inset and padding | 12 dots | Tokens (`ticket.card_inset`, `card_padding`). |
| Grid unit | 3 dots, spacing xs 3, s 6, m 12, l 18, xl 24, xxl 36 | Tokens (`grid`). |
| Strip margins | None in the picture. The blank before the cut (about 90 dots, half an inch) is fed with the cut command (4 lines), once at the end of the whole piece | Yannic's rule (2026-10-24): a strip, a continuation or a queued ticket carries no blank of its own. Confirm the real line height on the printer Monday. |

Winning template patterns (`leaderboard-templates.json`, 118 duels):
- **morning v1**, Elo 1688, 15-2: hello header, morning, radius 4, dense, light, outlined. This is the best-ranked template.
- **morning v3**, Elo 1634, 12-3: hello header, airy, light, outlined.
- **alert normal v2**, Elo 1593, 10-5: alert, airy, light, outlined, radius 8.
- **personal loving v2**, Elo 1583, 11-6.
- **alert normal v1**, Elo 1552, 7-6: alert, dense.
- **personal gentle warning v2**, Elo 1544, 7-6.

Density: airy 53% against dense 47% (`attributes`, 60 head-to-head duels). Treat as even.

**Conflict to decide:** the top template (morning v1) uses radius 4, but the tokens set the card radius at 12. The lab also preferred radius-4 cards in the outline pass. Decide between 4 and 12.

Hello header wins 87% (26-4) in the template arena and is the most preferred header in the lab taste profile.

## 3. Ornaments

Ornament arena, 187 duels, 90 pieces. Winners by rank:

| Rank | Ornament | Elo | W-L | Used by |
|---|---|---|---|---|
| 1 | Barcode decor | 1724 | 14-1 | urgent (header and footer) |
| 2 | Horizon sun strip | 1687 | 13-2 | happy, excited, playful |
| 3 | Dotted wave | 1641 | 10-3 | sad, gentle warning (header and footer) |
| 4 | Heart | 1630 | 12-5 | loving |
| 5 | Tape measure ticks | 1586 | 7-4 | reminder |
| 11 | Perforation | 1535 | 4-4 | firm complaint, upset |
| 14 | Warning triangle | 1530 | 3-2 | warning icon |
| 16 | Hairline and double hairline | 1528 | ties | neutral, factual, double rule |
| 22 | Outline, rounded 12 | 1524 | 2-1 | card outline (see radius conflict) |
| 37 | Bullet, box | 1521 | ties | checklist |
| 64 | Dashed outline | 1476 | ties | confused (dashed rule) |
| 71 | Water drop | 1473 | ties | sad and gentle warning icon |
| 80 | Outline, pill | 1431 | 0-3 | pill (lost) |

Notes:
- Ornaments with 3 or fewer games have wide error. The top five have 11 to 17 games each, so they are the most reliable.
- The tokens say one decoration per card, in one of these slots: divider, strip, icon (top right corner, 39 dots), stamp (top right, 72 dots), or corner. Max 1 per card.
- The 26 system ornament pieces live in `app/render/system/ornaments/` (PNG, `orn-sys-*`). The renderer draws its own versions in code and does not use them.

Icons (from the arena and the lab): warning (14), drop (71), heart (4), sun (sun strip, 2), star (29), box (37). **The "question" icon is not in the arena.** The confused mood uses it, so the choice is unvoted.

## 4. Taste rules (from 180 lab ratings)

From `docs/design/taste-guide` and `notes/taste-profile.md`. Mean score, +1 like and -1 dislike.

| Choice | Result | Count |
|---|---|---|
| Outlined card | +0.83 | 36 |
| Hello header | +0.92 | 24 |
| Rows (dot leaders) | +0.67 | 24 |
| Segmented bars | +0.86 | 14 |
| Server modules | +1.00 | 5 |
| Filled card | -0.88 | 16 |
| Elevated card | -1.00 | 8 |
| Text-only sparkline | -1.00 | 10 |
| Big numerals | -0.75 | 8 |
| Frame decoration | -0.41 | 17 |
| Font B (printer) | -0.62 | 26 |
| Morning and evening | +0.10 and +0.24 | 69 and 63 |

## 5. Mismatches: the renderer against the winners

Checked against `app/render/strips.py` on `design-blocks` (not yet on main) and `app/render/system/tokens.json` on main.

| # | Item | Winner or token | Renderer | Severity |
|---|---|---|---|---|
| 1 | Dot style | 2x2 dot squares on a 3-dot pitch | solid blocks | High. The dot matrix look is lost. |
| 2 | Body size | scale 3, cap 21 (or 14, see conflict) | scale 2, cap 14 | High. Printed text is too small. |
| 3 | Headline size | scale 4, cap 28 | scale 3, cap 21 | High. |
| 4 | Numerals | scale 6, cap 42 | scale 3 (metric value) | High. Numerals are too small. |
| 5 | Card radius | 12 (or 4 by the top template) | 4 | Medium. Decide first. |
| 6 | Card stroke | dot line | solid 2-dot line | Medium. |
| 7 | Rules | solid 2 dots, dotted 2-dot squares every 3 | 1-dot hairline | Medium. |
| 8 | Grid | 3-dot unit, spacing 3 to 36 | 40-dot unit, gap 10 | Medium. A different system. |
| 9 | Ticket margin | 24 dots, card inset 12, padding 12 | strip margins 90, pad 14 | Medium. The strip margin is Yannic's rule, so it may stay. Padding should be 12. |
| 10 | Ornament source | 26 system pieces (`orn-sys-*`) | ornaments drawn in code | Medium. Use the system pieces. |
| 11 | Decoration slots | one per card, divider, strip, icon, stamp, corner | up to two (header and divider) | Medium. Keep one. |
| 12 | Icon placement | top right corner of card (39 dots) | inline before each row | Low. |
| 13 | Greeting header | caption, headline, display numeral | headline and summary | Low. |
| 14 | Body alternative | Inter cap 20 for dense text | not supported | Low. Font file now in repo. |
| 15 | Confused icon | not voted | question mark sprite | Low. Vote it. |
| 16 | Dog counts | "P5 O1 F2 R0" is unreadable (findings v1) | letter codes | High. Replace with words or icons. |
| 17 | Metric rows | checkbox squares read as checklist (findings v1) | box icon bullets | Low. Taste call. |

Things the renderer already gets right: the mood map (ornaments and icons, except items 15 and 17 above), outlined cards with light type, black on white only, no fills, and the avoided fonts (none used).

## 6. Decisions needed

1. Body size: cap 14 or cap 21.
2. Card radius: 4 or 12.
3. Dog counts: words, icons, or keep codes (findings v1, question 1).
4. Confirm the printer dpi (180 or 203) for margins.

## 7. Where the numbers come from

- Arena leaderboards: `arena/data/leaderboard-*.json`, rebuilt from `arena/data/votes.json`.
- Lab ratings and the taste guide: `GUIDE/taste-guide.html`, built by `GUIDE/build_guide.js`.
- Tokens: `docs/design/system/tokens.json` (main) and `app/render/system/tokens.json`.
