"""The first-run wizard page. Served at / until setup is finished, then the normal web page takes over."""

SETUP_UI = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>printarr setup</title>
<style>
  :root { --ink:#15181c; --muted:#5d6670; --line:#c9ced4; --paper:#fbfbf9; --ok:#1d7a3e; --bad:#a3262e; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { --ink:#eef0f2; --muted:#9aa3ad; --line:#3a4149; --paper:#16191d; --ok:#5fc27e; --bad:#ff7b7b; }
  }
  :root[data-theme="dark"] { --ink:#eef0f2; --muted:#9aa3ad; --line:#3a4149; --paper:#16191d; --ok:#5fc27e; --bad:#ff7b7b; }
  body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.45 system-ui, sans-serif; }
  main { max-width:640px; margin:0 auto; padding:24px 16px 64px; }
  h1 { font-size:24px; font-weight:300; margin:0 0 4px; }
  h2 { font-size:16px; font-weight:500; margin:0 0 8px; }
  p.lead, .hint { color:var(--muted); font-size:14px; margin:4px 0 12px; }
  fieldset { border:1px solid var(--line); border-radius:6px; margin:0 0 16px; padding:14px; }
  legend { padding:0 6px; font-size:14px; color:var(--muted); }
  label { display:block; font-size:14px; margin:8px 0 2px; }
  input { width:100%; box-sizing:border-box; font:inherit; padding:8px; border:1px solid var(--line); border-radius:4px; background:transparent; color:var(--ink); }
  .row { display:flex; gap:8px; align-items:center; margin-top:10px; flex-wrap:wrap; }
  button { font:inherit; padding:8px 14px; border:1px solid var(--ink); border-radius:4px; background:transparent; color:var(--ink); cursor:pointer; }
  button.primary { background:var(--ink); color:var(--paper); }
  button:disabled { opacity:.5; cursor:default; }
  .result { font-size:14px; }
  .result.ok { color:var(--ok); } .result.bad { color:var(--bad); }
  .check { display:flex; align-items:center; gap:10px; margin-top:6px; }
  input[type="checkbox"] { width:auto; }
  .edit-only { display:none; }
  body.editing .edit-only { display:block; }
  body.editing .edit-only.check { display:flex; }
  #finish-msg { margin-top:12px; }
</style>
</head>
<body>
<main>
  <h1 id="title">Set up printarr</h1>
  <p class="lead" id="lead">Enter the setup code from the printarr log (<code>docker logs</code> or the Logs tab in TrueNAS). Each service is checked before you continue. Secrets are saved in the printarr data folder and are never shown again.</p>

  <fieldset>
    <legend>Printer</legend>
    <label for="printer_host">IP address or host name</label>
    <input id="printer_host" placeholder="192.168.1.50">
    <label for="printer_port">Port</label>
    <input id="printer_port" type="number" min="1" max="65535">
    <div class="row"><button type="button" data-check="printer">Test</button><span class="result" data-result="printer"></span></div>
  </fieldset>

  <fieldset>
    <legend>Setup code</legend>
    <label for="code">Setup code</label>
    <input id="code" autocomplete="off" spellcheck="false" placeholder="from the log, printed at start">
  </fieldset>

  <fieldset>
    <legend>Home Assistant</legend>
    <label for="ha_url">Address</label>
    <input id="ha_url" placeholder="http://192.168.1.10:8123">
    <label for="ha_token">Long-lived access token</label>
    <input id="ha_token" type="password" autocomplete="off" placeholder="paste to set or replace">
    <div class="hint" id="ha_token_state"></div>
    <div class="check edit-only"><input id="clear_ha_token" type="checkbox"><label for="clear_ha_token" style="margin:0">Remove the saved token</label></div>
    <div class="row"><button type="button" data-check="home_assistant">Test</button><span class="result" data-result="home_assistant"></span></div>
  </fieldset>

  <fieldset>
    <legend>Model server (optional, Ollama)</legend>
    <div class="check"><input id="llm_enabled" type="checkbox" checked><label for="llm_enabled" style="margin:0">Use the model server to choose templates and clean up text</label></div>
    <label for="llm_base_url">OpenAI-compatible address</label>
    <input id="llm_base_url" placeholder="http://192.168.1.231:11434/v1">
    <label for="llm_model">Template model</label>
    <input id="llm_model">
    <label for="llm_text_model">Text clean-up model</label>
    <input id="llm_text_model">
    <div class="row"><button type="button" data-check="model_server">Test</button><span class="result" data-result="model_server"></span></div>
  </fieldset>

  <fieldset>
    <legend>Telegram alerts (optional)</legend>
    <label for="telegram_token">Bot token</label>
    <input id="telegram_token" type="password" autocomplete="off" placeholder="paste to set or replace">
    <div class="hint" id="telegram_token_state"></div>
    <div class="check edit-only"><input id="clear_telegram_token" type="checkbox"><label for="clear_telegram_token" style="margin:0">Remove the saved bot token</label></div>
    <label for="telegram_chat_id">Chat ID</label>
    <input id="telegram_chat_id">
    <div class="row"><button type="button" data-check="telegram">Test</button><span class="result" data-result="telegram"></span></div>
  </fieldset>

  <fieldset>
    <legend>People and time</legend>
    <label for="yannic_name">First person</label>
    <input id="yannic_name" value="Yannic">
    <label for="wife_name">Second person</label>
    <input id="wife_name" value="Allyson">
    <label for="timezone">Timezone</label>
    <input id="timezone" placeholder="Europe/London">
    <div class="row"><button type="button" data-check="timezone">Test</button><span class="result" data-result="timezone"></span></div>
  </fieldset>

  <div class="row">
    <button type="button" class="primary" id="finish">Finish setup</button>
  </div>
  <p class="hint edit-only">Changes are saved after every service you filled in passes its check. The timezone takes effect after a restart of printarr.</p>
  <p id="finish-msg" class="result"></p>
</main>
<script>
const $ = (id) => document.getElementById(id);
const FIELDS = ["ha_url","ha_token","llm_base_url","llm_model","llm_text_model","printer_host","printer_port",
  "telegram_token","telegram_chat_id","yannic_name","wife_name","timezone"];

function values() {
  const out = {
    llm_enabled: $("llm_enabled").checked,
    printer_port: Number($("printer_port").value || 9100),
    clear: ["ha_token", "telegram_token"].filter((f) => $("clear_" + f).checked),
  };
  for (const f of FIELDS) if (f !== "printer_port") out[f] = $(f).value.trim();
  return out;
}

function headers() {
  return { "Content-Type": "application/json", "X-Setup-Code": $("code").value.trim() };
}

function show(name, ok, text) {
  const el = document.querySelector(`[data-result="${name}"]`);
  el.textContent = text;
  el.className = "result " + (ok ? "ok" : "bad");
}

async function readError(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail);
  } catch { return `HTTP ${response.status}`; }
}

async function runCheck(name) {
  if (!$("code").value.trim()) { show(name, false, "Enter the setup code first."); return; }
  show(name, true, "Checking...");
  try {
    const response = await fetch(`/api/v1/setup/check/${name}`, { method: "POST", headers: headers(), body: JSON.stringify(values()) });
    if (!response.ok) { show(name, false, await readError(response)); return; }
    const result = await response.json();
    show(name, result.ok, result.detail);
  } catch (err) { show(name, false, "The printarr server did not answer."); }
}

document.querySelectorAll("[data-check]").forEach((button) => {
  button.addEventListener("click", () => runCheck(button.dataset.check));
});

$("finish").addEventListener("click", async () => {
  const msg = $("finish-msg");
  if (!$("code").value.trim()) { msg.className = "result bad"; msg.textContent = "Enter the setup code first."; return; }
  msg.className = "result"; msg.textContent = "Checking every service and saving...";
  $("finish").disabled = true;
  try {
    const response = await fetch("/api/v1/setup/complete", { method: "POST", headers: headers(), body: JSON.stringify(values()) });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      msg.className = "result bad";
      msg.textContent = typeof detail.detail === "object"
        ? "Fix these first: " + Object.entries(detail.detail).map(([k, v]) => `${k}: ${v}`).join(" ")
        : (detail.detail || `HTTP ${response.status}`);
      return;
    }
    const done = await response.json();
    msg.className = "result ok";
    msg.textContent = done.restart_needed
      ? "Saved. Restart printarr once so the timezone takes effect."
      : "Saved.";
    setTimeout(() => { location.href = "/"; }, done.restart_needed ? 6000 : 2000);
  } catch (err) {
    msg.className = "result bad"; msg.textContent = "The printarr server did not answer.";
  } finally {
    $("finish").disabled = false;
  }
});

(async () => {
  try {
    const response = await fetch("/api/v1/setup/status");
    const status = await response.json();
    if (status.complete) {
      document.body.classList.add("editing");
      $("title").textContent = "printarr settings";
      $("lead").textContent = "Change any value below. Each service you filled in is checked before anything is saved. Leave a secret blank to keep the saved one.";
      $("finish").textContent = "Save settings";
      $("finish-msg").insertAdjacentHTML("afterend", '<p class="hint"><a href="/">Back to the printarr web page</a></p>');
    }
    for (const [key, value] of Object.entries(status.fields)) {
      const el = $(key);
      if (!el) continue;
      if (el.type === "checkbox") el.checked = Boolean(value); else el.value = value ?? "";
    }
    $("ha_token_state").textContent = "Saved: " + status.secrets.ha_token;
    $("telegram_token_state").textContent = "Saved: " + status.secrets.telegram_token;
  } catch (err) { /* the form still works with empty fields */ }
})();
</script>
</body>
</html>
"""
