'use strict';
// Round 3: builds raster designs, sends each to the simulator, and saves PNG, raw bytes and metadata.
// Writes data/designs3.json (the rating server reads it alongside round 1).
const fs = require('fs');
const path = require('path');
const { buildRound3 } = require('../lib/round3');
const { Doc } = require('../lib/doc');
const { encode } = require('../lib/escpos');

const ROOT = path.join(__dirname, '..');
const SIM = process.env.SIM_URL || 'http://localhost:8080';
fs.mkdirSync(path.join(ROOT, 'renders3'), { recursive: true });
fs.mkdirSync(path.join(ROOT, 'designs3'), { recursive: true });

async function simulate(bytes) {
  const res = await fetch(`${SIM}/api/simulate?format=json`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: bytes,
  });
  if (!res.ok) throw new Error(`simulator returned ${res.status}`);
  const body = await res.json();
  const ticket = body.tickets.find((t) => t.png);
  if (!ticket) throw new Error('no image returned');
  return ticket;
}

(async () => {
  const designs = buildRound3();
  const out = [];
  for (const d of designs) {
    const doc = new Doc({});
    doc.endFeed = 1; // the raster already ends at its last drawn row
    doc.raster(d.raster.w, d.raster.h, d.raster.bits);
    const bytes = encode(doc);
    const ticket = await simulate(bytes);
    const png = Buffer.from(ticket.png.replace(/^data:image\/png;base64,/, ''), 'base64');
    fs.writeFileSync(path.join(ROOT, 'renders3', `${d.id}.png`), png);
    fs.writeFileSync(path.join(ROOT, 'designs3', `${d.id}.bin`), bytes);
    const { raster, ...meta } = d;
    out.push({ ...meta, bytes: bytes.length, image: `renders3/${d.id}.png`, warnings: ticket.warnings });
    console.log(d.id, d.name, `${ticket.width}x${ticket.height}`, ticket.warnings.length ? `warnings ${ticket.warnings.length}` : '');
  }
  fs.writeFileSync(path.join(ROOT, 'data', 'designs3.json'), JSON.stringify(out, null, 2));
  console.log(`wrote ${out.length} round 3 designs`);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
