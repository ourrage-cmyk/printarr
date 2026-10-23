'use strict';
// Round 3: Material 3 rules (notes/material3-notes.md) on the round 2 layout, in 1-bit.
// Corner radii from the 10-step scale, tonal fills as Bayer dither, type hierarchy from the scale,
// filter chips as sets, linear and circular progress, list tiles, and asymmetric inner corners.
const { Canvas, textWidth, glyph } = require('./raster');
const { D } = require('./designs');
const { setPx, fillRect } = require('./escpos');
const { pixel, negativeGrid, arcGauge, metric, eraseText, paragraph, L, R } = require('./round2');

const PAD = 14;
const TONE = { low: 0.06, mid: 0.14, high: 0.25 };
const BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];

// True when (x, y) lies inside a rounded rectangle with corner radius r.
function insideRound(x, y, x0, y0, x1, y1, r) {
  const cx = Math.min(Math.max(x, x0 + r), x1 - r);
  const cy = Math.min(Math.max(y, y0 + r), y1 - r);
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
}

// Tonal fill: dithers only the empty pixels inside the rounded box, so text and strokes stay solid.
function tintEmpty(c, x0, y0, x1, y1, level, r = 0) {
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      if (pixel(c, x, y) === 0 && (BAYER[y & 3][x & 3] + 0.5) / 16 < level && insideRound(x, y, x0, y0, x1, y1, r)) setPx(c.bm, x, y);
    }
  }
}

// Asymmetric rounded rectangle, one radius per corner (M3 inner corners).
function asymBox(c, x0, y0, x1, y1, { tl, tr, br, bl }, t = 2) {
  c.hline(x0 + tl, x1 - tr, y0, t);
  c.hline(x0 + bl, x1 - br, y1 - t, t);
  c.vline(x0, y0 + tl, y1 - bl, t);
  c.vline(x1 - t, y0 + tr, y1 - br, t);
  const arc = (cx, cy, r, a0, a1) => {
    if (r <= 0) return;
    for (let a = a0; a <= a1; a += 2) {
      const rad = (a * Math.PI) / 180;
      fillRect(c.bm, Math.round(cx + Math.cos(rad) * r), Math.round(cy + Math.sin(rad) * r), t, t);
    }
  };
  arc(x0 + tl, y0 + tl, tl, 180, 270);
  arc(x1 - tr, y0 + tr, tr, 270, 360);
  arc(x1 - br, y1 - br, br, 0, 90);
  arc(x0 + bl, y1 - bl, bl, 90, 180);
}

// Card with M3 variants. Radius is a step from the scale, or 'full' for half the height.
function m3card(c, v, fn, { x0 = L, x1 = R, radius = v.r } = {}) {
  const top = c.y;
  c.y += PAD;
  fn(x0 + PAD, x1 - PAD);
  const bottom = c.y + PAD;
  const r = radius === 'full' ? Math.floor((bottom - top) / 2) : Math.min(radius, Math.floor((bottom - top) / 2));
  if (v.style !== 'outlined') tintEmpty(c, x0 + 2, top + 2, x1 - 2, bottom - 2, TONE[v.tone], Math.max(0, r - 2));
  if (v.style !== 'filled') c.roundBox(x0, top, x1, bottom, r, v.style === 'elevated' ? 1 : 2);
  else c.roundBox(x0, top, x1, bottom, r, 1);
  c.y = bottom + 8;
}

// M3 type scale on the 1-bit grid. Emphasized draws the glyphs again one dot to the right.
function type(c, x, y, str, role, emph = false) {
  const scale = { display: 6, headline: 4, title: 3, body: 2, label: 2 }[role];
  const txt = role === 'label' ? str.toUpperCase() : str;
  c.text(x, y, txt, scale);
  if (emph) c.text(x + 1, y, txt, scale);
  return 7 * scale;
}

// Filter chip: selected = filled pill, unselected = outlined pill (M3 chips).
function chip(c, v, x, y, label, selected) {
  const scale = 2;
  const h = 7 * scale + 14;
  const w = textWidth(label, scale) + 28;
  c.roundBox(x, y, x + w, y + h, Math.floor(h / 2), 2);
  if (selected) {
    c.fill(x + 3, y + 3, x + w - 3, y + h - 3);
    c.text(x + 14, y + 7, label, scale);
    eraseText(c, x + 14, y + 7, label, scale);
  } else {
    c.text(x + 14, y + 7, label, scale);
  }
  return w;
}

// Linear progress: dotted track, solid fill (M3 linear indicator).
function linear(c, x0, x1, y, fraction, h = 8) {
  for (let yy = y; yy < y + h; yy += 2) for (let xx = x0; xx < x1; xx += 2) setPx(c.bm, xx, yy);
  fillRect(c.bm, x0, y, Math.round((x1 - x0) * fraction), h);
}

// Circular indicator: dot ring (M3 circular indicator), value in the centre.
function circular(c, cx, cy, r, fraction, label, value) {
  c.dotRing(cx, cy, r, fraction, 4);
  c.textIn(cx - r, cx + r, cy - 6, value, 2);
  c.textIn(cx - r - 10, cx + r + 10, cy + r + 12, label, 2);
}

// ---- families ------------------------------------------------------------------------------

// A: tonal stack of filled cards at three levels, display numerals.
function famTonal(c, v) {
  const rows = [
    ['BODY BATTERY', String(D.yannic.bodyBattery), '%'],
    ['STEPS', (D.yannic.steps / 1000).toFixed(1), 'K'],
    ['ENERGY NOW', D.energy.now.toFixed(3), 'GBP/KWH'],
  ];
  const levels = ['low', 'mid', 'high'];
  rows.forEach(([label, val, unit], i) => {
    m3card(c, { ...v, tone: levels[i] }, (x0) => {
      type(c, x0, c.y, label, 'label');
      c.y += 22;
      const w = type(c, x0, c.y, val, 'display', v.emph);
      type(c, x0 + textWidth(val, 6) + 10, c.y + 30, unit, 'body');
      c.y += w - 6;
    });
  });
}

// B: outlined cards with filter chips as the choice for the period.
function famFilter(c, v) {
  let x = L;
  ['MORNING', 'EVENING', 'NIGHT'].forEach((t, i) => {
    x += chip(c, v, x, c.y, t, i === 1) + 8;
  });
  c.y += 7 * 2 + 14 + 12;
  m3card(c, v, (x0, x1) => {
    type(c, x0, c.y, 'Evening', 'title', v.emph);
    c.y += 26;
    c.row(x0, x1, c.y, 'STEPS', D.yannic.stepsEvening.toLocaleString('en-GB'), 2);
    c.y += 24;
    c.row(x0, x1, c.y, 'ENERGY USED', `${D.energy.used} KWH`, 2);
    c.y += 24;
    c.row(x0, x1, c.y, 'SAVED TODAY', `${D.energy.saved.toFixed(2)} GBP`, 2);
    c.y += 24;
  });
}

// C: linear progress rows (group indicators per list, not per item).
function famLinear(c, v) {
  m3card(c, v, (x0, x1) => {
    type(c, x0, c.y, 'Today', 'headline', v.emph);
    c.y += 40;
    const rows = [
      ['BODY BATTERY', D.yannic.bodyBattery / 100, `${D.yannic.bodyBattery}%`],
      ['SLEEP SCORE', D.allyson.sleepScore / 100, `${D.allyson.sleepScore}`],
      ['STEPS GOAL', D.yannic.steps / 10000, `${D.yannic.steps.toLocaleString('en-GB')}`],
      ['STRESS', 1 - D.yannic.stress / 100, `${D.yannic.stress}`],
    ];
    for (const [label, f, val] of rows) {
      c.row(x0, x1, c.y, label, val, 2);
      c.y += 24;
      linear(c, x0, x1, c.y, f, 10);
      c.y += 26;
    }
  });
}

// D: three circular indicators in a set.
function famCircular(c, v) {
  m3card(c, v, (x0, x1) => {
    type(c, x0, c.y, 'Now', 'title', v.emph);
    c.y += 30;
    const cw = Math.floor((x1 - x0) / 3);
    const top = c.y;
    const items = [
      [D.yannic.bodyBattery / 100, String(D.yannic.bodyBattery), 'BATTERY'],
      [D.allyson.sleepScore / 100, String(D.allyson.sleepScore), 'SLEEP'],
      [D.yannic.steps / 10000, (D.yannic.steps / 1000).toFixed(1) + 'K', 'STEPS'],
    ];
    items.forEach(([f, val, label], i) => {
      const cx = x0 + i * cw + Math.floor(cw / 2);
      circular(c, cx, top + 46, 36, f, label, val);
    });
    c.y = top + 46 + 36 + 40;
  });
}

// E: dog chip set; the selected dog shows her counts.
function famDogChips(c, v) {
  let x = L;
  ['BRIDGET', 'KIDA'].forEach((t, i) => {
    x += chip(c, v, x, c.y, t, i === 0) + 8;
  });
  c.y += 7 * 2 + 14 + 12;
  m3card(c, v, (x0, x1) => {
    type(c, x0, c.y, 'Bridget', 'headline', v.emph);
    c.y += 40;
    const counts = D.dogs.Bridget;
    const cw = Math.floor((x1 - x0) / 4);
    [['pee', 'drop'], ['poop', 'heart'], ['food', 'bone'], ['run', 'walk']].forEach(([k, icon], i) => {
      const cx = x0 + i * cw;
      c.sprite(cx, c.y, icon, 3);
      type(c, cx, c.y + 34, k.toUpperCase(), 'label');
      type(c, cx, c.y + 56, String(counts[k]), 'title', v.emph);
    });
    c.y += 100;
  });
}

// F: expressive shapes. A hero card with the largest step, then inner-corner cards that join up.
function famExpressive(c, v) {
  const hero = { ...v, tone: 'mid', style: 'filled' };
  m3card(c, hero, (x0, x1) => {
    type(c, x0, c.y, 'Good morning', 'headline', v.emph);
    c.y += 40;
    c.y += paragraph(c, x0, c.y, 'Cloudy, 12 C. Rain after 3pm. Cheap energy until 16:00.', 2, x1 - x0) + 4;
  }, { radius: 'full' });
  const top = c.y;
  const mid = Math.floor((R - L) / 2);
  const h = 96;
  asymBox(c, L, top, L + mid - 3, top + h, { tl: 28, tr: 4, br: 4, bl: 28 }, 2);
  asymBox(c, L + mid + 3, top, R, top + h, { tl: 4, tr: 28, br: 28, bl: 4 }, 2);
  metric(c, L + 12, top + 12, { label: 'BATTERY', value: String(D.yannic.bodyBattery), unit: '%', scale: v.num - 1 });
  metric(c, L + mid + 15, top + 12, { label: 'SLEEP', value: String(D.allyson.sleepScore), unit: '', scale: v.num - 1 });
  c.y = top + h + 8;
}

// G: full type scale demonstration with real content.
function famTypeScale(c, v) {
  m3card(c, v, (x0, x1) => {
    type(c, x0, c.y, 'Morning', 'label');
    c.y += 20;
    c.y += type(c, x0, c.y, '72', 'display', v.emph) - 4;
    c.y += 8;
    c.y += type(c, x0, c.y, 'Body battery', 'headline', v.emph) - 8;
    c.y += 8;
    c.y += paragraph(c, x0, c.y, 'Good morning. Energy is cheap until 16:00. Bin day is tomorrow.', 2, x1 - x0) + 6;
    c.y += type(c, x0, c.y, 'Updated 07:00', 'label') - 6;
  });
}

// H: list tiles, each with a leading icon, headline, supporting text and trailing value.
function famListTiles(c, v) {
  m3card(c, v, (x0, x1) => {
    const rows = [
      ['bolt', 'Energy peak', 'Starts at 16:00', '0.245'],
      ['drop', 'Rain', 'After 3pm', '58%'],
      ['bone', 'Dog food', 'Two bags left', '2'],
      ['walk', 'Steps', 'Goal 10,000', '6.1K'],
    ];
    for (const [icon, head, sup, trail] of rows) {
      c.sprite(x0, c.y + 8, icon, 3);
      c.text(x0 + 36, c.y, head.toUpperCase(), 2);
      c.text(x0 + 36, c.y + 22, sup.toUpperCase(), 2);
      c.textRight(x1, c.y + 8, trail, 3);
      c.y += 58;
      c.hline(x0 + 36, x1, c.y - 8, 1);
    }
  });
}

const FAMILIES = [
  { key: 'tonal', kind: 'morning', fn: famTonal, inspired: 'M3 tonal surfaces and card levels; screenshot 01 metric tiles' },
  { key: 'filter', kind: 'evening', fn: famFilter, inspired: 'M3 filter chips; screenshot 03 live meters' },
  { key: 'linear', kind: 'morning', fn: famLinear, inspired: 'M3 linear progress; screenshot 05 metric list' },
  { key: 'circular', kind: 'morning', fn: famCircular, inspired: 'M3 circular progress; screenshot 01 greeting card' },
  { key: 'chips', kind: 'evening', fn: famDogChips, inspired: 'M3 suggestion chips; screenshot 02 dog tiles' },
  { key: 'expressive', kind: 'morning', fn: famExpressive, inspired: 'M3 shape scale and inner corners; screenshot 01 hero card' },
  { key: 'typescale', kind: 'morning', fn: famTypeScale, inspired: 'M3 type scale, emphasized styles; Nothing dot headline' },
  { key: 'listtiles', kind: 'alert', fn: famListTiles, inspired: 'M3 list items; screenshot 05 health list' },
];

// Five variants, from the 10-step corner scale (none, small, large, extra large, full).
const VARIANTS = [
  { r: 8, tone: 'low', style: 'filled', num: 5, emph: false, gap: 8 },
  { r: 16, tone: 'mid', style: 'outlined', num: 4, emph: true, gap: 8 },
  { r: 'full', tone: 'mid', style: 'elevated', num: 6, emph: false, gap: 8 },
  { r: 28, tone: 'high', style: 'filled', num: 4, emph: true, gap: 8 },
  { r: 4, tone: 'low', style: 'outlined', num: 5, emph: false, gap: 8 },
];

function buildRound3() {
  const designs = [];
  let n = 0;
  for (const fam of FAMILIES) {
    VARIANTS.forEach((v, vi) => {
      n += 1;
      const id = `B3-${String(n).padStart(3, '0')}`;
      const measure = new Canvas();
      measure.y = 14;
      fam.fn(measure, v);
      const h = measure.y + 12;
      const c = new Canvas();
      c.y = 14;
      fam.fn(c, v);
      const img = c.crop(12);
      designs.push({
        id,
        name: `M3 ${fam.key[0].toUpperCase()}${fam.key.slice(1)} · v${vi + 1} · ${v.style} · r${v.r} · ${v.tone} tone${v.emph ? ' · emphasized' : ''}`,
        round: 3,
        family: fam.key,
        kind: fam.kind,
        header: 'raster',
        bodies: [fam.key],
        decoration: v.style,
        density: 'airy',
        weight: v.emph ? 'bold' : 'light',
        font: 'dot5x7',
        inspiredBy: fam.inspired,
        ideas: `Material 3 ${v.style} card, radius ${v.r}, ${v.tone} tone, display numeral ${v.num}`,
        variant: v,
        width: 512,
        height: img.h,
        raster: img,
      });
      void h;
    });
  }
  return designs;
}

module.exports = { buildRound3, FAMILIES, VARIANTS, glyph };
