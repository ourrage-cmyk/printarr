'use strict';
// Layout builder. Text lines are padded here, so the printer only sees finished rows.

class Doc {
  constructor({ font = 'A', frame = false, bodyBold = true }) {
    this.font = font;
    this.frame = frame;
    this.bodyBold = bodyBold;
    this.W = font === 'B' ? 56 : 42;
    this.inner = frame ? this.W - 4 : this.W;
    this.ops = [];
  }

  cells(size) {
    return size === 2 ? Math.floor(this.inner / 2) : this.inner;
  }

  // One padded text line. Size 2 is double width and height. Frames box the line and drop size 2.
  line(s, { align = 'left', bold = this.bodyBold, size = 1, invert = false } = {}) {
    if (this.frame) size = 1;
    const cells = this.cells(size);
    const t = s.length > cells ? s.slice(0, cells) : s;
    const space = cells - t.length;
    let body = t;
    if (align === 'center') body = ' '.repeat(Math.floor(space / 2)) + t;
    else if (align === 'right') body = ' '.repeat(space) + t;
    if (this.frame) body = `| ${body.padEnd(cells)} |`;
    this.ops.push({ t: 'text', s: body, bold, size, invert });
    return this;
  }

  // Unframed text, for borders and boxes.
  raw(s, { bold = true, invert = false } = {}) {
    this.ops.push({ t: 'text', s, bold, size: 1, invert });
    return this;
  }

  heading(s, opts = {}) {
    return this.line(s, { bold: true, ...opts });
  }

  body(s, opts = {}) {
    return this.line(s, { bold: this.bodyBold, ...opts });
  }

  blank() {
    return this.line('');
  }

  rule(ch = '-') {
    return this.line(ch.repeat(this.inner));
  }

  // Word-wrapped paragraph in the current body width.
  para(text, opts = {}) {
    const cells = this.cells(opts.size || 1);
    const words = text.split(/\s+/);
    let cur = '';
    for (const w of words) {
      if (cur && cur.length + 1 + w.length > cells) {
        this.body(cur, opts);
        cur = w;
      } else {
        cur = cur ? `${cur} ${w}` : w;
      }
    }
    if (cur) this.body(cur, opts);
    return this;
  }

  // Row with label, dot leaders and a right-aligned value.
  row(label, value, unit = '') {
    const tail = unit ? `${value} ${unit}` : `${value}`;
    const dots = Math.max(2, this.inner - label.length - tail.length - 2);
    return this.body(`${label} ${'.'.repeat(dots)} ${tail}`);
  }

  // Two or more columns, each right-aligned in a fixed width.
  cols(parts, widths) {
    const s = parts.map((p, i) => (i === 0 ? String(p).padEnd(widths[i]) : String(p).padStart(widths[i]))).join('');
    return this.body(s);
  }

  raster(w, h, bits) {
    this.ops.push({ t: 'raster', w, h, bits });
    return this;
  }

  feed(n) {
    this.ops.push({ t: 'feed', n });
    return this;
  }
}

module.exports = { Doc };
