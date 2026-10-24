'use strict';
// Round 5: one design language for every template. Dot-matrix 5x7 headline, numerals and body; outlined cards;
// light weight; hello header or none; ornaments chosen per tone from design-system/ornament-sets.json.
// No bands, rules, boxes around the ticket, centred or wordmark headers, dot/star/footer decorations, or filled cards.
const path = require('path');
const { Canvas, textWidth } = require('./raster');
const { D } = require('./designs');
const { drawers } = require('./ornaments');
const { card, pill, paragraph, metric, L, R } = require('./round2');
const SETS = require(path.join(__dirname, '..', 'design-system', 'ornament-sets.json'));

const TONES = SETS.tones;
const grid = SETS.grid;

// Draw one ornament from a tone slot (header, divider or footer) across the content width.
function ornament(c, tone, slot, x0, x1) {
  const name = TONES[tone][slot];
  const fn = drawers[name];
  if (!fn) return;
  const h = fn(c, x0, x1, c.y) || 4;
  c.y += h + 6;
}

// Sample text per tone (fictional, Yannic and Allyson are sample names).
const MESSAGES = {
  loving: 'Thank you for the coffee this morning. It made the whole day easier. Love you.',
  neutral: 'Bins go out on Thursday. The blue one is for recycling this week.',
  reminder: 'Dentist at 14:30 on Friday. Leave by 14:00 to get there in time.',
  playful: 'Did you know a group of flamingos is called a flamboyance? Just a thought for your afternoon.',
  gentle_warning: 'The washing machine is still running. Please check it before you leave the house.',
  firm_complaint: 'The hallway light has been left on all day again. Please switch it off when you leave a room.',
  urgent: 'Water leak under the kitchen sink. Turn off the stopcock now.',
};
const SIGNOFF = { loving: 'Allyson', neutral: 'Yannic', reminder: 'Allyson', playful: 'Yannic', gentle_warning: 'Yannic', firm_complaint: 'Yannic', urgent: 'Home system' };

// ---- families ----------------------------------------------------------------------------------

function morningBriefing(c, v) {
  if (v.hello) {
    card(c, v, (x0) => {
      c.text(x0, c.y, 'HELLO YANNIC', 3);
      c.y += 21 + 8;
      c.y += paragraph(c, x0, c.y, 'Cloudy, 12 C, rain after 3pm. Cheap energy until 16:00.', 2, R - L - 28) + 2;
    });
  }
  // Sleep and body battery for both, as metric tiles.
  card(c, v, (x0, x1) => {
    const cw = Math.floor((x1 - x0 - 8) / 2);
    const top = c.y;
    metric(c, x0, top, { label: 'YANNIC BATTERY', value: String(D.yannic.bodyBattery), unit: '%', scale: 3 });
    metric(c, x0 + cw + 8, top, { label: 'ALLYSON SLEEP', value: String(D.allyson.sleepScore), unit: '', scale: 3 });
    c.y = top + 52;
    c.row(x0, x1, c.y, 'STEPS', `${D.yannic.steps.toLocaleString('en-GB')} / ${D.allyson.steps.toLocaleString('en-GB')}`, 2);
    c.y += 24;
  });
  // Energy and house.
  card(c, v, (x0, x1) => {
    c.row(x0, x1, c.y, 'ENERGY NOW', `${D.energy.now.toFixed(3)} GBP`, 2);
    c.y += 24;
    c.row(x0, x1, c.y, `ENERGY ${D.energy.nextAt}`, `${D.energy.next.toFixed(3)} GBP`, 2);
    c.y += 24;
    c.row(x0, x1, c.y, 'INSIDE / OUT', `${D.house.indoor} / ${D.house.outdoor} C`, 2);
    c.y += 24;
  });
  // Outdoor graph.
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'OUTSIDE, 24 H', 2);
    c.y += 22;
    c.lineGraph(x0 + 4, c.y, x1 - 4, c.y + 60, D.outdoor24, { area: false });
    c.y += 60 + 16;
  });
  // Dogs and calendar.
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'DOGS', 2);
    c.y += 22;
    for (const [name, k] of Object.entries(D.dogs)) {
      c.row(x0, x1, c.y, name.toUpperCase(), `PEE ${k.pee} POOP ${k.poop} RUN ${k.run}`, 2);
      c.y += 24;
    }
    c.row(x0, x1, c.y, 'CALENDAR', 'NONE SET', 2);
    c.y += 24;
  });
}

function eveningRundown(c, v) {
  card(c, v, (x0) => {
    c.text(x0, c.y, 'HOME', 3);
    c.y += 21 + 8;
    c.y += paragraph(c, x0, c.y, 'Welcome back. Here is the day.', 2, R - L - 28) + 2;
  });
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'DOGS TODAY', 2);
    c.y += 22;
    for (const [name, k] of Object.entries(D.dogs)) {
      c.row(x0, x1, c.y, name.toUpperCase(), `P${k.pee} O${k.poop} F${k.food} R${k.run}`, 2);
      c.y += 24;
    }
  });
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'TODAY', 2);
    c.y += 22;
    c.row(x0, x1, c.y, 'STEPS', D.yannic.stepsEvening.toLocaleString('en-GB'), 2);
    c.y += 24;
    c.row(x0, x1, c.y, 'SAVED', `${D.energy.saved.toFixed(2)} GBP`, 2);
    c.y += 24;
  });
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'MISSED MESSAGES', 2);
    c.y += 22;
    c.row(x0, x1, c.y, 'ALLYSON 17:42', 'NEXT?', 2);
    c.y += 24;
    c.y += paragraph(c, x0, c.y, 'Can you pick up bread on the way back.', 2, x1 - x0) + 4;
  });
}

function personalTone(tone) {
  return (c, v) => {
    card(c, v, (x0, x1) => {
      ornament(c, tone, 'header', x0, x1);
      c.y += 4;
      c.y += paragraph(c, x0, c.y, MESSAGES[tone], 2, x1 - x0) + 6;
      ornament(c, tone, 'divider', x0, x1);
      c.text(x0, c.y, `- ${SIGNOFF[tone].toUpperCase()}`, 2);
      c.y += 24;
    });
  };
}

function shoppingList(c, v) {
  card(c, v, (x0, x1) => {
    pill(c, v, x0, x0 + 150, c.y, 'SHOPPING', { scale: 2 });
    c.y += 7 * 2 + 14 + 12;
    for (const item of D.list.slice(0, 7)) {
      c.sprite(x0, c.y, 'box', 3);
      c.text(x0 + 26, c.y + 2, item.toUpperCase(), 2);
      c.y += 28;
    }
    if (v.dividers) ornament(c, 'neutral', 'divider', x0, x1);
  });
}

function todoList(c, v) {
  card(c, v, (x0, x1) => {
    c.text(x0, c.y, 'TO DO', 3);
    c.y += 21 + 10;
    const tasks = [['BINS OUT', 'THU'], ['DENTIST', 'FRI 14:30'], ['CALL BANK', 'MON'], ['BOOK SERVICE', 'SOON']];
    for (const [t, when] of tasks) {
      c.sprite(x0, c.y, v.tick ? 'check' : 'box', 3);
      c.text(x0 + 30, c.y + 2, t, 2);
      c.textRight(x1, c.y + 2, when, 2);
      c.y += 28;
    }
  });
}

function alertNormal(c, v) {
  card(c, v, (x0, x1) => {
    ornament(c, 'gentle_warning', 'header', x0, x1);
    c.sprite(x0, c.y, 'drop', 3);
    c.text(x0 + 36, c.y + 2, 'WASHER STILL ON', 2);
    c.y += 30;
    c.y += paragraph(c, x0, c.y, MESSAGES.gentle_warning, 2, x1 - x0) + 6;
    ornament(c, 'gentle_warning', 'divider', x0, x1);
    c.row(x0, x1, c.y, 'DOOR', 'SHUT', 2);
    c.y += 24;
  });
}

function alertUrgent(c, v) {
  card(c, v, (x0, x1) => {
    ornament(c, 'urgent', 'header', x0, x1);
    pill(c, v, x0, x0 + 230, c.y, 'WATER LEAK', { fill: true, scale: 2 });
    c.y += 7 * 2 + 14 + 10;
    c.y += paragraph(c, x0, c.y, MESSAGES.urgent, 2, x1 - x0) + 6;
    ornament(c, 'urgent', 'divider', x0, x1);
    c.row(x0, x1, c.y, 'ACTION', 'STOPCOCK', 2);
    c.y += 24;
  });
}

function noteFunFact(c, v) {
  card(c, v, (x0, x1) => {
    ornament(c, 'playful', 'header', x0, x1);
    c.y += 4;
    c.y += paragraph(c, x0, c.y, MESSAGES.playful, 2, x1 - x0) + 6;
    ornament(c, 'playful', 'divider', x0, x1);
    c.text(x0, c.y, 'FUN FACT', 2);
    c.y += 24;
  });
}

// Family definitions: each has variants (layout and spacing differences) on the same language.
const FAMILIES = [
  { key: 'morning', kind: 'morning', fn: morningBriefing, variants: [{ hello: true, r: 4, gap: 10 }, { hello: false, r: 8, gap: 12 }, { hello: true, r: 8, gap: 14 }] },
  { key: 'evening', kind: 'evening', fn: eveningRundown, variants: [{ r: 4, gap: 10 }, { r: 8, gap: 12 }, { r: 4, gap: 14 }] },
  ...['loving', 'neutral', 'reminder', 'playful', 'gentle_warning', 'firm_complaint'].map((tone) => ({
    key: `personal_${tone}`,
    kind: 'note',
    fn: personalTone(tone),
    variants: [{ r: 4, gap: 10 }, { r: 8, gap: 12 }],
  })),
  { key: 'shopping', kind: 'list', fn: shoppingList, variants: [{ r: 4, gap: 10, dividers: false }, { r: 8, gap: 12, dividers: true }] },
  { key: 'todo', kind: 'list', fn: todoList, variants: [{ r: 4, gap: 10, tick: false }, { r: 8, gap: 12, tick: true }] },
  { key: 'alert_normal', kind: 'alert', fn: alertNormal, variants: [{ r: 4, gap: 10 }, { r: 8, gap: 12 }] },
  { key: 'alert_urgent', kind: 'alert', fn: alertUrgent, variants: [{ r: 4, gap: 10 }, { r: 8, gap: 12 }] },
  { key: 'note_fun_fact', kind: 'note', fn: noteFunFact, variants: [{ r: 4, gap: 10 }, { r: 8, gap: 12 }, { r: 4, gap: 14 }] },
];

function drawDesign(family, v) {
  const c = new Canvas();
  c.y = 14;
  family.fn(c, { ...v, thick: false });
  return c;
}

function buildRound5() {
  const designs = [];
  let n = 0;
  for (const fam of FAMILIES) {
    fam.variants.forEach((v, vi) => {
      n += 1;
      const id = `B5-${String(n).padStart(3, '0')}`;
      const measure = drawDesign(fam, v);
      void measure;
      const c = drawDesign(fam, v);
      const img = c.crop(12);
      designs.push({
        id,
        name: `${fam.key.replace(/_/g, ' ')} · v${vi + 1}`,
        round: 5,
        family: fam.key,
        kind: fam.kind,
        header: v.hello ? 'hello' : 'none',
        bodies: [fam.key],
        decoration: 'outlined',
        density: v.gap >= 12 ? 'airy' : 'dense',
        weight: 'light',
        font: 'dot5x7',
        tone: fam.key.startsWith('personal_') ? fam.key.slice(9) : (SETS.families[fam.key]?.tone ?? 'neutral'),
        d1_questions: SETS.families[fam.key]?.d1_questions ?? [],
        inspiredBy: 'arena ornament winners and round 4 outlined cards',
        ideas: 'outlined cards, dot-matrix type, one ornament set per tone',
        variant: v,
        width: 512,
        height: img.h,
        raster: img,
      });
    });
  }
  return designs;
}

module.exports = { buildRound5, FAMILIES, TONES, MESSAGES, textWidth };
