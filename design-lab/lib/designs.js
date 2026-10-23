'use strict';
// Receipt design library. Sample numbers come from the Home Assistant dashboard notes and are not live data.
const { Doc } = require('./doc');
const { bitmap, drawLine, fillRect, setPx } = require('./escpos');

const D = {
  short: 'Sat 24 Oct',
  time: '07:00',
  yannic: { bodyBattery: 72, bbNow: 38, stress: 24, steps: 6120, stepsEvening: 8430 },
  allyson: { sleepScore: 81, stress: 31, steps: 9840 },
  energy: { now: 0.079, next: 0.245, nextAt: '16:00', saved: 0.42, used: 9.1 },
  house: { indoor: 19.5, outdoor: 12 },
  weather: 'Cloudy, 12 C, rain after 3pm',
  dogs: { Bridget: { pee: 3, poop: 1, food: 2, run: 1 }, Kida: { pee: 2, poop: 2, food: 2, run: 2 } },
  outdoor24: [8.4, 8.1, 8.0, 8.6, 9.5, 10.2, 11.0, 11.8, 12.4, 13.1, 13.6, 14.0, 14.2, 13.9, 13.1, 12.6, 12.0, 11.4, 10.9, 10.4, 10.0, 9.6, 9.2, 8.9],
  runs7: [1, 0, 2, 1, 1, 2, 1],
  list: ['Milk (oat)', 'Dog food, 2 bags', 'Bread', 'Eggs x6', 'Bin bags', 'Coffee beans', 'Lemons'],
};

// ---- raster helpers (1-bit, 512 dots wide) -------------------------------------------------
function sparkRaster(values, h = 72) {
  const w = 512;
  const bm = bitmap(w, h);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pts = values.map((v, i) => [
    Math.round((i * (w - 1)) / (values.length - 1)),
    h - 1 - Math.round(((v - min) / (max - min || 1)) * (h - 8)) - 4,
  ]);
  for (let x = 0; x < w; x += 4) setPx(bm, x, h - 1); // dotted baseline
  for (let i = 1; i < pts.length; i++) drawLine(bm, pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]);
  for (const [x, y] of pts) fillRect(bm, x - 2, y - 2, 4, 4); // endpoint markers
  return bm;
}

function barRaster(values, h = 72) {
  const w = 512;
  const bm = bitmap(w, h);
  const max = Math.max(...values, 1);
  const slot = Math.floor(w / values.length);
  values.forEach((v, i) => {
    const bh = Math.max(2, Math.round((v / max) * (h - 4)));
    fillRect(bm, i * slot + Math.floor(slot / 4), h - bh, Math.floor(slot / 2), bh);
  });
  return bm;
}

// Circular gauge (Nothing-style): dotted ring with a solid arc for the fraction.
function ringRaster(fraction, h = 150) {
  const w = 512;
  const bm = bitmap(w, h);
  const cx = w / 2;
  const cy = h / 2;
  const r = 66;
  for (let a = 0; a < 360; a += 3) {
    const rad = (a * Math.PI) / 180;
    if (a % 6 === 0) setPx(bm, Math.round(cx + Math.cos(rad) * r), Math.round(cy + Math.sin(rad) * r));
  }
  const steps = Math.round(360 * fraction);
  let prev = null;
  for (let a = -90; a <= -90 + steps; a++) {
    const rad = (a * Math.PI) / 180;
    const x = Math.round(cx + Math.cos(rad) * (r + 3));
    const y = Math.round(cy + Math.sin(rad) * (r + 3));
    if (prev) drawLine(bm, prev[0], prev[1], x, y);
    prev = [x, y];
  }
  return bm;
}

// Segmented bar (Nothing-style): ten blocks, filled to the fraction.
function segRaster(fraction, h = 36) {
  const w = 512;
  const bm = bitmap(w, h);
  const seg = 44;
  const filled = Math.round(fraction * 10);
  for (let i = 0; i < 10; i++) {
    if (i < filled) fillRect(bm, i * seg + 2, 0, seg - 8, h);
    else for (let y = 0; y < h; y += 4) setPx(bm, i * seg + 2 + 8, y); // empty slot as a dotted marker
  }
  return bm;
}

// ---- header styles ------------------------------------------------------------------------
const HEADERS = {
  centred(d, s) {
    d.line(s.title, { align: 'center', bold: true, size: 2 });
    d.line(D.short.toUpperCase(), { align: 'center', size: 1 });
    d.blank();
  },
  boxed(d, s) {
    d.raw(`+${'-'.repeat(d.W - 2)}+`);
    d.raw(`|${s.title.padStart(Math.floor((d.W - 2 + s.title.length) / 2)).padEnd(d.W - 2)}|`, { bold: true });
    d.raw(`|${D.short.toUpperCase().padStart(Math.floor((d.W - 2 + 12) / 2)).padEnd(d.W - 2)}|`, { bold: false });
    d.raw(`+${'-'.repeat(d.W - 2)}+`);
  },
  rules(d, s) {
    d.rule('=');
    d.heading(s.title);
    d.body(D.short.toUpperCase());
    d.rule('-');
  },
  hello(d, s) {
    d.line('Hello Yannic', { bold: true, size: 2 });
    d.para(s.summary);
    d.blank();
  },
  band(d, s) {
    d.line(` ${s.title.toUpperCase()} `, { align: 'center', bold: true, invert: true });
    d.blank();
  },
  // Dot-matrix wordmark style: wide spaced caps over one thin rule.
  wordmark(d, s) {
    const spaced = s.title.toUpperCase().split('').join(' ');
    d.line(spaced, { align: 'left', bold: true });
    d.rule('_');
  },
};

// ---- body blocks --------------------------------------------------------------------------
const BODY = {
  rows(d, s) {
    if (s.kind === 'morning') {
      d.row('BODY BATTERY', D.yannic.bodyBattery, '/100');
      d.row('STRESS AVG', D.yannic.stress);
      d.row('STEPS', D.yannic.steps.toLocaleString('en-GB'));
      d.row('ENERGY NOW', D.energy.now.toFixed(3), 'GBP/kWh');
      d.row(`ENERGY ${D.energy.nextAt}`, D.energy.next.toFixed(3), 'GBP/kWh');
      d.row('INSIDE / OUT', `${D.house.indoor} / ${D.house.outdoor}`, 'C');
    } else {
      d.row('STEPS', D.yannic.stepsEvening.toLocaleString('en-GB'));
      d.row('ENERGY USED', D.energy.used, 'kWh');
      d.row('SAVED TODAY', D.energy.saved.toFixed(2), 'GBP');
      d.row('BODY BATTERY', D.yannic.bbNow, 'now');
      d.row('STRESS AVG', 27);
    }
  },
  compare(d) {
    const w = [16, 13, 13];
    d.cols(['', 'YANNIC', 'ALLYSON'], w);
    d.cols(['STRESS', D.yannic.stress, D.allyson.stress], w);
    d.cols(['STEPS', D.yannic.steps.toLocaleString('en-GB'), D.allyson.steps.toLocaleString('en-GB')], w);
    d.cols(['SLEEP', '7h 12m', `${D.allyson.sleepScore} score`], w);
  },
  dogs(d) {
    d.heading('DOGS TODAY');
    const w = [10, 16, 16];
    d.cols(['', 'BRIDGET', 'KIDA'], w);
    for (const k of ['pee', 'poop', 'food', 'run']) {
      d.cols([k.toUpperCase(), D.dogs.Bridget[k], D.dogs.Kida[k]], w);
    }
  },
  spark(d) {
    d.heading('OUTSIDE, LAST 24 H');
    d.raster(512, 72, sparkRaster(D.outdoor24).bits);
    d.body(`MIN ${Math.min(...D.outdoor24).toFixed(1)}   MAX ${Math.max(...D.outdoor24).toFixed(1)}   NOW ${D.house.outdoor}`);
  },
  bars(d) {
    d.heading('DOG RUNS, 7 DAYS');
    d.raster(512, 72, barRaster(D.runs7).bits);
    d.body(' M   T   W   T   F   S   S ');
  },
  temp(d) {
    d.heading('OUTSIDE TEMP');
    for (const [h, i] of [['07', 0], ['10', 3], ['13', 6], ['16', 9], ['19', 12], ['22', 15]]) {
      const t = D.outdoor24[i];
      d.body(`${h}:00 ${'#'.repeat(Math.round(t * 2)).padEnd(30)} ${t.toFixed(1)} C`);
    }
  },
  para(d, s) {
    d.para(s.paragraph);
  },
  ring(d) {
    d.heading('BODY BATTERY');
    d.raster(512, 150, ringRaster(D.yannic.bodyBattery / 100).bits);
    d.line(`${D.yannic.bodyBattery}`, { align: 'center', bold: true, size: 2 });
  },
  tiles(d) {
    const cell = Math.floor(d.inner / 2);
    d.body(`[ STEPS ${D.yannic.steps.toLocaleString('en-GB')} ]`.padEnd(cell) + `[ STRESS ${D.yannic.stress} ]`);
    d.body(`[ BATTERY ${D.yannic.bodyBattery} ]`.padEnd(cell) + `[ SLEEP ${D.allyson.sleepScore} ]`);
  },
  segbar(d) {
    d.heading('BODY BATTERY');
    d.raster(512, 36, segRaster(D.yannic.bodyBattery / 100).bits);
    d.body(`${D.yannic.bodyBattery} / 100`);
  },
  big(d) {
    d.line(`${D.energy.next.toFixed(3)}`, { align: 'center', bold: true, size: 2 });
    d.line('GBP/kWh FROM 16:00', { align: 'center' });
  },
  sparkText(d) {
    const chars = " ._-~'^";
    const v = D.outdoor24;
    const min = Math.min(...v);
    const max = Math.max(...v);
    const line = v.map((x) => chars[Math.round(((x - min) / (max - min || 1)) * (chars.length - 1))]).join('');
    d.body(`OUT ${line}`);
    d.body(`${min.toFixed(1)} to ${max.toFixed(1)} C today`);
  },
  checklist(d) {
    for (const item of D.list.slice(0, 6)) d.body(`[ ] ${item}`);
  },
};

const KINDS = {
  morning: {
    title: 'Good morning',
    headers: ['centred', 'boxed', 'rules', 'hello', 'band', 'wordmark'],
    bodies: ['rows', 'compare', 'dogs', 'spark', 'bars', 'temp', 'ring', 'tiles', 'segbar', 'para'],
    summary: 'Cloudy, 12 C, rain after 3pm. Bridget and Kida have been out twice this morning.',
    paragraph: 'Good morning. Body battery is at 72 and energy is cheap until 16:00. Bin day is tomorrow.',
  },
  evening: {
    title: 'Good evening',
    headers: ['centred', 'rules', 'hello', 'band', 'wordmark'],
    bodies: ['rows', 'compare', 'dogs', 'spark', 'temp', 'tiles', 'segbar', 'para'],
    summary: 'You saved 0.42 GBP today. Kida has been walked twice.',
    paragraph: 'Good evening. You walked 8,430 steps. Energy peak starts at 16:00, and the house is 19.5 C.',
  },
  alert: {
    title: 'Alert',
    headers: ['band', 'boxed', 'centred', 'wordmark'],
    bodies: ['big', 'rows', 'para', 'sparkText', 'ring'],
    summary: '',
    paragraph: 'Peak electricity starts at 16:00 at 0.245 GBP per kWh. Run the washing machine before then.',
  },
  list: {
    title: 'Shopping list',
    headers: ['rules', 'centred', 'boxed', 'wordmark'],
    bodies: ['checklist', 'para'],
    summary: '',
    paragraph: 'Add to the list before Friday. Tell Allyson if the oat milk is out.',
  },
};

const DECORATIONS = ['none', 'stars', 'dots', 'footer', 'frame'];
const LABEL = {
  morning: 'Morning', evening: 'Evening', alert: 'Alert', list: 'List',
  centred: 'Centred', boxed: 'Boxed', rules: 'Rules', hello: 'Hello', band: 'Band', wordmark: 'Wordmark',
  rows: 'Rows', compare: 'Compare', dogs: 'Dog grid', spark: 'Spark', bars: 'Bars', temp: 'Temp chart',
  ring: 'Ring', tiles: 'Tiles', segbar: 'Seg bar', para: 'Para', big: 'Big number', sparkText: 'Text spark', checklist: 'Checklist',
  none: 'Plain', stars: 'Stars', dots: 'Dots', footer: 'Footer', frame: 'Frame',
  dense: 'Dense', airy: 'Airy', bold: 'Bold', light: 'Light',
};
const RASTER_BODIES = new Set(['spark', 'bars', 'ring', 'segbar']);

// Seeded RNG so the same index always gives the same design.
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

function generateSpecs(count) {
  const r = rng(20261024);
  const pick = (arr) => arr[Math.floor(r() * arr.length)];
  const specs = [];
  const seen = new Set();
  let guard = 0;
  while (specs.length < count && guard++ < 20000) {
    const kind = pick(Object.keys(KINDS));
    const k = KINDS[kind];
    const header = pick(k.headers);
    const nBodies = r() < 0.5 ? 1 : 2;
    const bodies = [];
    while (bodies.length < nBodies) {
      const b = pick(k.bodies);
      if (!bodies.includes(b)) bodies.push(b);
    }
    const decoration = pick(DECORATIONS);
    const density = r() < 0.5 ? 'dense' : 'airy';
    const weight = r() < 0.5 ? 'bold' : 'light';
    const font = r() < 0.7 ? 'A' : 'B';
    // Frames only wrap text-only bodies without a boxed header. Hello is only for morning and evening.
    if (decoration === 'frame' && (bodies.some((b) => RASTER_BODIES.has(b)) || header === 'boxed')) continue;
    if (header === 'hello' && !['morning', 'evening'].includes(kind)) continue;
    const key = [kind, header, bodies.join('+'), decoration, density, weight, font].join('|');
    if (seen.has(key)) continue;
    seen.add(key);
    specs.push({ kind, header, bodies, decoration, density, weight, font });
  }
  return specs.map((spec, i) => {
    const id = `D${String(i + 1).padStart(3, '0')}`;
    const parts = [
      LABEL[spec.kind],
      LABEL[spec.header],
      spec.bodies.map((b) => LABEL[b] || b).join(' + '),
      LABEL[spec.decoration],
      LABEL[spec.density],
      LABEL[spec.weight],
      spec.font === 'B' ? 'Font B' : null,
    ];
    const name = parts.filter(Boolean).join(' · ');
    const k = KINDS[spec.kind];
    return { id, name, ...spec, title: k.title, summary: k.summary, paragraph: k.paragraph };
  });
}

function buildDesign(spec) {
  const frame = spec.decoration === 'frame';
  const d = new Doc({ font: spec.font, frame, bodyBold: spec.weight === 'bold' });
  if (frame) d.raw(`+${'-'.repeat(d.W - 2)}+`);
  HEADERS[spec.header](d, spec);
  spec.bodies.forEach((b, i) => {
    if (i > 0 || spec.density === 'airy') d.blank();
    BODY[b](d, spec);
  });
  if (spec.decoration === 'stars') d.line('* '.repeat(Math.floor(d.W / 2)).trimEnd(), { align: 'center' });
  if (spec.decoration === 'dots') d.line('. '.repeat(Math.floor(d.W / 2)).trimEnd(), { align: 'center' });
  if (spec.decoration === 'footer') d.line(`Printed ${D.time} ${D.short}`, { align: 'center' });
  if (frame) d.raw(`+${'-'.repeat(d.W - 2)}+`);
  d.feed(spec.density === 'airy' ? 4 : 2);
  return d;
}

module.exports = { generateSpecs, buildDesign, D };
