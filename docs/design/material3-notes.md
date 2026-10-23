# Material 3 notes for the receipt designs

Source: https://m3.material.io/ (read in the built-in browser, 2026-10-23). Pages: shape overview, corner radius scale, type scale tokens, color roles, cards guidelines, chips guidelines, progress indicators guidelines, elevation overview.

## Shape (corner radius scale)
- Ten steps: none 0, extra small 4, small 8, medium 12, large 16, large increased 20, extra large 28, extra large increased 32, extra extra large 48, full (fully rounded).
- Components map to a step. Buttons and chips are full. Cards use medium to large. Information-dense cards should not use large or full corners, because the corners clip content.
- Inner corners: asymmetric shapes for items grouped closely together (menus, split buttons).
- Shape can be cut instead of rounded. Add padding so content is not clipped.

**Translated to 1-bit:** radii in dots at 180 dpi: 4, 8, 12, 16, 20, 28 and full (half the height). Use the small radii for dense data and the large radii for hero cards.

## Typography
- One scale: display, headline, title, body, label, each in large, medium and small sizes. Baseline and emphasized sets. Emphasized is heavier and used for selection, actions and headlines.
- Brand typeface for large styles (display, headline), plain typeface for body and label.

**Translated:** display = 6x dot scale, headline = 4x, title = 3x, body = 2x, label = 2x in uppercase with letter spacing (a blank column between glyphs). Emphasized = the same glyphs drawn twice, 1 dot apart.

## Color and tone
- Surface roles are the background levels. Container roles are fills for elements. Variants are lower-emphasis versions.
- Tonal elevation: surfaces at higher elevation are lighter or darker by tone, not by shadow.

**Translated:** three tonal levels using a Bayer dither: low (about 6%), mid (about 14%), high (about 25%). No shadows, following the brand reference's rule against shadows on graphics.

## Cards
- Three variants: elevated (tone plus separation), filled (subtle tone), outlined (boundary line).
- Card size comes from its content. Use content blocks, with clear hierarchy between blocks.
- Do not force content into a card when spacing or dividers would work better.

**Translated:** filled = dither tint, outlined = stroke, elevated = mid tint plus a second stroke offset by 3 dots.

## Chips
- Assist, filter, input and suggestion chips. They appear as a set, never alone.
- Filter chips have a selected state. Selected = filled pill, unselected = outlined pill.
- Chips are for choices, buttons are for steps.

**Translated:** filter-chip rows for Bridget and Kida, and for day-part choice (morning, afternoon, evening).

## Progress indicators
- Short waits use a loading indicator. Long waits use a progress indicator.
- Linear for the edge of a container, circular for the centre of an element.
- One group gets one indicator, not one per item.
- Determinate (known progress) and indeterminate (unknown).

**Translated:** linear bar = segmented fill with a dotted track. Circular = dot ring, as in round 2, now used as a set of three.

## Lists
- A list item has a leading icon, a headline, supporting text and a trailing value.

**Translated:** icon sprite, label line, small value line, with a hairline divider.

## Icons
- Rounded, 24 dp grid. Used beside the label, never alone for data.

**Translated:** 9-dot sprites (sun, moon, bolt, drop, walk and others) drawn at 3 dots per sprite pixel.

## Rules carried into round 3
1. Corner radius from the 10-step scale, chosen by how dense the content is.
2. Type hierarchy from the scale: display, headline, title, body, label. One emphasized style per block.
3. Tonal levels, not shadows.
4. Chips as sets, buttons only for steps.
5. Progress as a group indicator.
6. Keep the Nothing grid (2 to 10 columns, margins), and keep the HA dashboard tiles.
