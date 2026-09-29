import { callMeta } from "./calls-view.js";

const list = document.getElementById("calls-list");
const empty = document.getElementById("calls-empty");
const clearButton = document.getElementById("clear-history");
const alertBox = document.getElementById("calls-alert");
const alertText = document.getElementById("calls-alert-text");
const alertTerminal = document.getElementById("calls-alert-terminal");
const transcriptsNote = document.getElementById("calls-transcripts");
const claudeNote = document.getElementById("calls-claude-note");

const TRANSCRIPT_MODES = { off: "off", "7d": "kept for 7 days", "30d": "kept for 30 days" };
// Missed: a handset with a slash. Every other call: a plain handset.
const HANDSET = "M5 3.5h2l1 3-1.5 1a8 8 0 0 0 3.5 3.5l1-1.5 3 1v2a1.5 1.5 0 0 1-1.5 1.5A10.5 10.5 0 0 1 3.5 5 1.5 1.5 0 0 1 5 3.5Z";
const SLASH = "M3 3l14 14";
const TRASH = "M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10";

let calls = [];
let listKey = "";
let terminalId = null;

async function api(path, options = {}) {
  const response = await fetch(`/v1${path}`, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : {},
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message || `The request failed (${response.status}).`);
  }
  return body;
}

function icon(paths, className) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("aria-hidden", "true");
  if (className) svg.classList.add(className);
  for (const d of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, className, onClick) {
  const node = element("button", className, label);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

function showAlert(message, id = null) {
  alertText.textContent = message;
  terminalId = id;
  alertTerminal.hidden = !id;
  alertBox.hidden = !message;
}

async function callBack(call, control) {
  control.disabled = true;
  showAlert("");
  try {
    const result = await window.talktomeCalls.callBack(call.id);
    if (!result.ok) showAlert(result.message, result.action === "open_terminal" ? call.id : null);
  } catch (error) {
    showAlert(error.message);
  } finally {
    control.disabled = false;
    await load();
  }
}

async function openTerminal(id) {
  try {
    await api(`/calls/${encodeURIComponent(id)}/terminal`, { method: "POST" });
    showAlert("");
  } catch (error) {
    showAlert(error.message);
  }
}

async function toggleTranscript(call, control, panel) {
  const open = control.getAttribute("aria-expanded") === "true";
  control.setAttribute("aria-expanded", String(!open));
  panel.hidden = open;
  if (open || panel.childElementCount) return;
  try {
    const { messages } = await api(`/calls/${encodeURIComponent(call.id)}/transcript`);
    for (const message of messages) {
      const line = element("p", `transcript-line ${message.role === "user" ? "from-user" : "from-agent"}`);
      line.append(element("span", "transcript-speaker", message.role === "user" ? "You" : message.name || "Agent"));
      line.append(document.createTextNode(message.text));
      panel.append(line);
    }
  } catch (error) {
    panel.append(element("p", "transcript-line", error.message));
  }
}

async function remove(call) {
  try {
    await api(`/calls/${encodeURIComponent(call.id)}`, { method: "DELETE" });
  } catch (error) {
    showAlert(error.message);
  }
  await load();
}

function row(call) {
  const item = element("li", "call");
  item.dataset.outcome = call.outcome || "ringing";
  const missed = call.outcome === "missed";
  item.append(icon(missed ? [HANDSET, SLASH] : [HANDSET], "call-icon"));

  const body = element("div", "call-body");
  body.append(element("p", "call-name", call.name));
  const meta = element("p", "call-meta");
  meta.dataset.started = call.started_at;
  meta.textContent = callMeta(call).join(" · ");
  body.append(meta);
  if (call.callback_reason) body.append(element("p", "call-reason", call.callback_reason));
  else if (call.closed) body.append(element("p", "call-reason", "That Codex session is closed."));
  if (call.outcome === "failed" && call.error) body.append(element("p", "call-reason", call.error));
  item.append(body);

  const actions = element("div", "call-actions");
  const back = button("Call back", "secondary-button", () => void callBack(call, back));
  back.disabled = Boolean(call.callback_reason) || !call.outcome;
  if (call.callback_reason) back.title = call.callback_reason;
  actions.append(back);
  if (call.closed && call.agent === "codex")
    actions.append(button("Open in Terminal", "ghost-button", () => void openTerminal(call.id)));
  const panel = element("div", "call-transcript");
  panel.hidden = true;
  if (call.transcript) {
    const show = button("Transcript", "ghost-button", () => void toggleTranscript(call, show, panel));
    show.setAttribute("aria-expanded", "false");
    actions.append(show);
  }
  const trash = button("", "ghost-button icon-button", () => void remove(call));
  trash.setAttribute("aria-label", `Delete the call from ${call.name}`);
  trash.title = "Delete";
  trash.append(icon([TRASH]));
  actions.append(trash);
  item.append(actions, panel);
  return item;
}

function render(mode) {
  const key = JSON.stringify(calls);
  transcriptsNote.textContent = `Transcripts are ${TRANSCRIPT_MODES[mode] || "off"}. Change this in Settings.`;
  claudeNote.hidden = !calls.some((call) => call.agent === "claude");
  clearButton.disabled = !calls.length;
  empty.hidden = Boolean(calls.length);
  if (key === listKey) return;
  listKey = key;
  list.replaceChildren(...calls.map(row));
}

async function load() {
  try {
    const result = await api("/calls");
    calls = result.calls;
    render(result.transcripts);
  } catch (error) {
    showAlert(error.message);
  }
}

clearButton.addEventListener("click", async () => {
  if (!confirm("Clear the call history? This also deletes saved transcripts.")) return;
  try {
    await api("/calls", { method: "DELETE" });
  } catch (error) {
    showAlert(error.message);
  }
  await load();
});
alertTerminal.addEventListener("click", () => {
  if (terminalId) void openTerminal(terminalId);
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") window.close();
});
window.talktomeCalls?.onError?.((error) => {
  showAlert(error.message, error.action === "open_terminal" ? error.id : null);
  void load();
});

// The relative times move on without a change to the list.
setInterval(() => {
  for (const meta of list.querySelectorAll(".call-meta")) {
    const call = calls.find((entry) => entry.started_at === meta.dataset.started);
    if (call) meta.textContent = callMeta(call).join(" · ");
  }
}, 30000);

const token = new URLSearchParams(location.hash.slice(1)).get("token");
history.replaceState(null, "", location.pathname);
(async () => {
  if (token) await api("/auth", { method: "POST", body: JSON.stringify({ token }) }).catch(() => {});
  await load();
  setInterval(() => void load(), 3000);
})();
