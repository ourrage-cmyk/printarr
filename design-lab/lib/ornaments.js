'use strict';
// Ornaments for round 5, drawn on the same dot pitch as the rest of the system (1 dot = 1 px at 512 wide).
// Names follow the arena: barcode, sun strip, dotted wave, heart, tape ticks, perforation, dashed rule.
const { setPx, fillRect } = require('./escpos');
const { SPRITES } = require('./raster');

const drawers = {
  // Barcode: vertical bars of varying width.
  barcode(c, x0, x1, y, h = 10) {
    const widths = [2, 1, 3, 1, 1, 2, 4, 1, 2, 1, 3, 2, 1, 1, 2, 3, 1, 2];
    let x = x0;
    let i = 0;
    while (x < x1) {
      const w = widths[i++ % widths.length];
      fillRect(c.bm, x, y, w, h);
      x += w + 2;
    }
    return h;
  },
  // Sun strip: a horizon line with a dotted half-sun above it.
  sunStrip(c, x0, x1, y) {
    const cx = Math.floor((x0 + x1) / 2);
    for (let a = 180; a <= 360; a += 4) {
      const rad = (a * Math.PI) / 180;
      fillRect(c.bm, Math.round(cx + Math.cos(rad) * 16) - 1, Math.round(y + 16 + Math.sin(rad) * 16) - 1, 3, 3);
    }
    fillRect(c.bm, x0, y + 16, x1 - x0, 2);
    return 18;
  },
  // Dotted wave: a sine of single dots.
  dottedWave(c, x0, x1, y, amp = 3) {
    for (let x = x0; x < x1; x += 3) setPx(c.bm, x, Math.round(y + amp + Math.sin((x - x0) / 6) * amp));
    return amp * 2 + 2;
  },
  // Heart sprite, centred in the strip.
  heart(c, x0, x1, y) {
    const w = SPRITES.heart[0].length * 3;
    c.sprite(Math.floor((x0 + x1 - w) / 2), y, 'heart', 3);
    return 18;
  },
  // Tape measure ticks: a rule with ticks every 8 dots and longer ones every 40.
  tapeTicks(c, x0, x1, y) {
    fillRect(c.bm, x0, y, x1 - x0, 1);
    for (let x = x0, i = 0; x <= x1; x += 8, i++) fillRect(c.bm, x, y, 1, i % 5 === 0 ? 8 : 4);
    return 9;
  },
  // Perforation: dashes of 6 dots with gaps of 4.
  perforation(c, x0, x1, y) {
    for (let x = x0; x < x1; x += 10) fillRect(c.bm, x, y, 6, 2);
    return 2;
  },
  // Dashed rule.
  dashedRule(c, x0, x1, y) {
    for (let x = x0; x < x1; x += 8) fillRect(c.bm, x, y, 4, 1);
    return 1;
  },
  // Hairline: one dot-thin line.
  hairline(c, x0, x1, y) {
    fillRect(c.bm, x0, y, x1 - x0, 1);
    return 1;
  },
  // Double hairline.
  doubleHairline(c, x0, x1, y) {
    fillRect(c.bm, x0, y, x1 - x0, 1);
    fillRect(c.bm, x0, y + 3, x1 - x0, 1);
    return 4;
  },
  // Warning triangle sprite.
  warn(c, x0, _x1, y) {
    c.sprite(x0, y, 'warn', 3);
    return 24;
  },
};

// Sprites used by the ornament sets (drawn on the same 3-dot pitch as the icons).
const EXTRA_SPRITES = {
  warn: ['....#....', '...###...', '...###...', '..##.##..', '..##.##..', '.##...##.', '.##...##.', '#########', '.........'],
  star: ['....#....', '....#....', '#########', '.#######.', '..#####..', '.##.#.##.', '##.....##', '.........', '.........'],
  check: ['........#', '.......##', '#.....##.', '##...##..', '.##.##...', '..###....', '...#.....'],
};
Object.assign(SPRITES, EXTRA_SPRITES);

module.exports = { drawers };
