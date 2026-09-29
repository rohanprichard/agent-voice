// The floating call surface.
//
// This window is a view and a remote control: the hidden main window still owns
// the call, the microphone, and the audio pipeline. Keeping that separation means
// the pill can be replaced or closed without disturbing a live call, and it is
// why this file talks to the main process rather than starting anything itself.

import {
  ACTIVE_OPACITY,
  QUIET_OPACITY,
  RESTING_OPACITY,
  advancePhase,
  approach,
  drawThread,
  fade,
  fitCanvas,
  threadFrame,
} from "./threads.js";
import { approvalDetails, approvalSummary } from "./approval.js";
import { applyEvent, followStream } from "./stream.js";

const surface = document.getElementById("surface");
const canvas = document.getElementById("canvas");
const status = document.getElementById("status");
const callName = document.getElementById("call-name");
const callStatus = document.getElementById("call-status");
const muteButton = document.getElementById("mute");
const interruptButton = document.getElementById("interrupt");
const muteOn = document.getElementById("mute-on");
const muteOff = document.getElementById("mute-off");
const transcriptToggle = document.getElementById("transcript-toggle");
const transcriptClose = document.getElementById("transcript-close");
const transcript = document.getElementById("transcript");
const transcriptGrip = document.getElementById("transcript-grip");
const transcriptList = document.getElementById("transcript-list");
const transcriptEmpty = document.getElementById("transcript-empty");
const ringing = document.getElementById("ringing");
const ringingName = document.getElementById("ringing-name");
const acceptButton = document.getElementById("accept");
const alertButton = document.getElementById("alert-action");
const approvalCard = document.getElementById("approval");
const approvalTool = document.getElementById("approval-tool");
const approvalCommand = document.getElementById("approval-command");
const approvalExpansion = document.getElementById("approval-details");
const approvalFull = document.getElementById("approval-full");
const approvalError = document.getElementById("approval-error");
const allowButton = document.getElementById("approval-allow");
const denyButton = document.getElementById("approval-deny");
const transcriptOnly = new URLSearchParams(location.search).get("surface") === "transcript";
if (transcriptOnly) document.documentElement.dataset.surface = "transcript";

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const state = {
  callState: "connecting",
  callId: undefined,
  muted: false,
  name: "TalkToMe",
  open: false,
  // Set by the hidden window: whether each side is talking right now.
  active: { user: false, agent: false },
  // Who is ringing, until the user answers. Null once there is a call.
  ring: null,
  partial: "",
  // The approval request the agent is waiting on, from the server state.
  approval: null,
  // From the hidden window: a problem to show, and what the agent is doing.
  alert: null,
  working: false,
  transcribing: false,
  tool: "",
  // Where the window sits: "bottom" or "top-center". The main process reports
  // this value from the saved setting.
  placement: "bottom",
  // The smoothed rise into and fall out of speech, plus the opacities. These are
  // read by the animation frame, so they live outside React-style state.
  energy: { user: 0, agent: 0 },
  opacity: { user: 0.35, agent: 0.35 },
};

/**
 * Who is speaking. Used only to decide prominence, so a threshold is enough; the
 * lines themselves follow the smoothed activity.
 */
function activeSpeaker(energy) {
  const noisy = 0.12;
  const user = energy.user > noisy;
  const agent = energy.agent > noisy;
  if (user && agent) return "both";
  if (user) return "user";
  if (agent) return "agent";
  return "none";
}

const phase = { user: Math.PI + 0.12, agent: 0.38 };

// The threads follow the theme: the user line in the foreground color and the
// agent line in the muted grey. The notch mode never draws them.
const threadColors = { user: "#0a0a0a", agent: "#666666" };
function readThreadColors() {
  const style = getComputedStyle(document.documentElement);
  threadColors.user = style.getPropertyValue("--foreground").trim() || threadColors.user;
  threadColors.agent = style.getPropertyValue("--muted-foreground").trim() || threadColors.agent;
}
readThreadColors();
new MutationObserver(readThreadColors).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});

// ------------------------------------------------------------------ drawing

let geometry = null;
let dirty = true;

const resizeObserver = new ResizeObserver(() => {
  dirty = true;
});
resizeObserver.observe(canvas);

function draw() {
  const ratio = window.devicePixelRatio || 1;
  if (dirty || !geometry) {
    geometry = fitCanvas(canvas, ratio);
    dirty = false;
  }
  const { ctx, width, height } = geometry;
  ctx.clearRect(0, 0, width, height);

  // Activity is a flag from the hidden window, turned into a slow swell here: the
  // threads should rise into speech and settle out of it, not snap between sizes.
  for (const kind of ["user", "agent"]) {
    state.energy[kind] = approach(state.energy[kind], state.active[kind] ? 1 : 0);
  }

  // Prominence follows the smoothed level, not the raw one, so the threads and
  // the speaker state agree with each other.
  const speaker = activeSpeaker(state.energy);
  const both = speaker === "both";
  if (surface.dataset.speaker !== speaker) surface.dataset.speaker = speaker;

  for (const kind of ["user", "agent"]) {
    const speaking = both || speaker === kind;
    const target = speaking
      ? ACTIVE_OPACITY
      : speaker === "none"
        ? RESTING_OPACITY
        : QUIET_OPACITY;
    state.opacity[kind] = fade(state.opacity[kind], target);
    drawThread(ctx, {
      ...threadFrame({
        kind,
        level: state.energy[kind],
        opacity: state.opacity[kind],
        phase: phase[kind],
        width,
        height,
        // Just enough separation to read as two lines where they overlap. Any
        // more and they stop looking like one conversation.
        offset: kind === "user" ? -1.5 : 1.5,
      }),
      color: threadColors[kind],
    });
  }
}

function advancePhases(delta) {
  // Reduced motion keeps the amplitude and opacity response but drops the travel.
  if (reduceMotion.matches) return;
  // The smoothed level, so speed follows the drawn shape rather than the raw
  // audio, and each thread answers its own side of the conversation.
  for (const kind of ["user", "agent"]) {
    phase[kind] = advancePhase(phase[kind], kind, state.energy[kind], delta);
  }
}

let previous = performance.now();
let frame = 0;

function loop(now) {
  const delta = Math.min(now - previous, 50);
  previous = now;
  advancePhases(delta);
  draw();
  // Reply deltas arrive faster than frames. The transcript is drawn at most
  // once a frame.
  if (transcriptDirty) {
    transcriptDirty = false;
    renderTranscript(currentMessages);
  }
  frame = requestAnimationFrame(loop);
}

// ------------------------------------------------------------------- state

let ringContext = null;
let ringTimer = null;
let ringGuard = null;

// The server gives up on an ignored ring after 30 seconds (RING_TIMEOUT in
// managed.py). The surface stops its own tone a little later, so a message the
// window never heard cannot leave it ringing forever. A new ring replaces the
// guard.
const RING_GUARD_MS = 32000;

function ringTone() {
  const context = ringContext;
  if (!context || context.state !== "running") return;
  const start = context.currentTime + 0.04;
  for (const [offset, frequency] of [[0, 523], [0.32, 659]]) {
    const tone = context.createOscillator();
    const volume = context.createGain();
    const at = start + offset;
    tone.type = "sine";
    tone.frequency.value = frequency;
    volume.gain.setValueAtTime(0.0001, at);
    volume.gain.exponentialRampToValueAtTime(0.055, at + 0.025);
    volume.gain.exponentialRampToValueAtTime(0.0001, at + 0.36);
    tone.connect(volume).connect(context.destination);
    tone.start(at);
    tone.stop(at + 0.38);
  }
}

function startRing() {
  if (ringTimer !== null) return;
  const context = new AudioContext();
  ringContext = context;
  ringTimer = setInterval(ringTone, 2300);
  clearTimeout(ringGuard);
  ringGuard = setTimeout(() => {
    ringGuard = null;
    // No idle state arrived. Drop the ring here so the tone stops and the next
    // ring can start clean.
    if (state.callState === "ringing") {
      state.ring = null;
      state.callState = "idle";
      render();
    } else {
      stopRing();
    }
  }, RING_GUARD_MS);
  void context.resume().then(() => {
    if (ringContext === context) ringTone();
  }).catch(() => {});
}

function stopRing() {
  clearTimeout(ringGuard);
  ringGuard = null;
  if (ringTimer !== null) clearInterval(ringTimer);
  ringTimer = null;
  const context = ringContext;
  ringContext = null;
  if (context) void context.close().catch(() => {});
}

function render() {
  const muted = state.muted;
  muteButton.setAttribute("aria-pressed", String(muted));
  muteButton.setAttribute("aria-label", muted ? "Unmute microphone" : "Mute microphone");
  // The glyph has to change with the state. A red surface alone left the button
  // looking pressed rather than muted, with the same microphone drawn on it.
  //
  // These are SVG elements, and `hidden` is an IDL property of HTMLElement, not
  // SVGElement: assigning it sets a plain JavaScript property and never touches
  // the attribute, so the stylesheet kept drawing both glyphs at once while
  // reading the property back looked correct. The attribute is what the
  // stylesheet selects on, so the attribute is what gets toggled.
  muteOn.toggleAttribute("hidden", muted);
  muteOff.toggleAttribute("hidden", !muted);
  // The label stays "Mute", as in the design: the pressed state and the red
  // surface carry the state, and the accessible name carries the action.
  surface.dataset.state = state.callState;
  surface.dataset.muted = String(muted);
  surface.dataset.open = String(state.open);
  surface.dataset.placement = state.placement;
  const ringingNow = state.callState === "ringing" && Boolean(state.ring);
  // A ring asks one question and has no transcript. Close the panel if a stale
  // open state reached this window.
  if (ringingNow && state.open) setTranscriptOpen(false, { notify: false });
  ringing.hidden = !ringingNow;
  if (ringingNow && !transcriptOnly) startRing();
  else stopRing();
  if (ringingNow) {
    ringingName.textContent = state.ring.name || "A session";
    surface.dataset.ringId = state.ring.id || "";
  }
  callName.textContent = state.name;
  interruptButton.disabled = state.callState !== "active" || !state.active.agent;
  const alert = state.callState === "active" ? state.alert : null;
  surface.dataset.alert = String(Boolean(alert));
  alertButton.hidden = !alert;
  if (alert) {
    alertButton.textContent = ALERT_ACTIONS[alert.action] || "Dismiss";
    alertButton.dataset.action = alert.action || "dismiss";
  }
  const line = state.callState === "error"
    ? "Call stopped"
    : alert
      ? alert.text
      : state.approval
        ? "Needs approval"
        : muted
          ? "Microphone off"
          : state.active.agent
            ? "Agent speaking"
            : state.transcribing
              ? "Transcribing…"
              : state.working
                ? state.tool ? `Working · ${state.tool}` : "Working"
                : "Listening";
  if (callStatus.textContent !== line) callStatus.textContent = line;
  callStatus.title = line;
  if (state.callState === "error") status.textContent = "The call stopped";
  else if (state.callState === "connecting") status.textContent = "Connecting";
}

// The one action the pill offers for each kind of problem.
const ALERT_ACTIONS = {
  "retry-mic": "Retry mic",
  "mic-settings": "Open Settings",
  settings: "Open Settings",
};

function setTranscriptOpen(open, { notify = true } = {}) {
  if (state.open === open) return;
  state.open = open;
  transcript.hidden = !open;
  transcript.setAttribute("aria-hidden", String(!open));
  // A disclosure control keeps one accessible name and reports its state
  // through aria-expanded. Renaming it to "Close transcript" would collide with
  // the panel's own close button, leaving two controls with the same name.
  transcriptToggle.setAttribute("aria-expanded", String(open));
  render();
  // The window has to grow before the panel animates into it.
  if (notify) window.talktomeCall.setTranscriptOpen(open);
  if (open) transcriptList.scrollTop = transcriptList.scrollHeight;
}

function command(type) {
  window.talktomeCall.command(type);
}

// ------------------------------------------------------------ panel resize

// The user drags the grip, so the size has a floor that keeps the header and a
// line of text usable. The main process still clamps the size to the work area.
const MIN_TRANSCRIPT_WIDTH = 180;
const MIN_TRANSCRIPT_HEIGHT = 120;
let resizeStart = null;

function applyTranscriptSize(size) {
  if (!size) return;
  const width = Number(size.width);
  const height = Number(size.height);
  if (!Number.isFinite(width) || !Number.isFinite(height)) return;
  transcript.style.setProperty("--transcript-width", `${Math.round(width)}px`);
  transcript.style.setProperty("--transcript-height", `${Math.round(height)}px`);
}

function requestTranscriptSize(width, height) {
  window.talktomeCall?.setTranscriptSize?.({
    width: Math.max(MIN_TRANSCRIPT_WIDTH, Math.round(width)),
    height: Math.max(MIN_TRANSCRIPT_HEIGHT, Math.round(height)),
  });
}

// The panel is right-aligned, so its left edge moves when the width changes.
// The grip sits on the free corner: the top left at the bottom placement, the
// bottom left at the top center placement. Screen coordinates keep the drag
// steady while the window grows under the pointer.
transcriptGrip.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  const rect = transcript.getBoundingClientRect();
  resizeStart = {
    pointerId: event.pointerId,
    x: event.screenX,
    y: event.screenY,
    width: rect.width,
    height: rect.height,
    heightSign: state.placement === "top-center" ? 1 : -1,
  };
  transcriptGrip.setPointerCapture(event.pointerId);
  event.preventDefault();
});

transcriptGrip.addEventListener("pointermove", (event) => {
  if (!resizeStart || event.pointerId !== resizeStart.pointerId) return;
  const width = resizeStart.width - (event.screenX - resizeStart.x);
  const height =
    resizeStart.height + resizeStart.heightSign * (event.screenY - resizeStart.y);
  requestTranscriptSize(width, height);
});

function endResize(event) {
  if (!resizeStart || event.pointerId !== resizeStart.pointerId) return;
  resizeStart = null;
  if (transcriptGrip.hasPointerCapture(event.pointerId))
    transcriptGrip.releasePointerCapture(event.pointerId);
}

transcriptGrip.addEventListener("pointerup", endResize);
transcriptGrip.addEventListener("pointercancel", endResize);

// ---------------------------------------------------------------- approval

let approvalBusy = false;

function renderApproval(approval) {
  const previous = state.approval;
  state.approval = approval;
  surface.dataset.approval = String(Boolean(approval));
  if (!approval) {
    const hadFocus = approvalCard.contains(document.activeElement);
    approvalCard.hidden = true;
    approvalExpansion.open = false;
    approvalFull.textContent = "";
    approvalBusy = false;
    if (hadFocus) (transcriptOnly ? transcriptClose : transcriptToggle).focus();
    if (previous) render();
    return;
  }
  if (previous?.id === approval.id) return;
  const summary = approvalSummary(approval);
  approvalTool.textContent = summary.tool;
  approvalCommand.textContent = summary.command;
  approvalCommand.hidden = !summary.command;
  approvalExpansion.open = false;
  approvalFull.textContent = approvalDetails(approval);
  approvalCard.querySelector(".approval-content").scrollTop = 0;
  approvalError.hidden = true;
  approvalBusy = false;
  allowButton.disabled = false;
  denyButton.disabled = false;
  approvalCard.hidden = false;
  // If the window has focus, move focus to the new request.
  if (document.hasFocus()) approvalCard.focus({ preventScroll: true });
  render();
}

async function decide(allow) {
  const approval = state.approval;
  if (!approval || approvalBusy) return;
  approvalBusy = true;
  allowButton.disabled = true;
  denyButton.disabled = true;
  approvalError.hidden = true;
  try {
    const response = await fetch(`/v1/managed/approvals/${encodeURIComponent(approval.id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ allow }),
    });
    // A 409 means the request already ended. The stream removes the card.
    if (!response.ok && response.status !== 409) throw new Error(String(response.status));
  } catch {
    if (state.approval?.id !== approval.id) return;
    approvalBusy = false;
    allowButton.disabled = false;
    denyButton.disabled = false;
    approvalError.textContent = "The answer did not reach the agent. Try again.";
    approvalError.hidden = false;
  }
}

allowButton.addEventListener("click", () => void decide(true));
denyButton.addEventListener("click", () => void decide(false));

// --------------------------------------------------------------- transcript

let currentMessages = [];
let transcriptDirty = false;
// The call the rendered transcript belongs to. The room keeps a finished call's
// messages, so this decides when the panel has to start again.
let renderedCallId = null;
// The live room from the stream, and the approvals from the session.
let streamRoom = { messages: [] };
let streamApprovals = [];

function transcriptRows(messages) {
  const rows = messages.slice(-14).map((message) => ({
    kind: message.role === "user" ? "user" : "agent",
    who: message.role === "user" ? "You" : message.name || "Agent",
    text: message.text,
  }));
  if (state.partial) rows.push({ kind: "user partial", who: "You · live", text: state.partial });
  // What the agent does between replies, and a problem, are one line each at
  // the end. Neither is part of the conversation, so neither is kept.
  if (state.working && state.tool) rows.push({ kind: "status", who: "Working", text: state.tool });
  if (state.alert) rows.push({ kind: "status alert", who: "Problem", text: state.alert.text });
  return rows;
}

// Only the rows that changed are touched. A streamed reply changes one row many
// times a second, and redrawing the whole list for it made the panel flicker.
function renderTranscript(messages) {
  const rows = transcriptRows(messages);
  const items = transcriptList.children;
  while (items.length > rows.length) items[items.length - 1].remove();
  rows.forEach((row, index) => {
    let item = items[index];
    if (!item) {
      item = document.createElement("li");
      const who = document.createElement("span");
      who.className = "who";
      const said = document.createElement("span");
      said.className = "said";
      item.append(who, said);
      transcriptList.append(item);
    }
    if (item.className !== row.kind) item.className = row.kind;
    if (item.firstChild.textContent !== row.who) item.firstChild.textContent = row.who;
    if (item.lastChild.textContent !== row.text) item.lastChild.textContent = row.text;
  });
  transcriptEmpty.hidden = rows.length > 0;
  if (state.open) transcriptList.scrollTop = transcriptList.scrollHeight;
}

// The room keeps the last call's messages after it ends, so a new ring saw the
// old conversation. Keep only the messages of the call that is live now, and
// clear the panel when the call identity changes.
function showRoom() {
  const callId = state.callId ?? streamRoom.call_id ?? null;
  if (callId !== renderedCallId) {
    renderedCallId = callId;
    transcriptList.replaceChildren();
  }
  currentMessages = callId
    ? streamRoom.messages.filter((message) => message.call_id === callId)
    : [];
  transcriptDirty = true;
  renderApproval(callId ? streamApprovals[0] || null : null);
}

followStream({
  onSnapshot: ({ room, managed }) => {
    streamRoom = { ...room, messages: room.messages || [] };
    streamApprovals = managed?.approvals || [];
    showRoom();
  },
  onEvent: ({ event, room, managed }) => {
    applyEvent(streamRoom, event);
    if (room) Object.assign(streamRoom, room);
    if (managed) streamApprovals = managed.approvals || [];
    showRoom();
  },
});

// ------------------------------------------------------------------ events

muteButton.addEventListener("click", () => command("mute"));
interruptButton.addEventListener("click", () => command("interrupt"));
// The toggle and the panel's close button both need the window resized.
transcriptToggle.addEventListener("click", () => setTranscriptOpen(!state.open));
transcriptClose.addEventListener("click", () => setTranscriptOpen(false));
acceptButton.addEventListener("click", () => command("accept"));
alertButton.addEventListener("click", () => command(alertButton.dataset.action || "dismiss"));
document.getElementById("end").addEventListener("click", () => {
  // Let the closing animation play before the window is taken away.
  surface.dataset.ending = "true";
  state.callState = "ending";
  render();
  setTimeout(() => command("end"), 320);
});

document.addEventListener("keydown", (event) => {
  // The panel holds a pending approval, so Escape does not hide it.
  if (event.key === "Escape" && state.open && !state.approval) setTranscriptOpen(false);
});

window.talktomeCall.onState((next) => {
  const callChanged = next.callId !== undefined && next.callId !== state.callId;
  if (next.callId !== undefined) state.callId = next.callId;
  if (next.muted !== undefined) state.muted = next.muted;
  state.alert = next.alert || null;
  state.working = next.working === true;
  state.transcribing = next.transcribing === true;
  state.tool = typeof next.tool === "string" ? next.tool : "";
  if (next.name) state.name = next.name;
  if (next.state) state.callState = next.state;
  // Written straight into the objects the animation frame reads. Making these
  // React-style state would re-render the window on every change.
  state.active = {
    user: next.userActive === true,
    agent: next.agentActive === true,
  };
  state.ring = next.ring || null;
  if (next.partial !== undefined) state.partial = next.partial;
  if (callChanged) showRoom();
  transcriptDirty = true;
  if (next.placement === "top-center" || next.placement === "bottom") {
    state.placement = next.placement;
  }
  if (next.open !== undefined && next.open !== state.open) {
    setTranscriptOpen(next.open, { notify: false });
  }
  if (next.transcript) applyTranscriptSize(next.transcript);
  render();
});

// A hidden window must not ring. The main process hides the surface when the
// call ends, so this is a second guard behind the idle message and the timer.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden || state.callState !== "ringing") return;
  state.ring = null;
  state.callState = "idle";
  render();
});

render();
frame = requestAnimationFrame(loop);

// The window can be torn down while a frame is pending.
window.addEventListener("pagehide", () => {
  cancelAnimationFrame(frame);
  stopRing();
});
window.addEventListener("beforeunload", () => {
  cancelAnimationFrame(frame);
  stopRing();
});
