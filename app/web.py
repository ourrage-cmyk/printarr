"""The browser UI served at /. It talks only to the JSON API. One file, no build step.

Look: receipt design system (docs/design/system): outlined cards, square controls, no bold, no fills,
ink on paper, and a hello-style header. Tabs: Compose, Queue, History, Inbox, Insights, Settings.
"""

WEB_UI = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Printarr</title>
<style>
  /* Ink and paper only. Outlines, not fills. Square controls, radius 12 on cards only. */
  :root {
    color-scheme: light dark;
    --paper: #ffffff; --ink: #000000; --card-radius: 12px;
    --mono: "Cascadia Mono", Consolas, ui-monospace, "SFMono-Regular", Menlo, monospace;
    --sans: "Segoe UI", system-ui, -apple-system, sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { --paper: #000000; --ink: #ffffff; }
  }
  :root[data-theme="dark"] { --paper: #000000; --ink: #ffffff; }
  [hidden] { display: none !important; }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--paper); color: var(--ink);
    font: 15px/1.5 var(--sans); font-weight: 400;
    padding-left: max(16px, env(safe-area-inset-left, 0px));
    padding-right: max(16px, env(safe-area-inset-right, 0px));
  }
  b, strong, th { font-weight: 400; }
  .wrap { max-width: 1120px; margin: 0 auto; padding-block: 20px 56px; display: grid; gap: 14px; }

  /* Hello header: caption, headline, then one moderate number. Left aligned. */
  header { display: grid; gap: 4px; padding: 4px 2px 6px; }
  .caption { font: 11px/1.2 var(--mono); letter-spacing: .14em; text-transform: uppercase; display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
  h1 { font: 24px/1.2 var(--mono); letter-spacing: .02em; margin: 0; text-transform: uppercase; }
  .count { font: 20px/1 var(--mono); }
  .link-state { font: 11px/1 var(--mono); letter-spacing: .12em; text-transform: uppercase; }

  /* Outlined card, the only container */
  .card { border: 1px solid var(--ink); border-radius: var(--card-radius); padding: 18px; min-width: 0; background: transparent; }
  .label { font: 11px/1.2 var(--mono); letter-spacing: .14em; text-transform: uppercase; display: flex; justify-content: space-between; gap: 10px; align-items: baseline; flex-wrap: wrap; margin: 0 0 12px; }
  h2 { font: 11px/1.2 var(--mono); letter-spacing: .14em; text-transform: uppercase; margin: 0 0 10px; }
  .sub { font-size: 13px; margin: -4px 0 14px; opacity: .65; }
  .muted { opacity: .6; }
  .dotted { border: 0; border-top: 2px dotted var(--ink); margin: 14px 0; opacity: .5; }

  /* Tabs: text and an underline, no fills */
  nav.tabs { display: flex; gap: 2px; overflow-x: auto; border-bottom: 1px dotted var(--ink); }
  nav.tabs button { flex: none; background: none; border: 0; color: var(--ink); font: 12px/1 var(--mono); letter-spacing: .12em; text-transform: uppercase; padding: 10px 12px; cursor: pointer; opacity: .6; }
  nav.tabs button[aria-selected="true"] { opacity: 1; text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: 8px; }

  .compose { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 380px); gap: 14px; align-items: start; }
  @media (max-width: 880px) { .compose { grid-template-columns: 1fr; } .preview-first { order: -1; } }
  .grid2 { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; }
  .grid3 { display: grid; gap: 12px; grid-template-columns: 1fr 1fr 1fr; }
  @media (max-width: 680px) { .grid2, .grid3 { grid-template-columns: 1fr; } }
  .stack { display: grid; gap: 14px; }

  /* Fields: outlined, square */
  label.f { display: grid; gap: 6px; font: 11px/1.3 var(--mono); letter-spacing: .12em; text-transform: uppercase; }
  label.f .opt { letter-spacing: .04em; text-transform: none; opacity: .6; }
  input, select, textarea {
    font: 15px/1.45 var(--sans); color: var(--ink); background: transparent;
    border: 1px solid var(--ink); border-radius: 0; padding: 9px 10px; width: 100%; min-width: 0;
  }
  select option { background: var(--paper); color: var(--ink); }
  input:focus, select:focus, textarea:focus, button:focus-visible, summary:focus-visible { outline: 2px dotted var(--ink); outline-offset: 2px; }
  textarea { min-height: 200px; resize: vertical; font-size: 17px; line-height: 1.5; }
  .check { display: flex; gap: 10px; align-items: center; font-size: 14px; cursor: pointer; }
  .check input { width: 18px; height: 18px; margin: 0; flex: none; accent-color: var(--ink); }
  .counter { font: 11px/1 var(--mono); letter-spacing: .06em; opacity: .6; }
  .counter.near { opacity: 1; text-decoration: underline; }

  /* Segmented choice: outlined, the selected one inverted */
  .seg { display: inline-flex; border: 1px solid var(--ink); border-radius: 0; }
  .seg button { font: 12px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; background: transparent; color: var(--ink); border: 0; padding: 10px 14px; cursor: pointer; }
  .seg button + button { border-left: 1px solid var(--ink); }
  .seg button[aria-pressed="true"] { background: var(--ink); color: var(--paper); }

  /* Buttons: outlined; the primary one inverted */
  .actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 16px; }
  button.btn { font: 12px/1 var(--mono); letter-spacing: .12em; text-transform: uppercase; padding: 11px 16px; border: 1px solid var(--ink); border-radius: 0; background: transparent; color: var(--ink); cursor: pointer; }
  button.btn.solid { background: var(--ink); color: var(--paper); }
  button.btn.small { font-size: 11px; padding: 7px 10px; }
  button.btn:disabled { opacity: .35; cursor: default; }
  .status { font: 12px/1.4 var(--mono); letter-spacing: .02em; }
  .status.err { text-decoration: underline wavy; }

  details.opts { border-top: 1px dotted var(--ink); margin-top: 16px; padding-top: 14px; }
  details summary { cursor: pointer; font: 11px/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; list-style: none; }
  details summary::-webkit-details-marker { display: none; }
  details summary::before { content: "+ "; }
  details[open] summary::before { content: "- "; }
  details[open] summary { margin-bottom: 14px; }

  /* Preview: a white ticket on the card, always ink on paper */
  .preview-info { font: 11px/1.4 var(--mono); letter-spacing: .08em; text-transform: uppercase; }
  .stage { border: 1px dotted var(--ink); border-radius: var(--card-radius); padding: 16px 10px; display: flex; justify-content: center; }
  .paper { width: 100%; max-width: 360px; background: #ffffff; color: #000000; padding: 18px 14px 20px; border: 1px solid #000000; }
  .paper.stale { opacity: .5; }
  .paper pre { margin: 0; font: 11.5px/1.45 var(--mono); white-space: pre; overflow: hidden; }
  .ruler { font: 11.5px/1 var(--mono); width: 42ch; height: 8px; margin: 0 0 8px; border-bottom: 1px solid #000; background: repeating-linear-gradient(90deg, #000 0 1px, transparent 1px 1ch); }
  .paper-empty { font: 11px/1.6 var(--mono); letter-spacing: .08em; text-transform: uppercase; text-align: center; padding: 56px 8px; color: #000; }
  .paper-error { font: 13px/1.5 var(--mono); padding: 28px 6px; color: #000; text-decoration: underline wavy; }
  .hint { font: 11px/1.5 var(--mono); letter-spacing: .03em; opacity: .6; margin: 12px 2px 0; }

  /* Tables: rules only */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 10px 8px; border-bottom: 1px dotted var(--ink); vertical-align: top; }
  th { font: 10px/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; }
  .st { display: inline-flex; align-items: center; gap: 7px; font: 11px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; white-space: nowrap; }
  .st::before { content: ""; width: 7px; height: 7px; border: 1px solid var(--ink); background: transparent; }
  .st.sent::before, .st.printing::before { background: var(--ink); }
  .st.failed::before { border-style: dashed; }
  .msg { max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .empty-row { padding: 26px 8px; text-align: center; font: 12px/1.4 var(--mono); letter-spacing: .06em; text-transform: uppercase; opacity: .6; }
  .filters { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); margin-bottom: 14px; }

  /* Insights: dot-matrix bars, the length is the count */
  .bars { display: grid; gap: 10px; }
  .bar-row { display: grid; grid-template-columns: minmax(96px, 150px) minmax(0, 1fr) 48px; gap: 10px; align-items: center; font: 12px/1.2 var(--mono); }
  .bar-row .lbl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bar-row .n { text-align: right; }
  .dots { display: block; height: 14px; min-width: 2px; background-image: radial-gradient(circle, var(--ink) 1.6px, transparent 2px); background-size: 6px 6px; background-repeat: repeat-x; }
  .inbox-item { border-top: 1px dotted var(--ink); padding: 12px 0; display: grid; gap: 4px; }
  .inbox-item:first-child { border-top: 0; padding-top: 0; }
  .meta-line { font: 11px/1.4 var(--mono); letter-spacing: .05em; text-transform: uppercase; opacity: .7; }

  details.settings { border: 1px solid var(--ink); border-radius: var(--card-radius); padding: 0 18px; }
  details.settings > summary { cursor: pointer; padding: 16px 0; font: 12px/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; list-style: none; }
  details.settings > summary::-webkit-details-marker { display: none; }
  details.settings > summary::after { content: "+"; float: right; }
  details.settings[open] > summary::after { content: "-"; }
  details.settings[open] > summary { border-bottom: 1px dotted var(--ink); margin-bottom: 14px; }
  .set { padding: 0 0 18px; margin: 0 0 18px; border-bottom: 1px dotted var(--ink); }
  .set:last-child { border-bottom: 0; margin-bottom: 0; padding-bottom: 6px; }

  @media (max-width: 560px) { .card { padding: 14px; } .wrap { gap: 12px; } }
</style>
</head>
<body>
<main class="wrap">
  <header>
    <div class="caption"><span>Printarr</span><span id="link" class="link-state">Connecting</span></div>
    <h1 id="title">Compose</h1>
    <div class="count" id="queued" aria-label="Tickets waiting"></div>
  </header>

  <nav class="tabs" role="tablist" aria-label="Sections">
    <button role="tab" data-tab="compose" aria-selected="true">Compose</button>
    <button role="tab" data-tab="queue" aria-selected="false">Queue</button>
    <button role="tab" data-tab="history" aria-selected="false">History</button>
    <button role="tab" data-tab="inbox" aria-selected="false">Inbox</button>
    <button role="tab" data-tab="insights" aria-selected="false">Insights</button>
  </nav>

  <!-- Compose -->
  <div class="compose" data-tab-panel="compose">
    <section class="card">
      <h2>New ticket</h2>
      <p class="sub">Type the text. Line breaks are kept. No codes needed.</p>
      <div class="stack">
        <div class="grid2">
          <div style="display:grid;gap:6px">
            <span class="label" style="margin:0">Print for</span>
            <div id="t-recipient" class="seg" role="group" aria-label="Recipient">
              <button type="button" data-value="yannic" aria-pressed="true">Yannic</button>
              <button type="button" data-value="wife" aria-pressed="false">Allyson</button>
            </div>
          </div>
          <label class="f">Template
            <select id="t-template"></select>
          </label>
        </div>
        <div class="grid3">
          <label class="f">Kind
            <select id="t-kind"></select>
          </label>
          <label class="f">Tone
            <select id="t-tone"></select>
          </label>
          <label class="f">Left by <span class="opt">optional</span>
            <select id="t-from"></select>
          </label>
        </div>
        <label class="f">For <span class="opt">optional, with Left by it goes to their inbox</span>
          <select id="t-to"></select>
        </label>
        <label class="f">
          <span style="display:flex;justify-content:space-between;gap:8px;align-items:baseline"><span>Message</span><span id="t-count" class="counter">0 / 2000</span></span>
          <textarea id="t-message" maxlength="2000" placeholder="Dinner is at 7 tonight. Bring the good wine."></textarea>
        </label>
        <label class="check"><input id="t-clean" type="checkbox"> Tidy spelling first (voice-typed text)</label>
      </div>

      <details class="opts">
        <summary>Title, sender, timing</summary>
        <div class="stack">
          <div class="grid2">
            <label class="f">Title <span class="opt">optional</span><input id="t-title" maxlength="80" placeholder="Dinner"></label>
            <label class="f">From <span class="opt">optional, for the log</span><input id="t-sender" maxlength="40" placeholder="hermes"></label>
          </div>
          <label class="f">Print at <span class="opt">optional, your local time</span><input id="t-when" type="datetime-local"></label>
          <div class="grid2">
            <label class="check"><input id="t-hold" type="checkbox"> Hold until I release it</label>
            <label class="f">Hold name <span class="opt">optional</span><input id="t-hold-key" placeholder="user-home"></label>
          </div>
        </div>
      </details>

      <div class="actions">
        <button id="t-send" class="btn solid" disabled>Queue ticket</button>
        <span id="t-hint" class="status">Type a message to queue it.</span>
        <span id="t-status" class="status"></span>
      </div>
    </section>

    <section class="card preview-first" aria-live="polite">
      <div class="label"><span>Preview</span><span id="p-info" class="preview-info"></span></div>
      <div class="stage">
        <div id="paper" class="paper"><div class="paper-empty">Your ticket<br>appears here</div></div>
      </div>
      <p class="hint">The printer's 42-column layout. Bold and large type are not shown.</p>
    </section>
  </div>

  <!-- Queue -->
  <section class="card" data-tab-panel="queue" hidden>
    <div class="label"><span>Queue</span><button id="refresh" class="btn small">Refresh</button></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Status</th><th>To</th><th>Message</th><th>Template</th><th></th></tr></thead>
        <tbody id="tickets"></tbody>
      </table>
    </div>
  </section>

  <!-- History -->
  <section class="card" data-tab-panel="history" hidden>
    <div class="label"><span>Log</span><span id="hf-count" class="preview-info"></span></div>
    <div class="filters">
      <label class="f">Kind<select id="hf-kind"></select></label>
      <label class="f">Tone<select id="hf-tone"></select></label>
      <label class="f">Template<select id="hf-template"></select></label>
      <label class="f">Status<select id="hf-status"></select></label>
      <label class="f">To<select id="hf-recipient"></select></label>
      <label class="f">Date<select id="hf-date">
        <option value="">All time</option>
        <option value="24">Last 24 hours</option>
        <option value="168">Last 7 days</option>
        <option value="720">Last 30 days</option>
      </select></label>
    </div>
    <div class="actions" style="margin-top:0;margin-bottom:12px">
      <button id="hf-csv" class="btn small">Export CSV</button>
      <button id="hf-json" class="btn small">Export JSON</button>
      <span class="hint" style="margin:0">Exports the rows shown, up to 1000.</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>When</th><th>To</th><th>Kind</th><th>Tone</th><th>Template</th><th>Chosen by</th><th>Status</th><th>Time (ms)</th><th>Message</th></tr></thead>
        <tbody id="hf-rows"></tbody>
      </table>
    </div>
  </section>

  <!-- Inbox -->
  <section class="card" data-tab-panel="inbox" hidden>
    <div class="label"><span>Inbox</span><span id="ib-count" class="preview-info"></span></div>
    <p class="sub">Messages left for this person by the other one. Set Left by and For on the Compose tab.</p>
    <div id="ib-person" class="seg" role="group" aria-label="Whose inbox">
      <button type="button" data-value="yannic" aria-pressed="true">Yannic</button>
      <button type="button" data-value="wife" aria-pressed="false">Allyson</button>
    </div>
    <div id="ib-list" style="margin-top:14px"></div>
  </section>

  <!-- Insights -->
  <section class="card" data-tab-panel="insights" hidden>
    <div class="label"><span>Insights</span><span id="in-info" class="preview-info"></span></div>
    <div class="filters" style="grid-template-columns:repeat(auto-fill,minmax(160px,1fr))">
      <label class="f">To<select id="in-recipient"></select></label>
      <label class="f">Date<select id="in-date">
        <option value="">All time</option>
        <option value="24">Last 24 hours</option>
        <option value="168">Last 7 days</option>
        <option value="720">Last 30 days</option>
      </select></label>
    </div>
    <div id="in-body" class="stack"></div>
  </section>

  <details class="settings">
    <summary>Settings</summary>

    <div class="set">
      <h2>Template and cleanup models</h2>
      <p class="sub">The template model picks a layout when a ticket uses Auto. The cleanup model tidies voice-typed text. Leave the URL empty to use the fixed rules only.</p>
      <div class="stack">
        <label class="check"><input id="m-enabled" type="checkbox"> Use the models</label>
        <label class="f">Base URL<input id="m-url" placeholder="http://ollama:11434/v1"></label>
        <div class="grid2">
          <label class="f">Template model<input id="m-model" placeholder="d1:latest"></label>
          <label class="f">Cleanup model<input id="m-text" placeholder="granite4.2:3b"></label>
        </div>
        <label class="f">Timeout (seconds)<input id="m-timeout" type="number" min="1" max="30" step="1"></label>
      </div>
      <div class="actions"><button id="m-save" class="btn">Save model settings</button><span id="m-status" class="status"></span></div>
    </div>

    <div class="set">
      <h2>Alerts</h2>
      <p class="sub">Telegram messages for an unreachable printer, paper out, cover open, cutter errors, failed tickets and a model that is down. Uptime Kuma can poll <code>/api/v1/health</code> (503 when the printer is down).</p>
      <div class="grid2">
        <label class="f">Telegram bot token<input id="a-token" autocomplete="off" placeholder="leave blank to keep current"></label>
        <label class="f">Telegram chat ID<input id="a-chat"></label>
      </div>
      <div class="actions"><button id="a-save" class="btn">Save alerts</button><button id="a-test" class="btn">Send test message</button><span id="a-status" class="status"></span></div>
    </div>

    <div class="set">
      <h2>Home Assistant</h2>
      <p class="sub">Live values and graphs are fetched from Home Assistant when a ticket is queued. Use a long-lived access token.</p>
      <div class="grid2">
        <label class="f">URL<input id="h-url" placeholder="http://192.168.1.10:8123"></label>
        <label class="f">Access token<input id="h-token" autocomplete="off" placeholder="leave blank to keep current"></label>
      </div>
      <div class="actions"><button id="h-save" class="btn">Save Home Assistant</button><button id="h-test" class="btn">Test connection</button><span id="h-status" class="status"></span></div>
    </div>
  </details>
</main>
<script>
const $ = (id) => document.getElementById(id);
const api = (path, options = {}) => fetch('/api/v1' + path, {
  headers: { 'Content-Type': 'application/json' }, ...options,
}).then(async (r) => {
  const body = r.headers.get('content-type')?.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error(typeof body === 'string' ? body : JSON.stringify(body.detail ?? body));
  return body;
});
const show = (el, text, bad) => { el.textContent = text; el.classList.toggle('err', !!bad); };
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '');
const NAME = { yannic: 'Yannic', wife: 'Allyson' };

// Labels for the API's kinds and tones. Morning and evening are fixed products, not picked.
const KIND_LABEL = { note: 'Note', shopping: 'Shopping list', todo: 'To-do', alert: 'Heads-up', fun: 'Fun fact', reminder: 'Reminder', morning: 'Morning', evening: 'Evening' };
const CHOOSABLE_KINDS = ['note', 'shopping', 'todo', 'alert', 'fun', 'reminder'];
const TONE_LABEL = { loving: 'Loving', neutral: 'Neutral', reminder: 'Reminder', playful: 'Playful', gentle: 'Gentle warning', firm: 'Firm', urgent: 'Urgent' };
const STATUS_LABEL = { held: 'Held', pending: 'Queued', printing: 'Printing', sent: 'Sent', failed: 'Failed', cancelled: 'Cancelled' };
const CHOSEN_LABEL = { model: 'Model', rule: 'Rule', explicit: 'You' };

// Fill a select: a first "any" or "auto" option, then the items.
function fill(select, first, items) {
  select.innerHTML = '';
  select.append(new Option(first[1], first[0]));
  for (const [value, label] of items) select.append(new Option(label, value));
}
const entries = (map) => Object.entries(map);

// ---- Header and tabs -------------------------------------------------------
const TITLES = { compose: 'Compose', queue: 'Queue', history: 'History', inbox: 'Inbox', insights: 'Insights' };
function setLink(ok) {
  $('link').textContent = ok ? 'Online' : 'Offline';
  $('link').style.textDecoration = ok ? 'none' : 'underline wavy';
}
function showTab(name) {
  if (!TITLES[name]) name = 'compose';
  for (const b of document.querySelectorAll('nav.tabs button')) b.setAttribute('aria-selected', String(b.dataset.tab === name));
  for (const p of document.querySelectorAll('[data-tab-panel]')) p.hidden = p.dataset.tabPanel !== name;
  $('title').textContent = TITLES[name];
  if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  if (name === 'queue') loadTickets();
  if (name === 'history') loadHistory();
  if (name === 'inbox') loadInbox();
  if (name === 'insights') loadInsights();
}
window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));
document.querySelector('nav.tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-tab]');
  if (b) showTab(b.dataset.tab);
});

// ---- Settings (unchanged behaviour) ----------------------------------------
async function loadModel() {
  const m = await api('/settings/model');
  $('m-enabled').checked = m.enabled; $('m-url').value = m.base_url;
  $('m-model').value = m.model; $('m-text').value = m.text_model; $('m-timeout').value = m.timeout;
}
async function saveModel() {
  try {
    await api('/settings/model', { method: 'PUT', body: JSON.stringify({
      enabled: $('m-enabled').checked, base_url: $('m-url').value.trim(),
      model: $('m-model').value.trim(), text_model: $('m-text').value.trim(),
      timeout: Number($('m-timeout').value),
    }) });
    show($('m-status'), 'Saved.');
  } catch (e) { show($('m-status'), e.message, true); }
}
async function loadAlerts() {
  const a = await api('/settings/alerts');
  $('a-chat').value = a.telegram_chat_id;
  $('a-token').placeholder = a.telegram_configured ? 'saved, ends ' + a.telegram_token_hint : 'not set';
}
async function saveAlerts() {
  const body = { telegram_chat_id: $('a-chat').value.trim() };
  if ($('a-token').value.trim()) body.telegram_token = $('a-token').value.trim();
  try {
    await api('/settings/alerts', { method: 'PUT', body: JSON.stringify(body) });
    $('a-token').value = '';
    await loadAlerts();
    show($('a-status'), 'Saved.');
  } catch (e) { show($('a-status'), e.message, true); }
}
async function testAlert() {
  try { await api('/alerts/test', { method: 'POST' }); show($('a-status'), 'Test message sent.'); }
  catch (e) { show($('a-status'), e.message, true); }
}
async function loadHA() {
  const h = await api('/settings/ha');
  $('h-url').value = h.url;
  $('h-token').placeholder = h.token_configured ? 'saved, ends ' + h.token_hint : 'not set';
}
async function saveHA() {
  const body = { url: $('h-url').value.trim() };
  if ($('h-token').value.trim()) body.token = $('h-token').value.trim();
  try {
    await api('/settings/ha', { method: 'PUT', body: JSON.stringify(body) });
    $('h-token').value = '';
    await loadHA();
    show($('h-status'), 'Saved.');
  } catch (e) { show($('h-status'), e.message, true); }
}
async function testHA() {
  try { await api('/settings/ha/test', { method: 'POST' }); show($('h-status'), 'Home Assistant reachable.'); }
  catch (e) { show($('h-status'), e.message, true); }
}

// ---- Compose ---------------------------------------------------------------
let templates = [];
function recipient() {
  return $('t-recipient').querySelector('[aria-pressed="true"]').dataset.value;
}
function segChoose(group, value) {
  for (const b of group.querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.dataset.value === value));
}
async function loadTemplates() {
  templates = await api('/templates');
  const select = $('t-template');
  select.innerHTML = '';
  select.append(new Option('Auto, chosen for you', 'auto'));
  for (const t of templates) {
    const option = new Option(t.name, t.id);
    option.dataset.recipient = t.recipient;
    select.append(option);
  }
  fillFilters();
  filterTemplates();
}
function filterTemplates() {
  const current = recipient();
  for (const option of $('t-template').options) {
    option.hidden = !!option.dataset.recipient && option.dataset.recipient !== current;
  }
  $('t-template').value = 'auto';
  schedulePreview();
}
function fillCompose() {
  fill($('t-kind'), ['auto', 'Auto'], CHOOSABLE_KINDS.map((k) => [k, KIND_LABEL[k]]));
  fill($('t-tone'), ['auto', 'Auto'], entries(TONE_LABEL));
  fill($('t-from'), ['', 'Nobody'], [['yannic', 'Yannic'], ['wife', 'Allyson']]);
  fill($('t-to'), ['', 'Nobody'], [['yannic', 'Yannic'], ['wife', 'Allyson']]);
}
function fillFilters() {
  fill($('hf-kind'), ['', 'Any kind'], entries(KIND_LABEL));
  fill($('hf-tone'), ['', 'Any tone'], entries(TONE_LABEL));
  fill($('hf-template'), ['', 'Any template'], templates.map((t) => [String(t.id), t.name]));
  fill($('hf-status'), ['', 'Any status'], entries(STATUS_LABEL));
  fill($('hf-recipient'), ['', 'Anyone'], [['yannic', 'Yannic'], ['wife', 'Allyson']]);
  fill($('in-recipient'), ['', 'Anyone'], [['yannic', 'Yannic'], ['wife', 'Allyson']]);
}
$('t-recipient').addEventListener('click', (e) => {
  const button = e.target.closest('button[data-value]');
  if (!button) return;
  segChoose($('t-recipient'), button.dataset.value);
  filterTemplates();
});

function ticketBody() {
  const template = $('t-template').value;
  const body = {
    recipient: recipient(),
    message: $('t-message').value,
    template: template === 'auto' ? 'auto' : Number(template),
    text_state: $('t-clean').checked ? 'unformatted' : 'formatted',
  };
  if ($('t-kind').value !== 'auto') body.kind = $('t-kind').value;
  if ($('t-tone').value !== 'auto') body.tone = $('t-tone').value;
  if ($('t-from').value) body.from_user = $('t-from').value;
  if ($('t-to').value) body.to_user = $('t-to').value;
  if ($('t-title').value.trim()) body.title = $('t-title').value.trim();
  if ($('t-sender').value.trim()) body.sender = $('t-sender').value.trim();
  if ($('t-hold').checked) {
    body.hold = true;
    if ($('t-hold-key').value.trim()) body.hold_key = $('t-hold-key').value.trim();
  } else if ($('t-when').value) {
    body.send_at = $('t-when').value + ':00';
  }
  return body;
}

// Preview: debounced, and a stale answer never overwrites a newer one.
let previewTimer = null;
let previewSeq = 0;
function setPaper(html, stale) {
  $('paper').innerHTML = html;
  $('paper').classList.toggle('stale', !!stale);
}
function schedulePreview() {
  clearTimeout(previewTimer);
  const raw = $('t-message').value;
  const text = raw.trim();
  $('t-send').disabled = !text;
  $('t-hint').hidden = !!text;
  $('t-count').textContent = `${raw.length} / 2000`;
  $('t-count').classList.toggle('near', raw.length > 1900);
  if (!text) {
    previewSeq++;
    setPaper('<div class="paper-empty">Your ticket<br>appears here</div>');
    $('p-info').textContent = '';
    return;
  }
  $('p-info').textContent = 'Updating';
  previewTimer = setTimeout(runPreview, 600);
}
async function runPreview() {
  const seq = ++previewSeq;
  try {
    const out = await api('/tickets/preview', { method: 'POST', body: JSON.stringify(ticketBody()) });
    if (seq !== previewSeq) return;
    setPaper(`<div class="ruler" aria-hidden="true"></div><pre>${esc(out.text)}</pre>`);
    $('p-info').textContent = `Template ${out.template_id} · ${out.selection}`;
  } catch (e) {
    if (seq !== previewSeq) return;
    setPaper(`<div class="paper-error">Preview unavailable.<br><br>${esc(e.message)}</div>`, true);
    $('p-info').textContent = 'Error';
  }
}
async function send() {
  const btn = $('t-send');
  btn.disabled = true;
  show($('t-status'), 'Queuing');
  try {
    const t = await api('/tickets', { method: 'POST', body: JSON.stringify(ticketBody()) });
    show($('t-status'), `Queued, ${t.status}. Template ${t.template_id}.`);
    $('t-message').value = '';
    schedulePreview();
    loadTickets();
  } catch (e) {
    show($('t-status'), e.message, true);
  } finally {
    btn.disabled = !$('t-message').value.trim();
  }
}

// ---- Queue -----------------------------------------------------------------
async function act(path) {
  try { await api(path, { method: 'POST' }); loadTickets(); }
  catch (e) { show($('t-status'), e.message, true); }
}
async function loadTickets() {
  try {
    const tickets = await api('/tickets?limit=50');
    setLink(true);
    const queued = tickets.filter((t) => t.status === 'pending' || t.status === 'held').length;
    $('queued').textContent = `${queued} waiting`;
    const rows = tickets.map((t) => {
      const actions = [];
      if (t.status === 'held' && t.delivery !== 'on_release') actions.push(`<button class="btn small" data-act="/tickets/${t.id}/release">Release</button>`);
      if (t.status === 'pending' || t.status === 'held') actions.push(`<button class="btn small" data-act="/tickets/${t.id}/cancel">Cancel</button>`);
      if (t.status === 'failed' || t.status === 'cancelled') actions.push(`<button class="btn small" data-act="/tickets/${t.id}/retry">Retry</button>`);
      const text = (t.title ? t.title + ': ' : '') + t.message;
      return `<tr><td><span class="st ${esc(t.status)}">${esc(STATUS_LABEL[t.status] || t.status)}</span></td>
        <td>${esc(NAME[t.recipient] || t.recipient)}</td>
        <td class="msg" title="${esc(text)}">${esc(text)}</td>
        <td>Template ${t.template_id} <span class="muted">${esc(t.selection)}</span></td><td>${actions.join(' ')}</td></tr>`;
    });
    $('tickets').innerHTML = rows.join('') || '<tr><td colspan="5" class="empty-row">No tickets yet</td></tr>';
  } catch (e) {
    setLink(false);
  }
}

// ---- History ---------------------------------------------------------------
let historyRows = [];
const SINCE = () => $('hf-date').value;
function logQuery() {
  const q = new URLSearchParams({ limit: '500' });
  if ($('hf-kind').value) q.set('kind', $('hf-kind').value);
  if ($('hf-tone').value) q.set('tone', $('hf-tone').value);
  if ($('hf-template').value) q.set('template_id', $('hf-template').value);
  if ($('hf-status').value) q.set('status', $('hf-status').value);
  if ($('hf-recipient').value) q.set('recipient', $('hf-recipient').value);
  if (SINCE()) q.set('since_hours', SINCE());
  return q.toString();
}
async function loadHistory() {
  try {
    // The API returns oldest first. The table shows newest first.
    historyRows = (await api('/log?' + logQuery())).reverse();
    $('hf-count').textContent = `${historyRows.length} shown`;
    $('hf-rows').innerHTML = historyRows.map((t) => {
      const timings = [t.render_ms != null ? `render ${t.render_ms}` : '', t.print_ms != null ? `print ${t.print_ms}` : ''].filter(Boolean).join(' · ');
      return `<tr>
        <td>${esc(fmtWhen(t.created_at))}</td>
        <td>${esc(NAME[t.recipient] || t.recipient)}</td>
        <td>${esc(KIND_LABEL[t.kind] || t.kind)}</td>
        <td>${esc(TONE_LABEL[t.tone] || t.tone)}</td>
        <td>${esc(templateName(t.template_id))}</td>
        <td>${esc(CHOSEN_LABEL[t.choice_source] || t.choice_source || '')}</td>
        <td><span class="st ${esc(t.status)}">${esc(STATUS_LABEL[t.status] || t.status)}</span></td>
        <td>${esc(timings)}</td>
        <td class="msg" title="${esc(t.message)}">${esc((t.title ? t.title + ': ' : '') + t.message)}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="9" class="empty-row">Nothing matches these filters</td></tr>';
  } catch (e) {
    $('hf-count').textContent = e.message;
  }
}
function templateName(id) {
  const t = templates.find((x) => x.id === id);
  return t ? `${id} ${t.name}` : String(id);
}
// Export the rows on screen, so the filters apply. CSV quotes any field with a comma, quote or line break.
function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function exportRows(format) {
  if (format === 'json') {
    download('printarr-log.json', JSON.stringify(historyRows, null, 2), 'application/json');
    return;
  }
  const columns = ['id', 'created_at', 'recipient', 'from_user', 'to_user', 'kind', 'tone', 'template_id',
    'choice_source', 'selection', 'status', 'inbox_state', 'render_ms', 'print_ms', 'title', 'sender', 'message'];
  const cell = (v) => { const s = v == null ? '' : String(v); return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const lines = [columns.join(','), ...historyRows.map((r) => columns.map((c) => cell(r[c])).join(','))];
  download('printarr-log.csv', lines.join('\r\n') + '\r\n', 'text/csv');
}

// ---- Inbox -----------------------------------------------------------------
let inboxPerson = 'yannic';
async function loadInbox() {
  try {
    const rows = await api('/log?limit=500&recipient=' + inboxPerson);
    const items = rows.filter((t) => t.from_user && t.to_user === inboxPerson).reverse();
    const open = items.filter((t) => t.inbox_state !== 'seen').length;
    $('ib-count').textContent = `${open} open`;
    $('ib-list').innerHTML = items.map((t) => `
      <div class="inbox-item">
        <div class="meta-line">From ${esc(NAME[t.from_user] || t.from_user)} · ${esc(fmtWhen(t.created_at))} · <span class="st ${t.inbox_state === 'unread' ? 'sent' : ''}">${esc(t.inbox_state || '')}</span></div>
        <div>${esc(t.message)}</div>
        <div class="meta-line">${esc(KIND_LABEL[t.kind] || t.kind)} · ${esc(TONE_LABEL[t.tone] || t.tone)}</div>
      </div>`).join('') || '<p class="empty-row" style="padding:18px 0">No messages left for ' + esc(NAME[inboxPerson]) + ' yet</p>';
  } catch (e) {
    $('ib-count').textContent = e.message;
  }
}

// ---- Insights --------------------------------------------------------------
async function loadInsights() {
  const q = new URLSearchParams();
  if ($('in-recipient').value) q.set('recipient', $('in-recipient').value);
  if ($('in-date').value) q.set('since_hours', $('in-date').value);
  try {
    const s = await api('/log/summary?' + q.toString());
    const total = Object.values(s.by_kind || {}).reduce((a, b) => a + b, 0);
    $('in-info').textContent = `${total} tickets`;
    const section = (title, map, label) => {
      const rows = entries(map || {}).sort((a, b) => b[1] - a[1]);
      const max = Math.max(1, ...rows.map((r) => r[1]));
      const body = rows.map(([k, n]) => `
        <div class="bar-row">
          <span class="lbl">${esc(label(k))}</span>
          <span><i class="dots" style="width:${Math.max(2, (n / max) * 100)}%"></i></span>
          <span class="n">${n}</span>
        </div>`).join('') || '<p class="empty-row" style="padding:8px 0">No data yet</p>';
      return `<div><h2>${esc(title)}</h2><div class="bars">${body}</div></div>`;
    };
    $('in-body').innerHTML = [
      section('By kind', s.by_kind, (k) => KIND_LABEL[k] || k),
      section('By tone', s.by_tone, (k) => TONE_LABEL[k] || k),
      section('By template', s.by_template, (k) => templateName(Number(k))),
      section('How it was chosen', s.by_choice, (k) => CHOSEN_LABEL[k] || k),
      section('Status', s.by_status, (k) => STATUS_LABEL[k] || k),
    ].join('<hr class="dotted">');
  } catch (e) {
    $('in-body').textContent = e.message;
  }
}

// ---- Wiring ----------------------------------------------------------------
$('t-template').onchange = schedulePreview;
$('t-clean').onchange = schedulePreview;
$('t-kind').onchange = schedulePreview;
$('t-tone').onchange = schedulePreview;
$('t-from').onchange = schedulePreview;
$('t-to').onchange = schedulePreview;
$('t-message').addEventListener('input', schedulePreview);
$('t-title').addEventListener('input', schedulePreview);
$('t-sender').addEventListener('input', schedulePreview);
$('t-send').onclick = send;
$('t-hold').onchange = () => { $('t-when').disabled = $('t-hold').checked; };
$('refresh').onclick = loadTickets;
$('tickets').onclick = (e) => { const path = e.target.dataset.act; if (path) act(path); };
for (const id of ['hf-kind', 'hf-tone', 'hf-template', 'hf-status', 'hf-recipient', 'hf-date']) $(id).onchange = loadHistory;
for (const id of ['in-recipient', 'in-date']) $(id).onchange = loadInsights;
$('hf-csv').onclick = () => exportRows('csv');
$('hf-json').onclick = () => exportRows('json');
$('ib-person').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-value]');
  if (!b) return;
  inboxPerson = b.dataset.value;
  segChoose($('ib-person'), inboxPerson);
  loadInbox();
});
$('m-save').onclick = saveModel;
$('a-save').onclick = saveAlerts;
$('h-save').onclick = saveHA;
$('h-test').onclick = testHA;
$('a-test').onclick = testAlert;

fillCompose();
fillFilters();
loadModel().catch((e) => show($('m-status'), e.message, true));
loadAlerts().catch((e) => show($('a-status'), e.message, true));
loadHA().catch((e) => show($('h-status'), e.message, true));
loadTemplates().catch((e) => show($('t-status'), e.message, true));
loadTickets();
showTab(location.hash.slice(1));
setInterval(() => { loadTickets(); }, 10000);
</script>
</body>
</html>
"""
