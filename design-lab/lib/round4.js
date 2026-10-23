'use strict';
// Round 4: built from the taste profile (notes/taste-profile.md). Outlined cards only, hello header,
// segmented bars, energy line graph, alert pills, rows and Yannic vs Allyson comparisons.
// Removed: filled and elevated cards, big numerals, sparkText, frames, wordmarks, centred headers, Font B.
const { Canvas, textWidth } = require('./raster');
const { D } = require('./designs');
const { card, pill, paragraph, metric, L, R } = require('./round2');

const SCALES = [2, 3];
const RADII = [4, 8, 12];

function hello(c, v, x0, x1) {
  c.text(x0, c.y, 'HELLO YANNIC', v.scale + 1);
  c.y += 7 * (v.scale + 1) + 8;
  c.y += paragraph(c, x0, c.y, 'Cloudy, 12 C. Bridget has been out twice. Cheap energy until 16:00.', 2, x1 - x0) + 2;
}

function rows(c, v, x0, x1) {
  c.text(x0, c.y, 'TODAY', 2);
  c.y += 22;
  c.row(x0, x1, c.y, 'BODY BATTERY', `${D.yannic.bodyBattery}/100`, 2);
  c.y += 24;
  c.row(x0, x1, c.y, 'STRESS AVG', D.yannic.stress, 2);
  c.y += 24;
  c.row(x0, x1, c.y, 'STEPS', D.yannic.steps.toLocaleString('en-GB'), 2);
  c.y += 24;
}

function compare(c, v, x0, x1) {
  const w = [14, 14, 14].map((n) => Math.floor(((x1 - x0) * n) / 42));
  const cols = (a, b, cc) => {
    c.text(x0, c.y, a, 2);
    c.textRight(x0 + w[0] + w[1] + 6 * 2, c.y, b, 2);
    c.textRight(x1, c.y, cc, 2);
    c.y += 22;
  };
  cols('', 'YANNIC', 'ALLYSON');
  cols('STRESS', String(D.yannic.stress), String(D.allyson.stress));
  cols('STEPS', (D.yannic.steps / 1000).toFixed(1) + 'K', (D.allyson.steps / 1000).toFixed(1) + 'K');
  cols('SLEEP', '7H 12', String(D.allyson.sleepScore));
}

function segbar(c, v, x0, x1) {
  const items = [
    ['BODY BATTERY', D.yannic.bodyBattery / 100, `${D.yannic.bodyBattery}%`],
    ['CPU', 0.18, '18%'],
    ['RAM', 0.61, '61%'],
  ];
  for (const [label, f, txt] of items) {
    c.text(x0, c.y, label, 2);
    c.textRight(x1, c.y, txt, 2);
    c.segBar(x0, x1, c.y + 22, 10, f, 20);
    c.y += 42;
  }
}

function energy(c, v, x0, x1) {
  c.text(x0, c.y, 'ENERGY', 2);
  c.y += 22;
  c.row(x0, x1, c.y, 'NOW', `${D.energy.now.toFixed(3)} GBP`, 2);
  c.y += 24;
  c.row(x0, x1, c.y, 'NEXT 16:00', `${D.energy.next.toFixed(3)} GBP`, 2);
  c.y += 28;
  c.lineGraph(x0 + 4, c.y, x1 - 4, c.y + 56, D.outdoor24, { area: false });
  c.y += 56 + 16;
}

function alert(c, v, x0) {
  pill(c, v, x0, x0 + 170, c.y, 'PEAK 16:00', { fill: true, scale: 2 });
  c.y += 7 * 2 + 14 + 10;
  c.text(x0, c.y, 'RUN THE WASHER BEFORE 16:00', 2);
  c.y += 24;
}

function dogs(c, v, x0, x1) {
  c.text(x0, c.y, 'DOGS TODAY', 2);
  c.y += 22;
  for (const [name, n] of Object.entries(D.dogs)) {
    const k = n;
    const tail = `P${k.pee} O${k.poop} F${k.food} R${k.run}`;
    c.row(x0, x1, c.y, name.toUpperCase(), tail, 2);
    c.y += 24;
  }
}

const MODULES = { rows, compare, segbar, energy, dogs };

// Seeded picks, so the same index always gives the same design.
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function specs(count) {
  const r = rng(20261025);
  const pick = (a) => a[Math.floor(r() * a.length)];
  const out = [];
  const seen = new Set();
  let guard = 0;
  while (out.length < count && guard++ < 5000) {
    const header = r() < 0.7 ? 'hello' : 'none';
    const n = r() < 0.5 ? 2 : 3;
    const mods = [];
    const pool = ['rows', 'compare', 'segbar', 'energy', 'dogs', 'alert'];
    while (mods.length < n) {
      const m = pick(pool);
      if (!mods.includes(m)) mods.push(m);
    }
    const v = { r: pick(RADII), scale: pick(SCALES), gap: pick([8, 12]) };
    const key = [header, mods.join('+'), v.r, v.scale, v.gap].join('|');
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ header, mods, v });
  }
  return out;
}

function draw(spec, c) {
  const { header, mods, v } = spec;
  c.y = 14;
  if (header === 'hello') {
    card(c, v, (x0, x1) => hello(c, v, x0, x1));
  }
  for (const m of mods) {
    card(c, v, (x0, x1) => {
      if (m === 'alert') alert(c, v, x0);
      else MODULES[m](c, v, x0, x1);
    });
  }
}

function buildRound4(count = 20) {
  return specs(count).map((spec, i) => {
    const id = `B4-${String(i + 1).padStart(3, '0')}`;
    const measure = new Canvas();
    draw(spec, measure);
    const c = new Canvas();
    draw(spec, c);
    const img = c.crop(12);
    const kind = spec.mods.includes('alert') || spec.mods.includes('energy') ? 'evening' : 'morning';
    return {
      id,
      name: `R4 · ${spec.header === 'hello' ? 'Hello + ' : ''}${spec.mods.map((m) => m[0].toUpperCase() + m.slice(1)).join(' + ')} · r${spec.v.r} · scale ${spec.v.scale}`,
      round: 4,
      family: 'r4',
      kind,
      header: spec.header,
      bodies: spec.mods,
      decoration: 'outlined',
      density: spec.v.gap >= 12 ? 'airy' : 'dense',
      weight: 'light',
      font: 'dot5x7',
      inspiredBy: 'taste profile (notes/taste-profile.md)',
      ideas: 'outlined cards, hello header, segmented bars, energy line, alert pill, rows, compare',
      variant: spec.v,
      width: 512,
      height: img.h,
      raster: img,
    };
  });
}

module.exports = { buildRound4, textWidth, L, R, metric };
