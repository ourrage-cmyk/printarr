# Receipt design renderer (round 2 to 4)

Node.js code (no npm dependencies) that draws the image-based receipt designs as 1-bit bitmaps.
The printarr side only needs a bitmap per ticket (512 dots wide, rows packed MSB first) and the GS ( L raster command.

## Files
- `lib/escpos.js`: ESC/POS byte builder for raster tickets, the 1-bit bitmap helpers (set pixel, line, fill).
- `lib/doc.js`: text layout helper for the earlier text tickets (round 1). The raster designs do not use it.
- `lib/raster.js`: the 5x7 dot-matrix font (drawn here, not a third-party font), icon sprites (sun, moon, bone, battery, bolt, thermometer, cloud, drop, walk, heart, box, tick), dot rings, segmented bars, line graphs, bar charts, dithered fills (Bayer 4x4).
- `lib/designs.js`: sample values (fictional) used by every design, plus the round 1 text designs.
- `lib/round2.js`: round 2 families and the card, tile, pill and gauge helpers.
- `lib/round3.js`: round 3 Material-style families (tonal fills, corner scale, chips, progress).
- `lib/round4.js`: round 4 designs (outlined cards, hello header, segmented bars, energy line, alert pill, rows, compare).
- `scripts/render2.js`, `render3.js`, `render4.js`: build the designs, send each bitmap to a simulator, save PNG and bytes. Set `SIM_URL` to the simulator. Output folders are `renders*`, `designs*` and `data/designs*.json` under the lab root.
- `samples/`: one PNG per design used in the handoff (sample data only).

## Raster ticket, in short
1. Build a bitmap of 512 dots wide and the height of the content.
2. Send `GS ( L` with `48, 112, 48, 1, 1, 49`, width and height as 16-bit little-endian, then the packed rows.
3. Follow with `GS ( L 2 0 48 50` (print buffer), one feed line, and a partial cut.

## Licences
All glyphs, sprites and layout code here were written for this project. No third-party fonts, icons or images are included. The Home Assistant dashboard screenshots and the Nothing and Material guideline pages were used as references only and are not copied.
