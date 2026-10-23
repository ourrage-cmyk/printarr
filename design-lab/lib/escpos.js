'use strict';
// ESC/POS byte builder for an 80 mm TM-T88V-style receipt (512 dots, Font A 42 cols, Font B 56 cols).
// Command bytes match printarr's app/escpos.py so the simulator draws what the printer would get.

const ESC = 0x1b;
const GS = 0x1d;
const LF = 0x0a;

function u16(v) {
  return [v & 0xff, v >> 8];
}

// The simulator reads bytes above 0x7f as Latin-1, so keep text to plain ASCII.
function ascii(s) {
  return Array.from(s.replace(/[^\x20-\x7e]/g, '?'), (c) => c.charCodeAt(0));
}

function encode(doc) {
  const out = [ESC, 0x40, ESC, 0x74, 0, ESC, 0x4d, doc.font === 'B' ? 1 : 0];
  for (const op of doc.ops) {
    if (op.t === 'text') {
      out.push(ESC, 0x45, op.bold ? 1 : 0); // ESC E
      out.push(GS, 0x21, op.size === 2 ? 0x11 : 0); // GS !
      if (op.invert) out.push(GS, 0x42, 1); // GS B
      out.push(...ascii(op.s), LF);
      if (op.invert) out.push(GS, 0x42, 0);
    } else if (op.t === 'raster') {
      const body = [48, 112, 48, 1, 1, 49, ...u16(op.w), ...u16(op.h)];
      out.push(GS, 0x28, 0x4c, ...u16(body.length + op.bits.length), ...body, ...op.bits);
      out.push(GS, 0x28, 0x4c, 2, 0, 48, 50); // print buffer
    } else if (op.t === 'feed') {
      out.push(ESC, 0x64, op.n);
    }
  }
  out.push(GS, 0x21, 0, ESC, 0x45, 0, ESC, 0x4d, 0, ESC, 0x64, doc.endFeed ?? 4, GS, 0x56, 1); // reset, feed, partial cut
  return Buffer.from(out);
}

// 1-bit bitmap, row-major, MSB first, 1 = black.
function bitmap(w, h) {
  return { w, h, bits: new Uint8Array((w / 8) * h) };
}

function setPx(bm, x, y) {
  if (x < 0 || y < 0 || x >= bm.w || y >= bm.h) return;
  bm.bits[y * (bm.w / 8) + (x >> 3)] |= 0x80 >> (x & 7);
}

function drawLine(bm, x0, y0, x1, y1) {
  const steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0), 1);
  for (let t = 0; t <= steps; t++) {
    setPx(bm, Math.round(x0 + ((x1 - x0) * t) / steps), Math.round(y0 + ((y1 - y0) * t) / steps));
  }
}

function fillRect(bm, x, y, w, h) {
  for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) setPx(bm, xx, yy);
}

module.exports = { encode, bitmap, setPx, drawLine, fillRect, ascii };
