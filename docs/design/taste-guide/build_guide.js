'use strict';
// Builds the taste guide from the lab and arena data. Run: node build_guide.js
// Writes taste-guide.html, taste-guide.md, img/ (copies of every image used), and DATA/ (timestamped backups).
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const GUIDE = __dirname;
const LAB = path.join(GUIDE, '..');
const ARENA = path.join(LAB, 'arena');
const IMG = path.join(GUIDE, 'img');
const DATA = path.join(GUIDE, 'DATA');
const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

const read = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const readText = (p) => fs.readFileSync(p, 'utf8');
const exists = (p) => fs.existsSync(p);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pct = (x) => `${Math.round(x * 100)}%`;
const mean = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0);

// ---- inputs ----------------------------------------------------------------------------
const ratings = read(path.join(LAB, 'data', 'ratings.json'));
const votes = read(path.join(ARENA, 'data', 'votes.json'));
const boards = {
  fonts: read(path.join(ARENA, 'data', 'leaderboard-fonts.json')),
  sizes: read(path.join(ARENA, 'data', 'leaderboard-sizes.json')),
  pairs: read(path.join(ARENA, 'data', 'leaderboard-pairs.json')),
  ornaments: read(path.join(ARENA, 'data', 'leaderboard-ornaments.json')),
  templates: read(path.join(ARENA, 'data', 'leaderboard-templates.json')),
};
const calibration = read(path.join(LAB, 'data', 'calibration.json'));
const modelScores = read(path.join(LAB, 'data', 'model-scores.json'));
const round4Rank = read(path.join(LAB, 'data', 'round4-model-rank.json'));
const round4Prior = read(path.join(LAB, 'data', 'round4-ranking.json'));
const designs = [1, 2, 3, 4].flatMap((n) => {
  const f = path.join(LAB, 'data', n === 1 ? 'designs.json' : `designs${n}.json`);
  return exists(f) ? read(f).map((d) => ({ ...d, lab: n, src: path.join(LAB, ['renders', 'renders2', 'renders3', 'renders4'][n - 1], `${d.id}.png`) })) : [];
});

// ---- images: every image used is copied to img/ and referenced from there ----------------
fs.mkdirSync(IMG, { recursive: true });
const copied = new Map();
function image(src, name) {
  if (!src || !exists(src)) return null;
  if (!copied.has(src)) {
    fs.copyFileSync(src, path.join(IMG, name));
    copied.set(src, `img/${name}`);
  }
  return copied.get(src);
}
const arenaSrc = (rel) => path.join(ARENA, rel.replace(/^\//, ''));
const embed = (rel) => {
  const p = path.join(GUIDE, rel);
  return exists(p) ? `data:image/png;base64,${fs.readFileSync(p).toString('base64')}` : rel;
};
const thumb = (rel, cls = 'thumb', eager = false) => (rel ? `<img class="${cls}" loading="${eager ? 'eager' : 'lazy'}" src="${eager ? embed(rel) : rel}" alt="">` : '');

// ---- rating summaries ----------------------------------------------------------------------
const cur = new Map();
for (const e of ratings.events) cur.set(e.id, e);
const byId = new Map(designs.map((d) => [d.id, d]));
const LABEL = { like: 1, dislike: -1 };
const traits = {};
for (const [id, e] of cur) {
  const d = byId.get(id);
  if (!d || !(e.rating in LABEL)) continue;
  const s = LABEL[e.rating];
  const add = (k) => (traits[k] = traits[k] || []).push(s);
  add(`decoration: ${d.decoration}`);
  add(`header: ${d.header}`);
  add(`kind: ${d.kind}`);
  add(`density: ${d.density}`);
  add(`weight: ${d.weight}`);
  add(`font: ${d.font}`);
  for (const b of d.bodies) add(`body: ${b}`);
}
const traitRows = Object.entries(traits)
  .map(([k, v]) => ({ k, mean: mean(v), n: v.length }))
  .sort((a, b) => b.mean - a.mean);

const likedIds = [...cur].filter(([, e]) => e.rating === 'like').map(([id]) => id);
const dislikedIds = [...cur].filter(([, e]) => e.rating === 'dislike').map(([id]) => id);
const roundOf = (id) => byId.get(id)?.lab ?? 1;

// ---- arena leaderboards ---------------------------------------------------------------------
const rankRows = (entries) => entries.map((e, i) => ({ ...e, rank: i + 1, wr: e.games ? e.wins / e.games : 0 }));
const fonts = rankRows(boards.fonts.entries);
const sizes = rankRows(boards.sizes.entries);
const pairs = rankRows(boards.pairs.entries);
const ornaments = rankRows(boards.ornaments.entries);
const templates = rankRows(boards.templates.entries);

function attributeWinRates(entries) {
  const groups = {};
  for (const e of entries) {
    for (const [k, v] of Object.entries(e.attributes || {})) {
      const key = `${k}: ${v}`;
      groups[key] = groups[key] || { wins: 0, games: 0 };
      groups[key].wins += e.wins;
      groups[key].games += e.games;
    }
  }
  return Object.entries(groups)
    .map(([k, g]) => ({ k, wins: g.wins, games: g.games, wr: g.games ? g.wins / g.games : 0 }))
    .filter((r) => r.games >= 4)
    .sort((a, b) => b.wr - a.wr);
}
const attrRows = attributeWinRates(boards.templates.entries);

const voteCounts = {};
for (const e of votes.events) voteCounts[e.arena] = (voteCounts[e.arena] || 0) + 1;

// ---- tables ---------------------------------------------------------------------------------
function table(rows, cols) {
  const head = cols.map((c) => `<th>${esc(c.label)}</th>`).join('');
  const body = rows
    .map((r) => `<tr>${cols.map((c) => `<td class="${c.num ? 'num' : ''}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join('')}</tr>`)
    .join('');
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
const boardCols = [
  { key: 'rank', label: '#', num: true },
  { key: 'name', label: 'Design' },
  { key: 'rating', label: 'Elo', num: true },
  { label: 'W-L', num: true, render: (r) => `${r.wins}-${r.losses}` },
  { label: 'Win rate', num: true, render: (r) => pct(r.wr) },
];

// ---- markdown mirror --------------------------------------------------------------------------
const md = [];
const mdTable = (rows, heads, row) => {
  md.push(`| ${heads.join(' | ')} |`, `| ${heads.map(() => '---').join(' | ')} |`);
  for (const r of rows) md.push(`| ${row(r).join(' | ')} |`);
  md.push('');
};

// ---- sections (HTML) ------------------------------------------------------------------------
const H = [];
const section = (id, title, html) => H.push(`<section id="${id}"><h2>${esc(title)}</h2>${html}</section>`);

// 1. Summary
const reliable = traitRows.filter((t) => t.n >= 8);
const topTraits = reliable.slice(0, 6);
const lowTraits = reliable.slice(-6).reverse();
section('summary', '1. Your taste, in short', `
<p class="lead">You like designs that look like a tool, not a poster: outlined cards, a greeting at the top, bars and rows you can read in one glance, and dot-matrix type. You dislike filled or shadowed cards, huge numbers, decorative frames, and text-only graphs.</p>
<div class="grid2">
  <div><h3>Likes</h3><ul>${topTraits.map((t) => `<li>${esc(t.k)} <span class="mono">${t.mean.toFixed(2)}</span> (${t.n} ratings)</li>`).join('')}</ul></div>
  <div><h3>Dislikes</h3><ul>${lowTraits.map((t) => `<li>${esc(t.k)} <span class="mono">${t.mean.toFixed(2)}</span> (${t.n} ratings)</li>`).join('')}</ul></div>
</div>
<p class="note">Ratings: ${ratings.events.length} events, ${cur.size} designs currently rated. Duels so far: ${Object.entries(voteCounts).map(([k, v]) => `${k} ${v}`).join(', ')}. Most arena entries have only 2 to 8 games, so treat small differences as noise.</p>`);
md.push('# Taste guide', '', '## 1. Your taste, in short', '', 'You like designs that look like a tool: outlined cards, a greeting at the top, bars and rows you can read in one glance, and dot-matrix type. You dislike filled or shadowed cards, huge numbers, decorative frames, and text-only graphs.', '');
md.push('Likes (mean +1 like, -1 dislike):', ...topTraits.map((t) => `- ${t.k}: ${t.mean.toFixed(2)} (${t.n})`), '', 'Dislikes:', ...lowTraits.map((t) => `- ${t.k}: ${t.mean.toFixed(2)} (${t.n})`), '');
md.push(`Ratings: ${ratings.events.length} events, ${cur.size} designs currently rated. Duels: ${Object.entries(voteCounts).map(([k, v]) => `${k} ${v}`).join(', ')}. Small samples: treat small differences as noise.`, '');

// 2. Rules
const T = (k) => traitRows.find((t) => t.k === k) || { mean: 0, n: 0 };
const fmt = (k) => {
  const t = T(k);
  return `${t.mean >= 0 ? '+' : ''}${t.mean.toFixed(2)} (${t.n})`;
};
const rules = [
  ['Use outlined cards only', `Outlined card ${fmt('decoration: outlined')} and outline ${fmt('decoration: outline')}. Filled ${fmt('decoration: filled')}. Elevated ${fmt('decoration: elevated')}.`],
  ['Open with a hello greeting', `Hello header ${fmt('header: hello')}. Centred headers ${fmt('header: centred')}. Wordmark headers ${fmt('header: wordmark')}.`],
  ['Show bars, rows and line graphs', `Server ${fmt('body: server')}, alert ${fmt('body: alert')}, rows ${fmt('body: rows')}, spark ${fmt('body: spark')}, energy ${fmt('body: energy')}. Text-only spark ${fmt('body: sparkText')}.`],
  ['Keep numbers moderate', `Big numerals ${fmt('body: big')}. Dense tile grids ${fmt('body: tiles')}.`],
  ['No frames around the whole ticket', `Frame decoration ${fmt('decoration: frame')}.`],
  ['No expressive shapes', `Expressive shapes ${fmt('body: expressive')}. Keep corners small or medium.`],
  ['Avoid Font B on the printer', `Font B ${fmt('font: B')}. Stay with the normal font.`],
  ['Morning and evening score close together', `Morning ${fmt('kind: morning')}, evening ${fmt('kind: evening')}. Airy ${fmt('density: airy')}, dense ${fmt('density: dense')}.`],
];
section('rules', '2. Rules for designs', `
<p>Each rule comes from your like and dislike ratings (mean score; +1 like, -1 dislike; count in brackets).</p>
<ol>${rules.map(([r, why]) => `<li><strong>${esc(r)}.</strong> <span class="why">${esc(why)}</span></li>`).join('')}</ol>`);
md.push('## 2. Rules for designs', '');
rules.forEach(([r, why], i) => md.push(`${i + 1}. **${r}.** ${why}`));
md.push('');

// 3. Fonts
const top10Fonts = fonts.slice(0, 10).map((r) => thumb(image(arenaSrc(r.image), `arena-${path.basename(r.image)}`), 'thumb', true));
const winnerSize = sizes[0];
const winnerPair = pairs[0];
const winnerSizeImg = winnerSize ? image(arenaSrc(winnerSize.image), `arena-${path.basename(winnerSize.image)}`) : null;
const winnerPairImg = winnerPair ? image(arenaSrc(winnerPair.image), `arena-${path.basename(winnerPair.image)}`) : null;
section('fonts', '3. Fonts arena', `
<p>Winner: <strong>${esc(fonts[0]?.name)}</strong> (Elo ${fonts[0]?.rating}, ${fonts[0]?.wins}-${fonts[0]?.losses}). Size winner: <strong>${esc(winnerSize?.name)}</strong>. Pair winner: <strong>${esc(winnerPair?.name)}</strong>.</p>
<div class="winners">${thumb(winnerSizeImg, 'thumb wide', true)}${thumb(winnerPairImg, 'thumb wide', true)}</div>
<h3>Top 10 fonts</h3><div class="grid5">${fonts.slice(0, 10).map((r, i) => `<figure>${top10Fonts[i]}<figcaption>#${r.rank} ${esc(r.name)}</figcaption></figure>`).join('')}</div>
<h3>Full font leaderboard (${fonts.length})</h3>${table(fonts, boardCols)}
<h3>Sizes (${sizes.length})</h3>${table(sizes, boardCols)}
<h3>Pairs (${pairs.length})</h3>${table(pairs, boardCols)}
<p class="note">Duels are still being added. Ratings start from a seed and move with Elo K=32. A both-bad result counts as a loss against a 1500 anchor.</p>`);
md.push('## 3. Fonts arena', '', `Winner: **${fonts[0]?.name}** (Elo ${fonts[0]?.rating}, ${fonts[0]?.wins}-${fonts[0]?.losses}). Size winner: **${winnerSize?.name}**. Pair winner: **${winnerPair?.name}**.`, '');
md.push('### Top 10 fonts', '');
fonts.slice(0, 10).forEach((r) => md.push(`- #${r.rank} ${r.name}, Elo ${r.rating} (${r.wins}-${r.losses}); image: ${copied.get(arenaSrc(r.image)) ?? '(missing)'}`));
md.push('', '### Full font leaderboard', '');
mdTable(fonts, ['#', 'Design', 'Elo', 'W-L', 'Win rate'], (r) => [r.rank, r.name, r.rating, `${r.wins}-${r.losses}`, pct(r.wr)]);
md.push('### Sizes', '');
mdTable(sizes, ['#', 'Design', 'Elo', 'W-L', 'Win rate'], (r) => [r.rank, r.name, r.rating, `${r.wins}-${r.losses}`, pct(r.wr)]);
md.push('### Pairs', '');
mdTable(pairs, ['#', 'Design', 'Elo', 'W-L', 'Win rate'], (r) => [r.rank, r.name, r.rating, `${r.wins}-${r.losses}`, pct(r.wr)]);

// 4. Ornaments
const orn20 = ornaments.slice(0, 20);
const orn10 = ornaments.slice(-10).reverse();
const ornFigure = (r) => `<figure>${thumb(image(arenaSrc(r.image), `orn-${path.basename(r.image)}`), 'thumb', false)}<figcaption>#${r.rank} ${esc(r.name)} · ${r.rating}</figcaption></figure>`;
section('ornaments', '4. Ornaments arena', `
<h3>Top 20</h3><div class="grid5">${orn20.map(ornFigure).join('')}</div>
<h3>Bottom 10</h3><div class="grid5">${orn10.map(ornFigure).join('')}</div>
<h3>Full ornament leaderboard (${ornaments.length})</h3>${table(ornaments, boardCols)}
<p class="note">Ornaments have few games each (most 2 to 4). Read the order as a rough guide, not a verdict.</p>`);
md.push('## 4. Ornaments arena', '', '### Top 20', '');
orn20.forEach((r) => md.push(`- #${r.rank} ${r.name}, Elo ${r.rating} (${r.wins}-${r.losses})`));
md.push('', '### Bottom 10', '');
orn10.forEach((r) => md.push(`- #${r.rank} ${r.name}, Elo ${r.rating} (${r.wins}-${r.losses})`));
md.push('');

// 5. Templates
const likedHtml = likedIds
  .map((id) => {
    const d = byId.get(id);
    return `<figure>${thumb(image(d.src, `lab-${id}.png`), 'thumb', false)}<figcaption>${esc(id)} ${esc(d.name)}</figcaption></figure>`;
  })
  .join('');
const dislikedHtml = dislikedIds
  .map((id) => {
    const d = byId.get(id);
    return `<figure>${thumb(image(d.src, `lab-${id}.png`), 'thumb', false)}<figcaption>${esc(id)} ${esc(d.name)}</figcaption></figure>`;
  })
  .join('');
const byRound = [1, 2, 3, 4].map((n) => {
  const ids = designs.filter((d) => d.lab === n).map((d) => d.id);
  const l = ids.filter((id) => cur.get(id)?.rating === 'like').length;
  const dl = ids.filter((id) => cur.get(id)?.rating === 'dislike').length;
  return { round: n, total: ids.length, liked: l, disliked: dl };
});
section('templates', '5. Templates', `
<h3>Lab ratings by round</h3>
${table(byRound, [{ key: 'round', label: 'Round' }, { key: 'total', label: 'Designs', num: true }, { key: 'liked', label: 'Liked', num: true }, { key: 'disliked', label: 'Disliked', num: true }])}
<h3>Liked (${likedIds.length})</h3><div class="grid5">${likedHtml}</div>
<h3>Disliked (${dislikedIds.length})</h3><div class="grid5">${dislikedHtml}</div>
<h3>Template duel leaderboard (${templates.length})</h3>${table(templates.slice(0, 40), boardCols)}
<p class="note">Top 40 shown. The full list is in DATA/ and in taste-guide.md.</p>
<h3>Attribute win rates (duels, at least 4 games)</h3>${table(attrRows.slice(0, 30), [{ key: 'k', label: 'Attribute' }, { key: 'wins', label: 'Wins', num: true }, { key: 'games', label: 'Games', num: true }, { label: 'Win rate', num: true, render: (r) => pct(r.wr) }])}`);
md.push('## 5. Templates', '', '### Lab ratings by round', '');
mdTable(byRound, ['Round', 'Designs', 'Liked', 'Disliked'], (r) => [r.round, r.total, r.liked, r.disliked]);
md.push(`### Liked (${likedIds.length})`, '', likedIds.map((id) => `- ${id} ${byId.get(id).name}`).join('\n'), '');
md.push(`### Disliked (${dislikedIds.length})`, '', dislikedIds.map((id) => `- ${id} ${byId.get(id).name}`).join('\n'), '');
md.push('### Template duel leaderboard (top 40)', '');
mdTable(templates.slice(0, 40), ['#', 'Design', 'Elo', 'W-L', 'Win rate'], (r) => [r.rank, r.name, r.rating, `${r.wins}-${r.losses}`, pct(r.wr)]);
md.push('### Attribute win rates (at least 4 games)', '');
mdTable(attrRows.slice(0, 30), ['Attribute', 'Wins', 'Games', 'Win rate'], (r) => [r.k, r.wins, r.games, pct(r.wr)]);

// 6. d1 model
const q = calibration.questions;
const qRows = Object.entries(q).sort((a, b) => Math.abs(b[1].correlation) - Math.abs(a[1].correlation));
section('model', '6. What the d1 model said', `
<p>The d1 model scored all ${byId.size} designs on 13 questions, twice each (${modelScores.rows.length} calls, ${modelScores.failed.length} failed). Its answers are deterministic: the two runs match, so repeats add nothing.</p>
<p>How well it matched your ratings (${calibration.designs} rated designs):</p>
${table(qRows.map(([k, v]) => ({ question: k, ...v })), [{ key: 'question', label: 'Question' }, { key: 'correlation', label: 'r', num: true }, { key: 'auc', label: 'AUC', num: true }, { key: 'mean_like', label: 'Mean if liked', num: true }, { key: 'mean_dislike', label: 'Mean if disliked', num: true }])}
<p class="note"><strong>Verdict:</strong> the model is a weak proxy. The best correlation is r = 0.27 (AUC 0.66). Use it to sort, not to decide. The pixelated question scored liked designs higher, so it is not measuring what it asks.</p>
<p>Round 4 ranking by the model (composite of graph readable, playful, interest, minus too much text): ${round4Rank.ranked.slice(0, 5).map((r) => r.id).join(', ')} on top. The trait ranking from your ratings put ${round4Prior.ranked.slice(0, 3).map((r) => r.id).join(', ')} on top. They disagree, so trust your ratings.</p>`);
md.push('## 6. What the d1 model said', '', `The d1 model scored all ${byId.size} designs on 13 questions, twice each. Answers are deterministic. Verdict: a weak proxy (best r = 0.27, AUC 0.66). Use it to sort, not to decide.`, '');
mdTable(qRows, ['Question', 'r', 'AUC', 'Mean if liked', 'Mean if disliked'], ([k, v]) => [k, v.correlation, v.auc, v.mean_like, v.mean_dislike]);

// 7. Recommended design system and final six
const finals = [
  { id: 'B4-014', role: 'Morning, Yannic', note: 'Hello, rows, segmented bars, outlined radius 4' },
  { id: 'B4-003', role: 'Evening, Yannic', note: 'Hello, energy rows and line graph, segmented bars' },
  { id: 'B4-010', role: 'Evening, dogs', note: 'Hello, Yannic vs Allyson comparison, dog rows' },
  { id: 'B4-012', role: 'Alert', note: 'Hello, filled alert pill, segmented bar' },
  { id: 'B2-031', role: 'Shopping list', note: 'Checkbox rows in an outlined card' },
  { id: null, role: 'Morning, Allyson', note: 'Not rendered yet. Same as B4-014 with her fields (see handoff)' },
];
const finalsHtml = finals
  .map((f) => {
    const d = f.id ? byId.get(f.id) : null;
    const img = d ? thumb(image(d.src, `final-${f.id}.png`), 'thumb', true) : '<div class="placeholder">Not rendered yet</div>';
    return `<figure>${img}<figcaption><strong>${esc(f.role)}</strong><br>${esc(f.id ?? '')} ${esc(f.note)}</figcaption></figure>`;
  })
  .join('');
section('final', '7. Recommended design system and six templates', `
<h3>Design system</h3>
<ul>
  <li><strong>Colour:</strong> black, white and one grey for dividers. Nothing else. The printer is 1-bit.</li>
  <li><strong>Type:</strong> 5x7 dot matrix, the arena's top font and pair. Body at 2x scale (14 dots, about 2 mm cap height). Numerals at 3x when a single figure matters.</li>
  <li><strong>Cards:</strong> outlined, 2-dot stroke, corner radius 4 or 8 dots, 14-dot padding, 8 to 12 dots between cards.</li>
  <li><strong>Greeting:</strong> "HELLO YANNIC" at 3x, then one summary line.</li>
  <li><strong>Data:</strong> rows with dot leaders, 10-segment bars, a 56-dot line graph. No frames, shadows, filled cards or expressive shapes.</li>
  <li><strong>Ornaments:</strong> use the arena's top 3 as dividers, sparingly. Keep the rule and the bullets.</li>
</ul>
<h3>Six final templates</h3><div class="grid3">${finalsHtml}</div>
<p class="note">Sample values only. Live values come from Home Assistant at print time (handoff-image-templates.md).</p>`);
md.push('## 7. Recommended design system and six templates', '', '### Design system', '');
md.push('- Colour: black, white and one grey for dividers.', '- Type: 5x7 dot matrix, the arena top font and pair. Body 2x scale (14 dots). Numerals 3x when one figure matters.', '- Cards: outlined, 2-dot stroke, radius 4 or 8 dots, 14-dot padding, 8 to 12 dots between cards.', '- Greeting: "HELLO YANNIC" at 3x, then one summary line.', '- Data: dot-leader rows, 10-segment bars, 56-dot line graph. No frames, shadows, filled cards or expressive shapes.', '');
md.push('### Six final templates', '');
finals.forEach((f) => md.push(`- ${f.role}: ${f.id ?? 'not rendered yet'}. ${f.note}.`));
md.push('');

// 8. Regeneration
section('regen', '8. How to regenerate this guide', `
<p>Duels are still being added, so rebuild after more votes:</p>
<pre>cd C:\\CLAUDE\\receipt-lab\\GUIDE
node build_guide.js</pre>
<p>The script reads the arena leaderboards and votes, the lab ratings and calibration, and writes taste-guide.html, taste-guide.md, img/ and a timestamped copy of every raw file in DATA/.</p>`);
md.push('## 8. How to regenerate this guide', '', '```', 'cd C:\\CLAUDE\\receipt-lab\\GUIDE', 'node build_guide.js', '```', '');

// ---- write outputs ---------------------------------------------------------------------------
const css = `
:root{color-scheme:light;--bg:#f4f4f2;--fg:#111;--muted:#666;--line:#cfcfcb;--card:#fff;--accent:#d71921;--mono:ui-monospace,Consolas,monospace;--sans:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0b0b0b;--fg:#f4f4f2;--muted:#8c8c88;--line:#2a2a28;--card:#141414;--accent:#ff3b3f}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0b0b0b;--fg:#f4f4f2;--muted:#8c8c88;--line:#2a2a28;--card:#141414;--accent:#ff3b3f}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 var(--sans);padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:16px 40px}
main{max-width:1100px;margin:0 auto;display:grid;gap:16px;min-width:0}
header h1{font:700 26px/1.1 var(--mono);text-transform:uppercase;letter-spacing:.04em;margin:0}
nav a{color:var(--muted);text-decoration:none;font:600 12px var(--mono);letter-spacing:.1em;text-transform:uppercase;margin-right:12px}
section{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:18px;min-width:0}
h2{font:700 18px var(--mono);text-transform:uppercase;margin:0 0 10px;letter-spacing:.04em}
h3{font:600 14px var(--mono);margin:18px 0 8px;letter-spacing:.06em;text-transform:uppercase}
.lead{font-size:17px}.note{color:var(--muted);font-size:13px}.mono{font-family:var(--mono)}
.why{color:var(--muted);font-size:13px}
.grid2{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.grid3{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.grid5{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
.winners{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));margin:8px 0}
figure{margin:0;border:1px solid var(--line);border-radius:6px;padding:8px;min-width:0;background:var(--bg)}
figcaption{font:12px/1.35 var(--mono);color:var(--muted);margin-top:6px;overflow-wrap:anywhere}
.thumb{width:100%;height:auto;display:block;image-rendering:pixelated;background:#fff}
.thumb.wide{max-width:100%}
.placeholder{padding:30px 8px;text-align:center;color:var(--muted);font:12px var(--mono);border:1px dashed var(--line)}
.scroll{overflow-x:auto;min-width:0}
table{width:100%;border-collapse:collapse;font:13px/1.4 var(--mono)}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
td.num,th:nth-child(n){white-space:nowrap}
td.num{text-align:right}
pre{background:var(--bg);border:1px solid var(--line);padding:10px;border-radius:4px;overflow-x:auto;font:13px var(--mono)}
ol,ul{padding-left:20px}li{margin:4px 0}
`;

const nav = [['summary', '1 Summary'], ['rules', '2 Rules'], ['fonts', '3 Fonts'], ['ornaments', '4 Ornaments'], ['templates', '5 Templates'], ['model', '6 d1 model'], ['final', '7 Final six'], ['regen', '8 Regenerate']];
const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="claude:viewport-fit-sides" content="cover">
<title>Receipt Taste Guide</title>
<style>${css}</style></head>
<body><main>
<header><h1>Receipt taste guide</h1><p class="note">Generated ${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC from the lab ratings, arena duels and d1 scores.</p>
<nav>${nav.map(([id, t]) => `<a href="#${id}">${esc(t)}</a>`).join('')}</nav></header>
${H.join('\n')}
</main></body></html>`;

fs.writeFileSync(path.join(GUIDE, 'taste-guide.html'), html);
fs.writeFileSync(path.join(GUIDE, 'taste-guide.md'), md.join('\n'));

// ---- DATA: timestamped backups of every raw file, plus a manifest ------------------------------
fs.mkdirSync(DATA, { recursive: true });
const sources = [
  path.join(LAB, 'data', 'ratings.json'),
  path.join(LAB, 'data', 'model-scores.json'),
  path.join(LAB, 'data', 'model-scores.csv'),
  path.join(LAB, 'data', 'calibration.json'),
  path.join(LAB, 'data', 'round4-ranking.json'),
  path.join(LAB, 'data', 'round4-model-rank.json'),
  ...[1, 2, 3, 4].map((n) => path.join(LAB, 'data', n === 1 ? 'designs.json' : `designs${n}.json`)),
  path.join(ARENA, 'data', 'votes.json'),
  ...['fonts', 'sizes', 'pairs', 'ornaments', 'templates'].map((k) => path.join(ARENA, 'data', `leaderboard-${k}.json`)),
  ...fs.readdirSync(path.join(LAB, 'notes')).map((f) => path.join(LAB, 'notes', f)),
  path.join(ARENA, 'assets', 'manifest.json'),
  path.join(ARENA, 'assets', 'fonts2-manifest.json'),
  path.join(ARENA, 'assets', 'templates-manifest.json'),
  path.join(ARENA, 'assets', 'fonts-winners', 'winners.json'),
  path.join(ARENA, 'LICENCES.md'),
].filter(exists);
const manifest = [];
for (const src of sources) {
  const ext = path.extname(src);
  const base = path.basename(src, ext);
  const dest = path.join(DATA, `${base}.${stamp}${ext}`);
  fs.copyFileSync(src, dest);
  const sha = crypto.createHash('sha256').update(fs.readFileSync(src)).digest('hex');
  manifest.push({ source: path.relative(LAB, src), backup: path.basename(dest), sha256: sha, bytes: fs.statSync(src).size });
}
fs.writeFileSync(path.join(DATA, `manifest.${stamp}.json`), JSON.stringify({ generatedAt: new Date().toISOString(), files: manifest }, null, 2));

console.log(`guide written: taste-guide.html, taste-guide.md (${copied.size} images in img/, ${sources.length} files backed up to DATA/, stamp ${stamp})`);
