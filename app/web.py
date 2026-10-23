"""The browser UI served at /. It talks only to the JSON API. One file, no build step."""

WEB_UI = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Printarr</title>
<style>
  :root { color-scheme: light dark; --bg: #f5f5f3; --fg: #1d1d1b; --card: #fff; --line: #d7d7d2; --accent: #2f6fdb; --bad: #b3261e; }
  @media (prefers-color-scheme: dark) { :root { --bg: #161615; --fg: #ecece8; --card: #22221f; --line: #3a3a36; --accent: #7ba7ff; --bad: #f2877f; } }
  :root[data-theme="light"] { --bg: #f5f5f3; --fg: #1d1d1b; --card: #fff; --line: #d7d7d2; --accent: #2f6fdb; --bad: #b3261e; }
  :root[data-theme="dark"] { --bg: #161615; --fg: #ecece8; --card: #22221f; --line: #3a3a36; --accent: #7ba7ff; --bad: #f2877f; }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.4 system-ui, sans-serif; }
  main { max-width: 900px; margin: 0 auto; padding: 16px; display: grid; gap: 16px; }
  section { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px; }
  h1 { font-size: 22px; margin: 8px 0; } h2 { font-size: 17px; margin: 0 0 12px; }
  label { display: grid; gap: 4px; margin-bottom: 10px; font-size: 14px; }
  input, select, textarea { font: inherit; padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); width: 100%; box-sizing: border-box; }
  textarea { min-height: 96px; }
  .row { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; } @media (max-width: 600px) { .row { grid-template-columns: 1fr; } }
  .check { display: flex; gap: 8px; align-items: center; }
  .check input { width: auto; }
  button { font: inherit; padding: 8px 14px; border-radius: 6px; border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer; margin: 0 8px 8px 0; }
  button.ghost { background: transparent; color: var(--accent); }
  pre { background: var(--bg); border: 1px dashed var(--line); padding: 12px; border-radius: 6px; overflow-x: auto; font: 13px/1.3 ui-monospace, monospace; white-space: pre; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  td, th { text-align: left; padding: 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
  .status { font-weight: 600; } .err { color: var(--bad); }
  .muted { color: #888; font-size: 13px; }
</style>
</head>
<body>
<main>
  <h1>Printarr</h1>

  <section>
    <h2>Decision model</h2>
    <p class="muted">Picks a template when a ticket arrives and template is set to auto. Leave the URL empty to use the fixed rules only. Settings are saved in the database.</p>
    <div class="row">
      <label class="check"><input id="m-enabled" type="checkbox"> Use the decision model</label>
      <label>Timeout (seconds)<input id="m-timeout" type="number" min="1" max="30" step="1"></label>
    </div>
    <label>Base URL<input id="m-url" placeholder="http://ollama:11434/v1"></label>
    <div class="row">
      <label>Decision model (templates)<input id="m-model" placeholder="d1:latest"></label>
      <label>Text model (paragraphs)<input id="m-text" placeholder="granite4.2:3b"></label>
    </div>
    <button id="m-save">Save model settings</button>
    <span id="m-status" class="muted"></span>
  </section>

  <section>
    <h2>Alerts and monitoring</h2>
    <p class="muted">Telegram messages for: printer unreachable, paper out, cover open, cutter error, rendering failures, ticket failures, and decision model down. Uptime Kuma polls <code>/api/v1/health</code> (503 when the printer is down). Nothing is pushed out.</p>
    <div class="row">
      <label>Telegram bot token<input id="a-token" autocomplete="off" placeholder="leave blank to keep current"></label>
      <label>Telegram chat ID<input id="a-chat"></label>
    </div>
    <button id="a-save">Save alert settings</button>
    <button id="a-test" class="ghost">Send test message</button>
    <span id="a-status" class="muted"></span>
  </section>

  <section>
    <h2>Home Assistant</h2>
    <p class="muted">Live values and graphs are fetched from Home Assistant when a ticket prints. Use a long-lived access token.</p>
    <div class="row">
      <label>URL<input id="h-url" placeholder="http://192.168.1.10:8123"></label>
      <label>Access token<input id="h-token" autocomplete="off" placeholder="leave blank to keep current"></label>
    </div>
    <button id="h-save">Save Home Assistant</button>
    <button id="h-test" class="ghost">Test connection</button>
    <span id="h-status" class="muted"></span>
  </section>

  <section>
    <h2>New ticket</h2>
    <div class="row">
      <label>Recipient
        <select id="t-recipient">
          <option value="yannic">Yannic</option>
          <option value="wife">Allyson</option>
        </select>
      </label>
      <label>Template
        <select id="t-template"></select>
      </label>
    </div>
    <div class="row">
      <label>Title (optional)<input id="t-title" maxlength="80"></label>
      <label>From (optional)<input id="t-sender" maxlength="40" placeholder="hermes"></label>
    </div>
    <label>Message<textarea id="t-message" maxlength="2000"></textarea></label>
    <div class="row">
      <label>Print at (optional)<input id="t-when" type="datetime-local"></label>
      <div>
        <label class="check"><input id="t-hold" type="checkbox"> Hold until released</label>
        <label>Hold name<input id="t-hold-key" placeholder="user-home"></label>
      </div>
    </div>
    <button id="t-preview" class="ghost">Preview</button>
    <button id="t-send">Queue ticket</button>
    <span id="t-status" class="muted"></span>
    <pre id="t-output" hidden></pre>
  </section>

  <section>
    <h2>Tickets</h2>
    <button id="refresh" class="ghost">Refresh</button>
    <table>
      <thead><tr><th>Status</th><th>To</th><th>Message</th><th>Template</th><th>Actions</th></tr></thead>
      <tbody id="tickets"></tbody>
    </table>
  </section>
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
async function loadTemplates() {
  const templates = await api('/templates');
  const select = $('t-template');
  select.innerHTML = '<option value="auto">Auto (model or rules)</option>';
  for (const t of templates) {
    const option = document.createElement('option');
    option.value = t.id; option.dataset.recipient = t.recipient;
    option.textContent = `${t.id}: ${t.name} (${t.recipient})`;
    select.appendChild(option);
  }
  filterTemplates();
}
function filterTemplates() {
  const recipient = $('t-recipient').value;
  for (const option of $('t-template').options) {
    option.hidden = !!option.dataset.recipient && option.dataset.recipient !== recipient;
  }
  $('t-template').value = 'auto';
}
function ticketBody() {
  const template = $('t-template').value;
  const body = {
    recipient: $('t-recipient').value,
    message: $('t-message').value,
    template: template === 'auto' ? 'auto' : Number(template),
  };
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
async function preview() {
  try {
    const out = await api('/tickets/preview', { method: 'POST', body: JSON.stringify(ticketBody()) });
    $('t-output').hidden = false;
    $('t-output').textContent = out.text;
    show($('t-status'), `Template ${out.template_id}, chosen by ${out.selection}.`);
  } catch (e) { show($('t-status'), e.message, true); }
}
async function send() {
  try {
    const t = await api('/tickets', { method: 'POST', body: JSON.stringify(ticketBody()) });
    show($('t-status'), `Queued as ${t.status}, template ${t.template_id} (${t.selection}).`);
    $('t-message').value = '';
    loadTickets();
  } catch (e) { show($('t-status'), e.message, true); }
}
async function act(path) {
  try { await api(path, { method: 'POST' }); loadTickets(); }
  catch (e) { alert(e.message); }
}
async function loadTickets() {
  const tickets = await api('/tickets?limit=50');
  const rows = tickets.map((t) => {
    const actions = [];
    if (t.status === 'held') actions.push(`<button class="ghost" data-act="/tickets/${t.id}/release">Release</button>`);
    if (t.status === 'pending') actions.push(`<button class="ghost" data-act="/tickets/${t.id}/cancel">Cancel</button>`);
    if (t.status === 'failed' || t.status === 'cancelled') actions.push(`<button class="ghost" data-act="/tickets/${t.id}/retry">Retry</button>`);
    const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    return `<tr><td class="status">${t.status}</td><td>${esc(t.recipient)}</td>
      <td>${esc(t.title ? t.title + ': ' : '')}${esc(t.message).slice(0, 80)}</td>
      <td>${t.template_id} <span class="muted">${t.selection}</span></td><td>${actions.join('')}</td></tr>`;
  });
  $('tickets').innerHTML = rows.join('') || '<tr><td colspan="5" class="muted">No tickets yet.</td></tr>';
}

$('m-save').onclick = saveModel;
$('a-save').onclick = saveAlerts;
$('h-save').onclick = saveHA;
$('h-test').onclick = testHA;
$('a-test').onclick = testAlert;
$('t-recipient').onchange = filterTemplates;
$('t-preview').onclick = preview;
$('t-send').onclick = send;
$('t-hold').onchange = () => { $('t-when').disabled = $('t-hold').checked; };
$('refresh').onclick = loadTickets;
$('tickets').onclick = (e) => { const path = e.target.dataset.act; if (path) act(path); };

loadModel().catch((e) => show($('m-status'), e.message, true));
loadAlerts().catch((e) => show($('a-status'), e.message, true));
loadHA().catch((e) => show($('h-status'), e.message, true));
loadTemplates().catch((e) => show($('t-status'), e.message, true));
loadTickets().catch(() => {});
setInterval(loadTickets, 10000);
</script>
</body>
</html>
"""
