'use strict';
// Round 2: Material-style cards and pills (HA screenshots 01 to 09), Nothing dot type and grid (brand reference),
// drawn as full-width 1-bit rasters. Each family has five variants, so 8 families give 40 designs.
const { Canvas, textWidth } = require('./raster');
const { D } = require('./designs');
const { setPx, fillRect } = require('./escpos');

const L = 14;
const R = 498;
const PAD = 14;

const VARIANTS = [
  { r: 4, tone: false, grid: false, num: 5, thick: false, gap: 10, order: 0 },
  { r: 14, tone: true, grid: false, num: 4, thick: true, gap: 14, order: 1 },
  { r: 18, tone: false, grid: true, num: 6, thick: false, gap: 12, order: 0 },
  { r: 8, tone: true, grid: true, num: 5, thick: true, gap: 8, order: 1 },
  { r: 12, tone: false, grid: true, num: 4, thick: false, gap: 16, order: 0 },
];

function pixel(c, x, y) {
  if (x < 0 || y < 0 || x >= 512) return 0;
  return (c.bm.bits[y * 64 + (x >> 3)] >> (7 - (x & 7))) & 1;
}

// Dot grid in the empty space only, so it never touches type or lines.
function negativeGrid(c, h, step = 10) {
  for (let y = step; y < h - step; y += step) {
    for (let x = step; x < 512 - step; x += step) {
      let busy = false;
      for (let dy = -5; dy <= 5 && !busy; dy += 1) for (let dx = -5; dx <= 5 && !busy; dx += 1) busy = pixel(c, x + dx, y + dy) === 1;
      if (!busy) setPx(c.bm, x, y);
    }
  }
}

// Card: rounded outline around whatever fn draws. Tone adds a light dither inside.
function card(c, v, fn, { x0 = L, x1 = R, pad = PAD } = {}) {
  const top = c.y;
  c.y += pad;
  fn(x0 + pad, x1 - pad);
  const bottom = c.y + pad;
  c.roundBox(x0, top, x1, bottom, v.r, v.thick ? 3 : 2);
  c.y = bottom + v.gap;
}

// Tile with a fixed size, optional tonal dither, and a callback for its content.
function tile(c, v, x0, x1, y, h, fn) {
  if (v.tone) c.dither(x0 + 3, y + 3, x1 - 3, y + h - 3, 0.1);
  c.roundBox(x0, y, x1, y + h, v.r, v.thick ? 3 : 2);
  fn(x0 + 10, x1 - 10, y + 8);
}

// Pill chip: fully rounded outline, centred text.
function pill(c, v, x0, x1, y, text, { scale = 2, fill = false } = {}) {
  const h = 7 * scale + 14;
  c.roundBox(x0, y, x1, y + h, Math.floor(h / 2), v.thick ? 3 : 2);
  if (fill) c.fill(x0 + 4, y + 4, x1 - 4, y + h - 4);
  const color = fill ? 'invert' : 'normal';
  if (fill) {
    // Draw the text in white on the solid pill by clearing its glyph dots.
    c.text(x0 + Math.floor((x1 - x0 - textWidth(text, scale)) / 2), y + 7, text, scale);
    eraseText(c, x0 + Math.floor((x1 - x0 - textWidth(text, scale)) / 2), y + 7, text, scale);
  } else {
    c.textIn(x0, x1, y + 7, text, scale);
  }
  return { h, color };
}

// Clears the glyph dots drawn at x, y so text shows through a solid fill.
function eraseText(c, x, y, str, scale) {
  const { glyph } = require('./raster');
  let cx = x;
  for (const ch of str) {
    const g = glyph(ch);
    for (let r = 0; r < 7; r++) for (let col = 0; col < 5; col++) {
      if (g[r][col] === '#') {
        for (let yy = 0; yy < scale; yy++) for (let xx = 0; xx < scale; xx++) {
          c.bm.bits[(y + r * scale + yy) * 64 + ((cx + col * scale + xx) >> 3)] &= ~(0x80 >> ((cx + col * scale + xx) & 7));
        }
      }
    }
    cx += 6 * scale;
  }
}

// Wraps a sentence to a width at scale, one line per call to c.text.
function paragraph(c, x, y, str, scale, maxW) {
  const perLine = Math.floor(maxW / (6 * scale));
  const words = str.toUpperCase().split(/\s+/);
  const lines = [];
  let cur = '';
  for (const w of words) {
    if (cur && cur.length + 1 + w.length > perLine) {
      lines.push(cur);
      cur = w;
    } else {
      cur = cur ? `${cur} ${w}` : w;
    }
  }
  if (cur) lines.push(cur);
  lines.forEach((ln, i) => c.text(x, y + i * (7 * scale + 4), ln, scale));
  return lines.length * (7 * scale + 4);
}

// Semicircle gauge drawn with dots, filled to the fraction (HA "Real-Time Savings" gauge, screenshot 03).
function arcGauge(c, cx, cy, r, fraction) {
  const steps = 90;
  for (let i = 0; i <= steps; i++) {
    const a = Math.PI + (i / steps) * Math.PI;
    const x = Math.round(cx + Math.cos(a) * r);
    const y = Math.round(cy + Math.sin(a) * r);
    if (i / steps <= fraction) fillRect(c.bm, x - 2, y - 2, 4, 4);
    else setPx(c.bm, x, y);
  }
  const na = Math.PI + fraction * Math.PI;
  const nx = Math.round(cx + Math.cos(na) * (r - 14));
  const ny = Math.round(cy + Math.sin(na) * (r - 14));
  c.vline(cx, cy - 2, cy + 1, 1);
  fillRect(c.bm, nx - 2, ny - 2, 5, 5);
}

// Icon with a label and a big value and unit. Used in the tiles.
function metric(c, x, y, { icon, label, value, unit, scale }) {
  if (icon) c.sprite(x, y, icon, 3);
  c.text(x + (icon ? 36 : 0), y + 4, label, 2);
  const vy = y + 26;
  const vw = c.text(x, vy, String(value), scale);
  if (unit) c.text(x + vw + 6, vy + (7 * scale) - (7 * 2), unit, 2);
  return vy + 7 * scale;
}

// ---- families. Each takes (c, v) and advances c.y. --------------------------------------------

// 01: Greeting card, weather tiles and heat pill.
function famGreeting(c, v) {
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'HELLO YANNIC', v.num - 1);
    c.y += 7 * (v.num - 1) + 10;
    c.y += paragraph(c, x0, c.y, `Cloudy, 12 C. Bridget has been out twice. Cheap energy until 16:00.`, 2, x1 - x0) + 4;
  });
  const half = Math.floor((R - L - 10) / 2);
  const top = c.y;
  tile(c, v, L, L + half, top, 124, (x, xr, y) => {
    metric(c, x, y, { icon: 'thermo', label: 'TEMP', value: '12', unit: 'C', scale: v.num });
    c.lineGraph(x, y + 62, xr, y + 102, D.outdoor24.slice(0, 24), { area: true });
  });
  tile(c, v, L + half + 10, R, top, 124, (x, xr, y) => {
    metric(c, x, y, { icon: 'drop', label: 'RAIN', value: '58', unit: '%', scale: v.num });
    c.text(x, y + 66, 'INSIDE 19.5 C', 2);
  });
  c.y = top + 124 + v.gap;
  card(c, v, (x0, x1) => {
    pill(c, v, x0, x0 + 170, c.y, 'HEAT NOW ON', { fill: true });
    c.y += 7 * 2 + 14 + 10;
  });
  card(c, v, (x0) => {
    c.sprite(x0, c.y, 'bolt', 3);
    c.text(x0 + 36, c.y + 4, 'ELECTRICITY', 2);
    c.text(x0, c.y + 26, D.energy.now.toFixed(3), v.num - 1);
    c.text(x0 + textWidth(D.energy.now.toFixed(3), v.num - 1) + 8, c.y + 26 + 7 * (v.num - 1) - 14, 'GBP/KWH', 2);
    c.y += 26 + 7 * (v.num - 1) + 4;
  });
}

// 05: Person metrics row and health list with icons (screenshot 05).
function famPerson(c, v) {
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'HOME', v.num);
    c.y += 7 * v.num + 8;
  });
  const cw = Math.floor((R - L - 20) / 3);
  const top = c.y;
  const items = [
    { icon: 'heart', label: 'BATTERY', value: '24', unit: '%' },
    { icon: 'thermo', label: 'STRESS', value: '35', unit: 'LVL' },
    { icon: 'walk', label: 'STEPS', value: '8.2', unit: 'K' },
  ];
  items.forEach((m, i) => {
    const x0 = L + i * (cw + 10);
    tile(c, v, x0, x0 + cw, top, 92, (x, xr, y) => metric(c, x, y, { ...m, scale: v.num - 1 }));
  });
  c.y = top + 92 + v.gap;
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'HEALTH', 2);
    c.y += 22;
    const rows = [['RESTING HR', '56 BPM', 'heart'], ['CALORIES', '2068 KCAL', 'bolt'], ['ACTIVE', '46 M', 'walk'], ['STRESS', '35 LEVEL', 'thermo']];
    for (const [label, val, icon] of rows) {
      c.sprite(x0, c.y, icon, 2);
      c.row(x0 + 26, x1, c.y + 4, label, val, 2);
      c.y += 26;
    }
  });
}

// 03: Energy with semicircle gauge, savings tiles and a usage line (screenshot 03).
function famEnergy(c, v) {
  const half = Math.floor((R - L - 10) / 2);
  const top = c.y;
  tile(c, v, L, L + half, top, 124, (x, xr, y) => {
    c.text(x, y, 'SAVINGS', 2);
    arcGauge(c, x + Math.floor((xr - x) / 2), y + 60, 46, 0.6);
    c.textIn(x, xr, y + 66, `${D.energy.saved.toFixed(2)} GBP`, 2);
  });
  tile(c, v, L + half + 10, R, top, 124, (x, xr, y) => {
    metric(c, x, y, { icon: 'bolt', label: 'SAVED', value: '2.46', unit: 'GBP', scale: v.num - 1 });
    c.text(x, y + 66, 'THIS MONTH', 2);
  });
  c.y = top + 124 + v.gap;
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'LIVE METERS', 2);
    c.y += 24;
    const rows = [['CURRENT', `${D.energy.now.toFixed(3)} GBP/KWH`], ['NEXT 16:00', `${D.energy.next.toFixed(4)} GBP/KWH`], ['COST NOW', '0.052 GBP/H']];
    for (const [l, val] of rows) {
      c.row(x0, x1, c.y, l, val, 2);
      c.y += 24;
    }
  });
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'USAGE VS RATE', 2);
    c.y += 22;
    c.lineGraph(x0 + 4, c.y, x1 - 4, c.y + 90, D.outdoor24.map((x) => 14 - x), { area: true, labels: [{ i: 0, text: '07' }, { i: 12, text: '19' }, { i: 23, text: '22' }] });
    c.y += 90 + 22;
  });
}

// 02: Dog tiles, four counts per dog, icons over labels (screenshot 02).
function famDogs(c, v) {
  const cols = 4;
  const gapX = 8;
  const w = Math.floor((R - L - 20 - gapX * (cols - 1)) / cols);
  for (const [name, counts] of Object.entries(D.dogs)) {
    card(c, v, (x0, x1) => {
      c.text(x0, c.y, name.toUpperCase(), v.num - 1);
      c.sprite(x1 - 36, c.y, 'bone', 3);
      c.y += 7 * (v.num - 1) + 12;
      const top = c.y;
      [['pee', 'drop'], ['poop', 'heart'], ['food', 'bone'], ['run', 'walk']].forEach(([k, icon], i) => {
        const tx = x0 + i * (w + gapX);
        tile(c, v, tx, tx + w, top, 98, (x, xr, y) => {
          c.sprite(x, y, icon, 3);
          c.text(x, y + 36, k.toUpperCase(), 2);
          c.text(x, y + 56, String(counts[k]), v.num - 1);
        });
      });
      c.y = top + 98 + 4;
    });
  }
}

// 06/09: Server bars with segmented gauges and threshold rows.
function famServer(c, v) {
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'SERVER', v.num - 1);
    c.y += 7 * (v.num - 1) + 10;
    const rows = [['CPU', 0.18, '18%'], ['RAM', 0.61, '61%'], ['GPU 3060', 0.42, '42%'], ['HDD MAX', 0.62, '62 C'], ['POOL', 0.71, '71%']];
    for (const [label, f, txt] of rows) {
      c.text(x0, c.y + 2, label, 2);
      c.textRight(x1, c.y + 2, txt, 2);
      c.segBar(x0, x1, c.y + 22, 10, f, 20);
      c.y += 40;
    }
    pill(c, v, x0, x0 + 130, c.y, 'UP TO DATE', { scale: 2 });
    c.y += 7 * 2 + 14 + 6;
  });
}

// Alert pills with a big peak number and rule-style lines.
function famAlert(c, v) {
  card(c, v, (x0, x1) => {
    pill(c, v, x0, x0 + 190, c.y, 'PEAK 16:00', { fill: true, scale: 2 });
    c.y += 7 * 2 + 14 + 12;
    c.text(x0, c.y, D.energy.next.toFixed(3), v.num);
    c.y += 7 * v.num + 6;
    c.text(x0, c.y, 'GBP/KWH UNTIL 19:00', 2);
    c.y += 24;
    c.text(x0, c.y, 'RUN THE WASHER BEFORE 16:00', 2);
    c.y += 22;
  });
  const cw = Math.floor((R - L - 20) / 3);
  const top = c.y;
  ['RAIN 3PM', 'BIN DAY', 'DOGS 2X'].forEach((t, i) => {
    const x0 = L + i * (cw + 10);
    pill(c, v, x0, x0 + cw, top, t, { scale: 2 });
  });
  c.y = top + 7 * 2 + 14 + v.gap;
}

// Shopping list as a card of checkbox rows, with pill headings.
function famList(c, v) {
  card(c, v, (x0, x1) => {
    pill(c, v, x0, x0 + 150, c.y, 'SHOPPING', { scale: 2 });
    c.y += 7 * 2 + 14 + 14;
    for (const item of D.list.slice(0, 6)) {
      c.sprite(x0, c.y, 'box', 3);
      c.text(x0 + 26, c.y + 2, item.toUpperCase(), 2);
      c.y += 28;
    }
  });
}

// Nothing-style poster: huge dot headline, dot grid margin, ring and segmented bar (brand reference).
function famPoster(c, v) {
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'MORNING', v.num + 1);
    c.y += 7 * (v.num + 1) + 6;
    c.text(x0, c.y, 'BRIEF 24 OCT', 2);
    c.y += 26;
    c.dotRing(x1 - 60, c.y + 50, 44, D.yannic.bodyBattery / 100, 4);
    c.text(x1 - 84, c.y + 42, String(D.yannic.bodyBattery), 2);
    c.text(x0, c.y, 'BODY BATTERY', 2);
    c.y += 30;
    c.segBar(x0, x0 + 260, c.y + 10, 16, D.yannic.bodyBattery / 100, 10);
    c.y += 50;
  });
}

const FAMILIES = [
  { key: 'greeting', kind: 'morning', fn: famGreeting, inspired: '01-home-top.jpg', ideas: 'greeting card, tile metrics with sparkline, pill button, electricity line' },
  { key: 'person', kind: 'morning', fn: famPerson, inspired: '05-people-yannic.jpg', ideas: 'three metric tiles, icon-led health list' },
  { key: 'energy', kind: 'evening', fn: famEnergy, inspired: '03-energy.jpg', ideas: 'semicircle dot gauge, savings tile, live meter rows, usage line chart' },
  { key: 'dogs', kind: 'evening', fn: famDogs, inspired: '02-home-dogs-and-camera.jpg', ideas: 'four-up counter tiles with icons per dog' },
  { key: 'server', kind: 'alert', fn: famServer, inspired: '06-server-view.jpg, 09-server-view-full-page.png', ideas: 'bar gauges with segments, status pill' },
  { key: 'alert', kind: 'alert', fn: famAlert, inspired: '03-energy.jpg (rate card)', ideas: 'filled pill, big numeral with unit, three chips' },
  { key: 'list', kind: 'list', fn: famList, inspired: 'design-notes.md (shopping and note)', ideas: 'checkbox sprite rows, pill heading' },
  { key: 'poster', kind: 'morning', fn: famPoster, inspired: 'Nothing brand reference (dot headline, segmented bar, ring)', ideas: 'dot headline, dot-ring gauge, segmented bar' },
];

function buildRound2() {
  const designs = [];
  let n = 0;
  for (const fam of FAMILIES) {
    VARIANTS.forEach((v, vi) => {
      n += 1;
      const id = `B2-${String(n).padStart(3, '0')}`;
      // First pass to find the height, then draw again with the dot grid behind the content.
      const measure = new Canvas();
      measure.y = 14;
      fam.fn(measure, v);
      const h = measure.y + 12;
      const c = new Canvas();
      c.y = 14;
      fam.fn(c, v);
      if (v.grid) negativeGrid(c, h);
      const img = c.crop(12);
      designs.push({
        id,
        name: `${fam.key[0].toUpperCase()}${fam.key.slice(1)} · v${vi + 1} · ${v.num >= 6 ? 'huge' : v.num >= 5 ? 'large' : 'medium'} numerals · r${v.r}${v.tone ? ' · tint' : ''}${v.grid ? ' · dot grid' : ''}`,
        round: 2,
        family: fam.key,
        kind: fam.kind,
        header: 'raster',
        bodies: [fam.key],
        decoration: v.tone ? 'tint' : 'outline',
        density: v.gap >= 14 ? 'airy' : 'dense',
        weight: v.thick ? 'bold' : 'light',
        font: 'dot5x7',
        inspiredBy: fam.inspired,
        ideas: fam.ideas,
        variant: v,
        width: 512,
        height: img.h,
        raster: img,
      });
    });
  }
  return designs;
}

module.exports = { buildRound2, FAMILIES, VARIANTS, pixel, negativeGrid, card, tile, pill, paragraph, arcGauge, metric, eraseText, L, R, PAD };
