'use strict';
// Writes the reference bitmap for B4-014 (morning, Yannic) so printarr's Python port can be
// checked bit for bit. Output: tests/golden/design/b4-014.bin, raw rows, 512 dots wide.
const fs = require('fs');
const path = require('path');
const { buildRound4 } = require('../lib/round4');

const design = buildRound4(20).find((d) => d.id === 'B4-014');
const out = path.join(__dirname, '..', '..', 'tests', 'golden', 'design', 'b4-014.bin');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, Buffer.from(design.raster.bits));
console.log(`wrote ${out}: ${design.raster.w}x${design.raster.h}, ${design.raster.bits.length} bytes`);
