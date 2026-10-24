'use strict';
// Round 2 raster toolkit. Each ticket is drawn as one 512-dot-wide 1-bit bitmap, then sent as GS ( L.
// Dot-matrix 5x7 font, icon sprites, dot rings, dithered fills and charts. Nothing is anti-aliased.
const { bitmap, setPx, drawLine, fillRect } = require('./escpos');

const W = 512;
const MAX_H = 2400;

// 5x7 dot-matrix glyphs. '#' is a dot, '.' is blank. Lowercase maps to uppercase.
const GLYPHS = {
  A: ['.###.', '#...#', '#...#', '#####', '#...#', '#...#', '#...#'],
  B: ['####.', '#...#', '#...#', '####.', '#...#', '#...#', '####.'],
  C: ['.###.', '#...#', '#....', '#....', '#....', '#...#', '.###.'],
  D: ['####.', '#...#', '#...#', '#...#', '#...#', '#...#', '####.'],
  E: ['#####', '#....', '#....', '####.', '#....', '#....', '#####'],
  F: ['#####', '#....', '#....', '####.', '#....', '#....', '#....'],
  G: ['.###.', '#...#', '#....', '#.###', '#...#', '#...#', '.####'],
  H: ['#...#', '#...#', '#...#', '#####', '#...#', '#...#', '#...#'],
  I: ['.###.', '..#..', '..#..', '..#..', '..#..', '..#..', '.###.'],
  J: ['..###', '...#.', '...#.', '...#.', '...#.', '#..#.', '.##..'],
  K: ['#...#', '#..#.', '#.#..', '##...', '#.#..', '#..#.', '#...#'],
  L: ['#....', '#....', '#....', '#....', '#....', '#....', '#####'],
  M: ['#...#', '##.##', '#.#.#', '#.#.#', '#...#', '#...#', '#...#'],
  N: ['#...#', '#...#', '##..#', '#.#.#', '#..##', '#...#', '#...#'],
  O: ['.###.', '#...#', '#...#', '#...#', '#...#', '#...#', '.###.'],
  P: ['####.', '#...#', '#...#', '####.', '#....', '#....', '#....'],
  Q: ['.###.', '#...#', '#...#', '#...#', '#.#.#', '#..#.', '.##.#'],
  R: ['####.', '#...#', '#...#', '####.', '#.#..', '#..#.', '#...#'],
  S: ['.####', '#....', '#....', '.###.', '....#', '....#', '####.'],
  T: ['#####', '..#..', '..#..', '..#..', '..#..', '..#..', '..#..'],
  U: ['#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '.###.'],
  V: ['#...#', '#...#', '#...#', '#...#', '#...#', '.#.#.', '..#..'],
  W: ['#...#', '#...#', '#...#', '#.#.#', '#.#.#', '##.##', '#...#'],
  X: ['#...#', '#...#', '.#.#.', '..#..', '.#.#.', '#...#', '#...#'],
  Y: ['#...#', '#...#', '.#.#.', '..#..', '..#..', '..#..', '..#..'],
  Z: ['#####', '....#', '...#.', '..#..', '.#...', '#....', '#####'],
  0: ['.###.', '#...#', '#..##', '#.#.#', '##..#', '#...#', '.###.'],
  1: ['..#..', '.##..', '..#..', '..#..', '..#..', '..#..', '.###.'],
  2: ['.###.', '#...#', '....#', '...#.', '..#..', '.#...', '#####'],
  3: ['#####', '...#.', '..#..', '...#.', '....#', '#...#', '.###.'],
  4: ['...#.', '..##.', '.#.#.', '#..#.', '#####', '...#.', '...#.'],
  5: ['#####', '#....', '####.', '....#', '....#', '#...#', '.###.'],
  6: ['..##.', '.#...', '#....', '####.', '#...#', '#...#', '.###.'],
  7: ['#####', '....#', '...#.', '..#..', '.#...', '.#...', '.#...'],
  8: ['.###.', '#...#', '#...#', '.###.', '#...#', '#...#', '.###.'],
  9: ['.###.', '#...#', '#...#', '.####', '....#', '...#.', '.##..'],
  '.': ['.....', '.....', '.....', '.....', '.....', '.##..', '.##..'],
  ',': ['.....', '.....', '.....', '.....', '.##..', '..#..', '.#...'],
  ':': ['.....', '.##..', '.##..', '.....', '.##..', '.##..', '.....'],
  '-': ['.....', '.....', '.....', '#####', '.....', '.....', '.....'],
  '+': ['.....', '..#..', '..#..', '#####', '..#..', '..#..', '.....'],
  '/': ['....#', '...#.', '...#.', '..#..', '.#...', '.#...', '#....'],
  '%': ['##..#', '##.#.', '...#.', '..#..', '.#...', '.#.##', '#..##'],
  '(': ['...#.', '..#..', '.#...', '.#...', '.#...', '..#..', '...#.'],
  ')': ['.#...', '..#..', '...#.', '...#.', '...#.', '..#..', '.#...'],
  '!': ['..#..', '..#..', '..#..', '..#..', '..#..', '.....', '..#..'],
  '?': ['.###.', '#...#', '....#', '...#.', '..#..', '.....', '..#..'],
  "'": ['..#..', '..#..', '.....', '.....', '.....', '.....', '.....'],
  ' ': ['.....', '.....', '.....', '.....', '.....', '.....', '.....'],
};

function glyph(ch) {
  return GLYPHS[ch.toUpperCase()] || GLYPHS['?'];
}

function textWidth(str, scale) {
  return str.length * 6 * scale - scale;
}

class Canvas {
  constructor() {
    this.bm = bitmap(W, MAX_H);
    this.y = 0;
  }

  // Dot-matrix text at scale (each glyph dot is scale x scale).
  text(x, y, str, scale = 2) {
    let cx = x;
    for (const ch of str) {
      const g = glyph(ch);
      for (let r = 0; r < 7; r++) {
        for (let c = 0; c < 5; c++) {
          if (g[r][c] === '#') fillRect(this.bm, cx + c * scale, y + r * scale, scale, scale);
        }
      }
      cx += 6 * scale;
    }
    return cx - x;
  }

  // Text centred in a box from x0 to x1.
  textIn(x0, x1, y, str, scale = 2) {
    this.text(x0 + Math.floor((x1 - x0 - textWidth(str, scale)) / 2), y, str, scale);
  }

  textRight(x1, y, str, scale = 2) {
    this.text(x1 - textWidth(str, scale), y, str, scale);
  }

  // Sets or clears a rectangle outline. Used for borders and rules.
  hline(x0, x1, y, t = 1) {
    fillRect(this.bm, x0, y, x1 - x0, t);
  }

  vline(x, y0, y1, t = 1) {
    fillRect(this.bm, x, y0, t, y1 - y0);
  }

  // Rounded box outline between (x0, y0) and (x1, y1). Corner radius r, stroke t.
  roundBox(x0, y0, x1, y1, r = 10, t = 2) {
    this.hline(x0 + r, x1 - r, y0, t);
    this.hline(x0 + r, x1 - r, y1 - t, t);
    this.vline(x0, y0 + r, y1 - r, t);
    this.vline(x1 - t, y0 + r, y1 - r, t);
    for (let a = 0; a <= 90; a += 2) {
      const rad = (a * Math.PI) / 180;
      const dx = Math.round(Math.cos(rad) * r);
      const dy = Math.round(Math.sin(rad) * r);
      // Corner arcs, drawn as t x t dots.
      fillRect(this.bm, x0 + r - dx, y0 + r - dy, t, t);
      fillRect(this.bm, x1 - r + dx - t + 1, y0 + r - dy, t, t);
      fillRect(this.bm, x0 + r - dx, y1 - r + dy - t + 1, t, t);
      fillRect(this.bm, x1 - r + dx - t + 1, y1 - r + dy - t + 1, t, t);
    }
  }

  fill(x0, y0, x1, y1) {
    fillRect(this.bm, x0, y0, x1 - x0, y1 - y0);
  }

  // Dithered fill with a Bayer 4x4 threshold. level 0..1 gives a tone, so no grey is needed.
  dither(x0, y0, x1, y1, level) {
    const B = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        if ((B[y & 3][x & 3] + 0.5) / 16 < level) setPx(this.bm, x, y);
      }
    }
  }

  // Grid of single dots: the dot-matrix background.
  dotGrid(x0, y0, x1, y1, step = 8) {
    for (let y = y0; y < y1; y += step) for (let x = x0; x < x1; x += step) setPx(this.bm, x, y);
  }

  dots(x, y, size = 2) {
    fillRect(this.bm, x, y, size, size);
  }

  // Icon sprite, drawn with scale dots per sprite pixel.
  sprite(x, y, name, scale = 3) {
    const rows = SPRITES[name];
    rows.forEach((row, r) => {
      for (let c = 0; c < row.length; c++) {
        if (row[c] === '#') fillRect(this.bm, x + c * scale, y + r * scale, scale, scale);
      }
    });
    return { w: rows[0].length * scale, h: rows.length * scale };
  }

  // Ring of dots: filled arc for the fraction, hollow dots for the rest.
  dotRing(cx, cy, r, fraction, dot = 4) {
    const steps = 120;
    for (let i = 0; i < steps; i++) {
      const a = -Math.PI / 2 + (i / steps) * Math.PI * 2;
      const x = Math.round(cx + Math.cos(a) * r);
      const y = Math.round(cy + Math.sin(a) * r);
      if (i / steps <= fraction) fillRect(this.bm, x - dot / 2, y - dot / 2, dot, dot);
      else setPx(this.bm, x, y);
    }
  }

  // Filled segmented bar. Segments are solid, or dotted when empty.
  segBar(x0, x1, y, h, fraction, segs = 10) {
    const gap = 4;
    const seg = Math.floor((x1 - x0 - gap * (segs - 1)) / segs);
    const on = Math.round(fraction * segs);
    for (let i = 0; i < segs; i++) {
      const sx = x0 + i * (seg + gap);
      if (i < on) fillRect(this.bm, sx, y, seg, h);
      else this.roundBoxDots(sx, y, sx + seg, y + h);
    }
  }

  roundBoxDots(x0, y0, x1, y1) {
    for (let y = y0; y < y1; y += 2) for (let x = x0; x < x1; x += 2) setPx(this.bm, x, y);
  }

  // Line graph with axes, dotted gridlines, and a dithered area under the line.
  lineGraph(x0, y0, x1, y1, values, { labels = [], area = true } = {}) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const pad = 4;
    const pts = values.map((v, i) => [
      Math.round(x0 + pad + (i * (x1 - x0 - pad * 2)) / (values.length - 1)),
      Math.round(y1 - pad - ((v - min) / span) * (y1 - y0 - pad * 2)),
    ]);
    for (let g = 0; g <= 3; g++) {
      const gy = y0 + Math.round((g * (y1 - y0)) / 3);
      for (let x = x0; x < x1; x += 4) setPx(this.bm, x, gy);
    }
    this.vline(x0, y0, y1 + 1, 1);
    this.hline(x0, x1, y1, 1);
    if (area) {
      for (const [x, y] of pts) this.vline(x, y, y1, 1);
      // Dither the area: keep every second column solid, thinning out toward the baseline.
      for (let i = 1; i < pts.length; i++) {
        const [ax, ay] = pts[i - 1];
        const [bx, by] = pts[i];
        for (let x = ax; x <= bx; x++) {
          const yy = Math.round(ay + ((by - ay) * (x - ax)) / Math.max(1, bx - ax));
          for (let y = yy + 3; y < y1; y += 3) if ((x + y) % 2 === 0) setPx(this.bm, x, y);
        }
      }
    }
    for (let i = 1; i < pts.length; i++) drawLine(this.bm, pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]);
    for (let i = 1; i < pts.length; i++) drawLine(this.bm, pts[i - 1][0], pts[i - 1][1] + 1, pts[i][0], pts[i][1] + 1);
    for (const [x, y] of pts.filter((_, i) => i % 6 === 0)) fillRect(this.bm, x - 2, y - 2, 5, 5);
    labels.forEach(({ i, text }) => this.text(pts[i][0] - 6, y1 + 6, text, 2));
    return pts;
  }

  // Vertical bars with dot-font value labels on top and day labels underneath.
  barChart(x0, x1, y0, y1, values, labels) {
    const max = Math.max(...values, 1);
    const slot = Math.floor((x1 - x0) / values.length);
    const barW = Math.floor(slot * 0.55);
    values.forEach((v, i) => {
      const h = Math.max(2, Math.round((v / max) * (y1 - y0 - 24)));
      const bx = x0 + i * slot + Math.floor((slot - barW) / 2);
      fillRect(this.bm, bx, y1 - h, barW, h);
      this.text(bx + Math.floor((barW - textWidth(String(v), 2)) / 2), y1 - h - 16, String(v), 2);
      this.textIn(x0 + i * slot, x0 + (i + 1) * slot, y1 + 6, labels[i], 2);
    });
    this.hline(x0, x1, y1, 2);
  }

  // Dot leader row: label, dots, value.
  row(x0, x1, y, label, value, scale = 2) {
    const tail = String(value);
    const total = textWidth(label, scale) + textWidth(tail, scale) + 2 * 6 * scale;
    const dotsW = x1 - x0 - total;
    const dotCount = Math.max(1, Math.floor(dotsW / (2 * scale)));
    this.text(x0, y, label, scale);
    const dx = x0 + textWidth(label, scale) + 6 * scale;
    for (let i = 0; i < dotCount; i++) fillRect(this.bm, dx + i * 2 * scale, y + 6 * scale, scale, scale);
    this.textRight(x1, y, tail, scale);
  }

  advance(h) {
    this.y += h;
    return this;
  }

  // Trims the canvas to the drawn height plus a small margin, as the printed image.
  crop(margin = 12) {
    const h = Math.min(MAX_H, this.y + margin);
    const rowBytes = W / 8;
    return { w: W, h, bits: this.bm.bits.slice(0, rowBytes * h) };
  }
}

// Icon sprites, 9 pixels or fewer per side.
const SPRITES = {
  sun: ['....#....', '..#.#.#..', '...###...', '.#######.', '#########', '.#######.', '...###...', '..#.#.#..', '....#....'],
  moon: ['...###...', '..##.....', '.##......', '.##......', '.##......', '.##......', '.##......', '..##.....', '...###...'],
  bone: ['##.....##', '###...###', '...###...', '###...###', '##.....##'],
  battery: ['##########', '#........#', '#........#', '#........#', '##########'],
  bolt: ['....##.', '...##..', '..##...', '.#####.', '....##.', '...##..', '..##...', '.##....', '##.....'],
  thermo: ['..#..', '..#..', '..#..', '..#..', '.###.', '#####', '#####', '.###.'],
  cloud: ['...###....', '.#########.', '###########', '###########', '.#########.'],
  rain: ['.#.#.#.', '.#.#.#.', '.#.#.#.'],
  walk: ['..##.', '.###.', '..#..', '.###.', '#..#.', '.##..', '#..#.'],
  tick: ['.....#', '....##', '#..##.', '##.#..', '.##...', '..#...'],
  box: ['#####', '#...#', '#...#', '#...#', '#####'],
  heart: ['.##.##.', '#######', '#######', '.#####.', '..###..', '...#...'],
  drop: ['..#..', '.###.', '#####', '#####', '.###.'],
};

module.exports = { Canvas, W, glyph, textWidth, SPRITES, GLYPHS };
