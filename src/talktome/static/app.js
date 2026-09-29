import { Microphone } from "./audio.js";
import { agentNames } from "./onboarding-steps.js";
import { AudioQueue, currentAudioEvent } from "./playback.js";
import { WebAudioPlayer } from "./player.js";
import { RealtimeInput, supportsRealtimeRate } from "./realtime-input.js";
import { applyEvent, followStream } from "./stream.js";

const $ = (id) => document.getElementById(id);
let state = { room: { messages: [] }, speech: {} };
let paired = false;
let microphone = null;
let realtimeInput = null;
let partialTranscript = "";
let recording = false;
let transcribing = false;
let speaking = false;
let playbackEpoch = 0;
let playbackRequests = 0;
let firstAudioTurn = null;
let firstScheduledTurn = null;
let interruptionCandidate = null;
let turnSettingsBusy = false;
// A problem the user must see during a call. The Settings window is hidden
// then, so it goes to the call surface with at most one action.
let callAlert = null;
let dismissedError = null;
// Speech that ended while the last utterance was still transcribing. It is sent
// next, so nothing the user says in that time is lost.
const heldAudio = [];

function capturePlayback() {
  return {
    call_id: state.room.call_id,
    playback_epoch: state.room.playback_epoch,
    playback: player.playbackSnapshot(),
  };
}

function pauseForSpeech() {
  if (!speaking || interruptionCandidate || !state.room.call_id) return;
  interruptionCandidate = capturePlayback();
  void player.pause().catch(() => {});
}

function resumeFalseInterruption() {
  const candidate = interruptionCandidate;
  interruptionCandidate = null;
  if (candidate && candidate.call_id === state.room.call_id &&
      candidate.playback_epoch === state.room.playback_epoch) {
    void player.resume().catch(() => {});
  }
}
// The agent's speech goes through Web Audio so the call surface can measure it,
// which an <audio> element cannot offer.
const player = new WebAudioPlayer({
  onError: () =>
    callProblem("The reply audio did not play. The text is in the transcript."),
  onIdle: () => syncPlayback(),
});
const audioQueue = new AudioQueue(
  (event) => playAudio(`/audio/${event.audio_id}`, event),
  stopCurrentPlayback,
);
let modelSignature = "";
let page = "setup";
let voiceSignature = "";
let providerBusy = false;
let previewBusy = false;
let onboarding = null;
let microphonePermission = "unknown";
let permissionBusy = false;

async function readMicrophonePermission() {
  if (window.talktomeDesktop?.microphoneStatus) {
    microphonePermission = await window.talktomeDesktop.microphoneStatus();
  } else {
    try {
      const permission = await navigator.permissions.query({
        name: "microphone",
      });
      microphonePermission = permission.state;
    } catch {
      microphonePermission = "unknown";
    }
  }
}

// The desktop setup window owns onboarding. It reports completion through the
// main process, and this window records it.
function onboardingStage(stage) {
  localStorage.setItem("talktome-onboarding", stage);
  onboarding = stage === "complete" ? null : stage;
  // Setup is complete when this becomes false. The main process then hides the
  // window and keeps the app in the menu bar.
  window.talktomeDesktop?.setOnboarding?.(Boolean(onboarding));
  render();
}

function renderMicrophonePermission() {
  $("allow-microphone").classList.toggle(
    "hidden",
    microphonePermission === "granted",
  );
  $("allow-microphone").disabled =
    permissionBusy || Boolean(state.room.call_id);
  $("allow-microphone").textContent = permissionBusy
    ? "Please wait…"
    : "Allow microphone";
  $("microphone-permission-status").textContent =
    microphonePermission === "granted"
      ? "Microphone allowed"
      : microphonePermission === "denied" ||
          microphonePermission === "restricted"
        ? "Access is off. Turn on TalkToMe in System Settings."
        : "";
  $("open-microphone-settings").classList.toggle(
    "hidden",
    !window.talktomeDesktop?.openSystemSettings ||
      !["denied", "restricted"].includes(microphonePermission),
  );
}

let loginItem = { available: false, enabled: false, needsApproval: false };

function renderLoginItem() {
  $("login-item").checked = loginItem.enabled;
  $("login-item").disabled = !loginItem.available;
  $("open-login-items").classList.toggle("hidden", !loginItem.needsApproval);
  $("login-item-status").textContent = !loginItem.available
    ? "Open at login works in the installed app."
    : loginItem.needsApproval
      ? "Allow TalkToMe in System Settings → General → Login Items."
      : "";
}

window.talktomeDesktop?.loginItem?.()?.then((state) => {
  loginItem = state;
  renderLoginItem();
})?.catch(() => {});
renderLoginItem();

$("login-item").addEventListener("change", async () => {
  try {
    loginItem = await window.talktomeDesktop.setLoginItem($("login-item").checked);
  } catch (error) {
    notice(error.message);
  }
  renderLoginItem();
});
$("open-login-items").addEventListener("click", () =>
  window.talktomeDesktop?.openSystemSettings?.("login-items")?.catch?.((error) => notice(error.message)),
);
$("open-microphone-settings").addEventListener("click", () =>
  window.talktomeDesktop?.openSystemSettings?.("microphone")?.catch?.((error) => notice(error.message)),
);

function notice(message) {
  $("notice-text").textContent = message;
  $("notice").classList.remove("hidden");
}

// action: "retry-mic", "mic-settings", or "settings". The call surface shows
// the matching button.
function callProblem(message, action = null) {
  notice(message);
  if (!state.room.call_id) return;
  callAlert = { text: message, action };
  render();
}

function clearCallProblem(action) {
  if (!callAlert || (action !== undefined && callAlert.action !== action)) return;
  callAlert = null;
  render();
}

async function api(path, options = {}) {
  const response = await fetch(`/v1${path}`, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof Blob)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `The request failed (${response.status}).`,
    );
  }
  return response.headers.get("content-type")?.includes("application/json")
    ? response.json()
    : response.blob();
}

const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body) });

function navigate(next) {
  page = next;
  for (const section of document.querySelectorAll(".page"))
    section.classList.add("hidden");
  $(paired ? `page-${next}` : "signin-failed").classList.remove("hidden");
}

const GLOW_KEY = "talktome-notch-glow";
const GLOW_COLORS = new Set(["amber", "blue", "violet", "green", "pink", "cyan"]);
// The glow color belongs to the native notch surface. Without it the call uses
// the normal pill, so Settings shows the pill position instead.
let nativeNotch = false;
window.talktomeDesktop?.info?.()?.then((info) => {
  nativeNotch = Boolean(info.nativeNotch);
  $("pill-placement-setting").hidden = nativeNotch;
  $("glow-setting").hidden = !nativeNotch;
  syncGlow();
})?.catch(() => {});

function syncGlow(color = localStorage.getItem(GLOW_KEY) || "amber") {
  const selected = GLOW_COLORS.has(color) ? color : "amber";
  document.documentElement.dataset.color = selected;
  if (nativeNotch) window.talktomeDesktop?.setGlowColor?.(selected)?.catch(() => {});
  for (const button of $("settings-glow-list").querySelectorAll("[data-color]")) {
    button.setAttribute("aria-checked", String(button.dataset.color === selected));
  }
}

$("settings-glow-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-color]");
  if (!button) return;
  localStorage.setItem(GLOW_KEY, button.dataset.color);
  syncGlow(button.dataset.color);
});
window.addEventListener("storage", (event) => {
  if (event.key === GLOW_KEY) syncGlow(event.newValue || "amber");
});
syncGlow();

function render() {
  const active = Boolean(state.room.call_id);
  const agent = state.room.agent;
  $("connection-name").textContent = agent
    ? `${agent.name} is connected`
    : "No agent connected";
  $("disconnect-agent").classList.toggle("hidden", !agent);
  reportDesktopCallState(active);
  $("mic-select").disabled = active;
  renderModelProgress();
  renderProviders();
  renderTurnDetection();
  renderMicrophonePermission();
}

function renderTurnDetection() {
  const detector = state.speech.smart_turn || {};
  const busy = turnSettingsBusy || Boolean(state.room.call_id || state.managed?.ring);
  $("turn-detection").value = detector.enabled === false ? "pause" : "smart";
  $("turn-detection").disabled = busy;
  $("retry-turn-detection").disabled = busy;
  $("retry-turn-detection").classList.toggle("hidden", !detector.enabled || detector.status !== "error");
  $("turn-detection-status").textContent = detector.enabled === false
    ? "Send after the selected pause."
    : detector.status === "ready"
      ? "Ready. Smart Turn checks whether you finished speaking."
      : detector.status === "error"
        ? detector.error
        : "Preparing Smart Turn · 8.7 MB. The pause setting works until it is ready.";
  const smart = detector.enabled && detector.status === "ready";
  $("turn-pause-description").textContent = smart
    ? "Checks after 0.3, 0.45, or 0.7 seconds. Waits up to 3 seconds for unfinished speech."
    : "Sends after 0.7, 0.9, or 1.8 seconds of silence.";
}

let skillReport = null;
let agentBusy = false;

async function loadAgents() {
  try {
    skillReport = await api("/skill");
  } catch {
    skillReport = null;
  }
  renderAgents();
}

function renderAgents() {
  const rows = [];
  if (skillReport) {
    const row = document.createElement("div");
    row.className = "agent-row";
    const text = document.createElement("div");
    text.className = "agent-row-text";
    const name = document.createElement("p");
    name.className = "agent-row-name";
    name.textContent = skillReport.name;
    const state_ = document.createElement("p");
    state_.className = `agent-row-state${skillReport.installed ? " installed" : ""}`;
    state_.textContent = skillState(skillReport);
    text.append(name, state_);
    row.append(text);
    const button = document.createElement("button");
    button.className = skillReport.installed ? "secondary-button" : "primary-button small";
    button.textContent = skillReport.installed ? "Reinstall" : "Install";
    button.disabled = agentBusy;
    button.addEventListener("click", () => installSkill());
    row.append(button);
    rows.push(row);
  }
  $("agent-list").replaceChildren(...rows);
  $("admin-install").classList.toggle(
    "hidden",
    !skillReport?.admin_install || !window.talktomeDesktop?.installCommandForAllUsers,
  );
  $("install-all-users").disabled = agentBusy;
}

// Two halves, one step: instructions and the command they tell an agent to run.
// Installed means an agent can actually do it, so a missing half is worth naming
// rather than leaving as "not installed" with no clue which part is missing.
function skillState(report) {
  const missing = (report.hosts || []).filter((host) => !host.skill);
  if (missing.length)
    return `Install or update the skill for ${agentNames(missing).join(", ")}`;
  if (report.installed) return "Your agent can ring you";
  if (report.skill && !report.command) return "Installed, but the talktome command is not on PATH";
  if (report.command && !report.skill) return "The command is ready, but the skill is missing";
  return "Adds the skill and the talktome command";
}

// The server tries a normal install first. The main process then writes its own
// copy of the script into /usr/local/bin after the macOS administrator prompt.
async function installForAllUsers() {
  agentBusy = true;
  renderAgents();
  try {
    let installed = false;
    try {
      installed = Boolean((await post("/skill/install", {})).installed);
    } catch (error) {
      // Only this refusal stages the script. Any other one is the real answer.
      if (!error.message.includes("Install for all users")) throw error;
    }
    if (!installed) await window.talktomeDesktop.installCommandForAllUsers();
    skillReport = await api("/skill");
    notice("The talktome command is installed for all users.");
  } catch (error) {
    notice(error.message);
  } finally {
    agentBusy = false;
    renderAgents();
  }
}
$("install-all-users").addEventListener("click", () => installForAllUsers());

async function installSkill() {
  agentBusy = true;
  renderAgents();
  try {
    skillReport = await post("/skill/install", {});
    notice("Your agent can ring you now. Ask it to call you.");
  } catch (error) {
    notice(error.message);
  } finally {
    agentBusy = false;
    renderAgents();
  }
}

function renderModelProgress() {
  const speech = state.speech.local_stt || state.speech;
  const busy = ["downloading", "loading"].includes(speech.status);
  $("download-state").classList.toggle(
    "hidden",
    !busy && speech.status !== "error",
  );
  $("download-label").textContent =
    speech.status === "loading"
      ? "Load the speech model"
      : speech.status === "error"
        ? "Download failed"
        : "Download in progress";
  $("download-percent").textContent = busy ? `${speech.progress || 0}%` : "";
  $("download-progress").value = speech.progress || 0;
  $("download-detail").textContent =
    speech.error ||
    (speech.status === "loading"
      ? "Please wait."
      : `${Math.round((speech.downloaded_bytes || 0) / 1e6)} MB of ${Math.round((speech.total_bytes || 0) / 1e6)} MB`);
  document.querySelectorAll("[data-model]").forEach((button) => {
    const selected =
      speech.model_id === button.dataset.model && speech.status === "ready";
    button.disabled = busy || selected || Boolean(state.room.call_id);
    button.textContent = selected ? "Active" : "Download & use";
  });
}

function renderProviders() {
  const speech = state.speech;
  const active = Boolean(state.room.call_id);
  const kokoro = speech.kokoro || {};
  const eleven = speech.elevenlabs || {};
  const busy = ["downloading", "loading"].includes(kokoro.status);
  if (!providerBusy) {
    $("tts-provider").value = speech.tts_provider || "system";
    $("stt-provider").value = speech.stt_provider || "whisper";
  }
  $("whisper-settings").classList.toggle(
    "hidden",
    $("stt-provider").value !== "whisper",
  );
  $("kokoro-settings").classList.toggle(
    "hidden",
    $("tts-provider").value !== "kokoro",
  );
  $("elevenlabs-settings").classList.toggle(
    "hidden",
    !eleven.configured &&
      ![$("tts-provider").value, $("stt-provider").value].includes(
        "elevenlabs",
      ),
  );
  for (const id of [
    "tts-provider",
    "stt-provider",
    "voice-select",
    "save-elevenlabs",
    "forget-elevenlabs",
    "elevenlabs-key",
    "remember-elevenlabs",
  ])
    $(id).disabled = active || providerBusy;
  $("settings-call-note").classList.toggle("hidden", !active);
  $("download-kokoro").disabled = busy || active || kokoro.status === "ready";
  $("download-kokoro").textContent =
    kokoro.status === "ready"
      ? "Downloaded"
      : busy
        ? "Please wait…"
        : "Download Kokoro";
  $("kokoro-progress").classList.toggle(
    "hidden",
    !busy && kokoro.status !== "error",
  );
  $("kokoro-download-progress").value = kokoro.progress || 0;
  $("kokoro-download-detail").textContent =
    kokoro.error ||
    (kokoro.status === "loading"
      ? "Load the voice model…"
      : `${kokoro.progress || 0}% · ${Math.round((kokoro.downloaded_bytes || 0) / 1e6)} MB of ${Math.round((kokoro.total_bytes || 0) / 1e6)} MB`);
  $("elevenlabs-key-status").textContent = eleven.configured
    ? eleven.remembered
      ? "Key connected. The system keychain stores the key."
      : "Key connected for this app session."
    : "No key connected.";
  $("forget-elevenlabs").classList.toggle("hidden", !eleven.configured);
  $("preview-voice").disabled =
    active ||
    providerBusy ||
    previewBusy ||
    !speech.tts_available ||
    !$("voice-select").options.length;
  const signature = `${speech.tts_provider}:${kokoro.status}:${eleven.configured}`;
  if (paired && voiceSignature !== signature && !providerBusy) {
    voiceSignature = signature;
    void loadVoices().catch((error) => notice(error.message));
  }
}

async function loadVoices() {
  const provider = state.speech.tts_provider;
  const voices = await api("/tts/voices");
  if (provider !== state.speech.tts_provider) return;
  const options = voices.voices.map(
    (voice) =>
      new Option(
        `${voice.name}${voice.language ? ` · ${voice.language}` : ""}`,
        voice.id,
      ),
  );
  if (options.length && !options.some((option) => option.value === "default"))
    options.unshift(new Option("Provider default", "default"));
  // A voice the provider lists but will not speak with — a library voice on a free
  // plan — is not in the list, and a bare blank select would read as a bug rather
  // than a refusal. It stays visible, labelled, until the user picks another.
  if (
    voices.selected &&
    !options.some((option) => option.value === voices.selected)
  )
    options.unshift(
      new Option("Unavailable — choose another voice", voices.selected),
    );
  $("voice-select").replaceChildren(...options);
  $("voice-select").value = voices.selected;
  const withheld = voices.withheld || {};
  $("voice-withheld").textContent = withheld.count ? withheld.reason : "";
  render();
}

async function loadSettings() {
  const catalog = await api("/models");
  if (modelSignature !== JSON.stringify(catalog.models)) {
    modelSignature = JSON.stringify(catalog.models);
    $("model-list").replaceChildren();
    for (const model of catalog.models) {
      const card = document.createElement("div");
      card.className = "model-card";
      const title = document.createElement("div");
      title.className = "model-title";
      const name = document.createElement("span");
      name.textContent = model.name;
      title.append(name);
      const bottom = document.createElement("div");
      bottom.className = "model-bottom";
      const size = document.createElement("span");
      size.textContent = `${model.size_mb} MB · ${model.languages}`;
      const button = document.createElement("button");
      button.className = "secondary-button";
      button.dataset.model = model.id;
      button.textContent = "Download & use";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await post(`/models/${model.id}/download`, {});
          await refresh();
        } catch (error) {
          notice(error.message);
          button.disabled = false;
        }
      });
      bottom.append(size, button);
      card.append(title, bottom);
      $("model-list").append(card);
    }
  }
  await loadVoices().catch((error) => notice(error.message));
  await listMicrophones();
  await loadAgents();
  render();
}

async function listMicrophones() {
  const selected = localStorage.getItem("talktome-microphone") || "default";
  const devices = await navigator.mediaDevices.enumerateDevices();
  const options = [new Option("System default", "default")];
  devices
    .filter(
      (device) => device.kind === "audioinput" && device.deviceId !== "default",
    )
    .forEach((device, i) => {
      options.push(
        new Option(device.label || `Microphone ${i + 1}`, device.deviceId),
      );
    });
  $("mic-select").replaceChildren(...options);
  $("mic-select").value = options.some((option) => option.value === selected)
    ? selected
    : "default";
}

function showPartial(text) {
  if (partialTranscript === text) return;
  partialTranscript = text;
  reportDesktopCallState(Boolean(state.room.call_id));
}

function stopRealtimeInput() {
  const current = realtimeInput;
  realtimeInput = null;
  current?.close();
  showPartial("");
}

function startRealtimeInput(mic) {
  if (
    state.speech.stt_provider !== "elevenlabs" ||
    !state.room.call_id ||
    !supportsRealtimeRate(mic.context?.sampleRate)
  ) return;
  if (realtimeInput && !realtimeInput.failed && !realtimeInput.closed) return;
  stopRealtimeInput();
  const callId = state.room.call_id;
  const stream = new RealtimeInput({
    callId,
    sampleRate: mic.context.sampleRate,
    onPartial: (text) => {
      if (realtimeInput === stream && state.room.call_id === callId) showPartial(text);
    },
  });
  realtimeInput = stream;
  void stream.start().catch(() => {});
}

async function startMicrophone() {
  const mic = new Microphone({
    pauseMode: $("turn-pause").value,
    onAudio: sendAudio,
    onChunk: (chunk) => realtimeInput?.feed(chunk),
    onTurnCheck: () => {
      const detector = state.speech.smart_turn;
      if (!detector?.enabled || detector.status !== "ready") return;
      const callId = state.room.call_id;
      const stream = realtimeInput;
      if (!callId || stream?.callId !== callId || stream.failed || stream.closed) return;
      void stream.commitEarly().catch(() => {
        if (realtimeInput === stream && state.room.call_id === callId)
          stopRealtimeInput();
      });
    },
    onSpeechResume: () => {
      if (realtimeInput?.callId === state.room.call_id) realtimeInput.resumeSpeech();
    },
    checkTurn: checkSpeechTurn,
    onDiscard: () => {
      stopRealtimeInput();
      resumeFalseInterruption();
    },
    onRecording: (value) => {
      recording = value;
      if (value) {
        pauseForSpeech();
        startRealtimeInput(mic);
        realtimeInput?.startUtterance();
      }
      render();
    },
    onError: (message) => {
      stopRealtimeInput();
      resumeFalseInterruption();
      if (microphone === mic) microphone = null;
      callProblem(message, "retry-mic");
      render();
    },
  });
  try {
    await mic.start($("mic-select").value);
    microphone = mic;
    microphonePermission = "granted";
    mic.setAssistantSpeaking(speaking);
    pauseCapture();
    startRealtimeInput(mic);
    clearCallProblem("retry-mic");
    clearCallProblem("mic-settings");
    await listMicrophones();
  } catch (error) {
    if (error.name === "NotAllowedError") {
      microphonePermission = "denied";
      callProblem("Microphone access is off. Allow it in System Settings.", "mic-settings");
    } else {
      callProblem(`The microphone did not start. ${error.message}`, "retry-mic");
    }
  }
  render();
}

// Realtime input keeps one open utterance, so capture pauses while it commits.
// The file path can hold the next utterance and send it after this one.
function pauseCapture() {
  microphone?.setPaused(transcribing && Boolean(realtimeInput));
}

async function checkSpeechTurn(audio, signal) {
  const detector = state.speech.smart_turn;
  if (!detector?.enabled || detector.status !== "ready" || !state.room.call_id) return null;
  const callId = state.room.call_id;
  const epoch = state.room.playback_epoch;
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal.aborted) return null;
  signal.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 650);
  try {
    const query = new URLSearchParams({ call_id: callId, playback_epoch: String(epoch) });
    const result = await api(`/call/turn-check?${query}`, {
      method: "POST", body: audio, signal: controller.signal,
    });
    if (state.room.call_id !== callId || state.room.playback_epoch !== epoch) return null;
    return result;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}

async function sendAudio(blob, timing = {}) {
  if (!state.room.call_id) return;
  if (transcribing) {
    if (heldAudio.length < 3) heldAudio.push([blob, timing]);
    return;
  }
  const callId = state.room.call_id;
  const interruption = interruptionCandidate;
  transcribing = true;
  pauseCapture();
  render();
  try {
    let text = "";
    let committed = false;
    let commitTiming = null;
    const stream = realtimeInput;
    if (stream && !stream.failed) {
      try {
        const result = await stream.commitFinal();
        text = result.text;
        commitTiming = result;
        committed = Boolean(text) && realtimeInput === stream && stream.callId === callId;
      } catch {
        stream.close();
        if (realtimeInput === stream) realtimeInput = null;
      }
    }
    if (!committed && interruption && state.room.call_id === callId) {
      const result = await api("/stt/transcribe", { method: "POST", body: blob });
      text = (result.text || "").trim();
      committed = Boolean(text);
    }
    if (committed && state.room.call_id === callId) {
      if (interruption) stopPlayback();
      await post("/call/text", {
        call_id: callId,
        text,
        speech_end_ms: timing.speechEndMs,
        capture_end_ms: timing.captureEndMs,
        commit_sent_ms: commitTiming?.commitSentMs,
        committed_ms: commitTiming?.committedMs,
        transcribed_ms: performance.timeOrigin + performance.now(),
        turn_reason: timing.turnReason,
        turn_probability: timing.turnProbability,
        turn_check_ms: timing.turnCheckMs,
        ...(interruption || {}),
      });
    } else if (!interruption && state.room.call_id === callId) {
      const result = await api(
        `/call/audio?call_id=${encodeURIComponent(callId)}`,
        {
          method: "POST",
          body: blob,
          headers: {
            ...(timing.turnReason ? { "X-TalkToMe-Turn-Reason": timing.turnReason } : {}),
            ...(Number.isFinite(timing.turnProbability)
              ? { "X-TalkToMe-Turn-Probability": String(timing.turnProbability) } : {}),
            ...(Number.isFinite(timing.turnCheckMs)
              ? { "X-TalkToMe-Turn-Check-Ms": String(timing.turnCheckMs) } : {}),
            ...(timing.speechEndMs
              ? { "X-TalkToMe-Speech-End-Ms": String(timing.speechEndMs) }
              : {}),
            ...(timing.captureEndMs
              ? { "X-TalkToMe-Capture-End-Ms": String(timing.captureEndMs) }
              : {}),
          },
        },
      );
      if (!result.text)
        notice("No speech was detected. Speak closer to the microphone.");
    }
    if (interruption && !committed) resumeFalseInterruption();
    clearCallProblem("settings");
    clearCallProblem(null);
  } catch (error) {
    resumeFalseInterruption();
    callProblem(error.message, /speech model|Settings/.test(error.message) ? "settings" : null);
  } finally {
    showPartial("");
    transcribing = false;
    pauseCapture();
    render();
  }
  const next = heldAudio.shift();
  if (next && state.room.call_id === callId) void sendAudio(...next);
  else heldAudio.length = 0;
}

function stopPlayback() {
  audioQueue.clear();
}

function stopCurrentPlayback() {
  interruptionCandidate = null;
  playbackEpoch++;
  playbackRequests = 0;
  player.cancel();
  syncPlayback();
}

function syncPlayback() {
  speaking = playbackRequests > 0 || player.playing;
  microphone?.setAssistantSpeaking(speaking);
  pauseCapture();
  render();
}

async function playAudio(source, event = null) {
  const epoch = playbackEpoch;
  if (event && !currentAudioEvent(event, state.room)) return;
  playbackRequests++;
  syncPlayback();
  try {
    if (source instanceof Blob) {
      // Audio the caller already holds — the voice preview. It is decoded
      // directly rather than through an object URL, which the content security
      // policy blocks for fetch.
      await player.playData(source);
    } else {
      // Callers name a route the way the rest of this file does, relative to
      // /v1. The player fetches it directly, so the prefix is added here.
      await player.play(`/v1${source}`, {
        event,
        onScheduled: event && event.kind !== "greeting"
          ? (atMs) => {
              if (firstScheduledTurn === event.turn_id) return;
              firstScheduledTurn = event.turn_id;
              void post("/call/timing", {
                call_id: event.call_id,
                turn_id: event.turn_id,
                first_audio_scheduled_ms: atMs,
              }).catch(() => {});
            }
          : undefined,
        onAudible: event && event.kind !== "greeting"
          ? (atMs) => {
              if (firstAudioTurn === event.turn_id) return;
              firstAudioTurn = event.turn_id;
              void post("/call/timing", {
                call_id: event.call_id,
                turn_id: event.turn_id,
                first_audio_ms: atMs,
              }).catch(() => {});
            }
          : undefined,
      });
    }
  } catch (error) {
    if (epoch === playbackEpoch) {
      callProblem(`The reply audio did not play. ${error.message}`);
    }
  } finally {
    if (epoch === playbackEpoch) {
      playbackRequests--;
      syncPlayback();
    }
  }
}

function callChanged(previousCall) {
  if (!previousCall || previousCall === state.room.call_id) return;
  microphone?.stop();
  microphone = null;
  stopRealtimeInput();
  stopPlayback();
  callAlert = null;
  heldAudio.length = 0;
}

async function refresh() {
  const next = await api("/state");
  const previousCall = state.room.call_id;
  state = next;
  callChanged(previousCall);
  if (state.speech.stt_provider !== "elevenlabs" && realtimeInput) stopRealtimeInput();
  render();
}

// The one live view of the server. Reply deltas change only the transcript,
// which this window does not draw, so they skip the render.
function startStream() {
  followStream({
    onSnapshot: (next) => {
      const previousCall = state.room.call_id;
      state = { ...state, ...next };
      callChanged(previousCall);
      if (state.speech.stt_provider !== "elevenlabs" && realtimeInput) stopRealtimeInput();
      render();
    },
    onEvent: ({ event, room, managed }) => {
      const previousCall = state.room.call_id;
      applyEvent(state.room, event);
      if (room) Object.assign(state.room, room);
      if (managed) state.managed = managed;
      callChanged(previousCall);
      if (["user.utterance", "agent.interrupted", "call.ended"].includes(event.type))
        stopPlayback();
      if (["agent.reply", "agent.audio"].includes(event.type) && currentAudioEvent(event, state.room))
        audioQueue.enqueue(event);
      if (event.type !== "message.delta") render();
    },
    onSpeech: (speech) => {
      state.speech = speech;
      if (state.speech.stt_provider !== "elevenlabs" && realtimeInput) stopRealtimeInput();
      render();
    },
    onLost: () => callProblem("The local connection stopped. TalkToMe tries to connect again."),
    onOpen: () => clearCallProblem(null),
  });
}

async function initialize(token) {
  if (token) await post("/auth", { token });
  await refresh();
  await readMicrophonePermission().catch(() => {});
  paired = true;
  const savedStage = localStorage.getItem("talktome-onboarding");
  onboarding =
    savedStage === "complete" || state.room.call_id
      ? null
      : savedStage === "connect"
        ? "connect"
        : "setup";
  // The main process shows the setup window only while setup is incomplete. After
  // setup the window hides and the app waits in the menu bar.
  window.talktomeDesktop?.setOnboarding?.(Boolean(onboarding));
  navigate("setup");
  await loadSettings();
  startStream();
}

$("theme-select").value =
  document.documentElement.dataset.themePreference || "dark";
$("theme-select").addEventListener("change", () =>
  window.setTalktomeTheme($("theme-select").value),
);
$("allow-microphone").addEventListener("click", async () => {
  permissionBusy = true;
  render();
  try {
    microphonePermission =
      (await window.talktomeDesktop?.requestMicrophone?.()) || "unknown";
    if (microphonePermission === "unknown") {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: false,
      });
      stream.getTracks().forEach((track) => track.stop());
      microphonePermission = "granted";
    }
    if (microphonePermission !== "granted")
      notice("Allow microphone access in system settings, then try again.");
    await listMicrophones();
  } catch (error) {
    microphonePermission =
      error.name === "NotAllowedError" ? "denied" : "unknown";
    notice(
      "The microphone is unavailable. Examine its connection and system permissions.",
    );
  } finally {
    permissionBusy = false;
    render();
  }
});
window.addEventListener("focus", () => {
  if (paired)
    void readMicrophonePermission()
      .then(render)
      .catch(() => {});
});

async function toggleMute() {
  if (!microphone) await startMicrophone();
  else {
    microphone.setMuted(!microphone.muted);
    if (microphone.muted) stopRealtimeInput();
    else startRealtimeInput(microphone);
  }
  render();
}

async function endCall() {
  if (!state.room.call_id) return;
  const callId = state.room.call_id;
  microphone?.stop();
  microphone = null;
  stopRealtimeInput();
  stopPlayback();
  callAlert = null;
  heldAudio.length = 0;
  await post("/call/end", { call_id: callId });
}

async function retryMicrophone() {
  if (!state.room.call_id) return;
  const muted = Boolean(microphone?.muted);
  microphone?.stop();
  microphone = null;
  stopRealtimeInput();
  await startMicrophone();
  if (muted && microphone) {
    microphone.setMuted(true);
    stopRealtimeInput();
    render();
  }
}

// The Mac woke up. The microphone and both ElevenLabs sockets can be dead with
// no error, so each one starts again. A microphone that does not come back
// shows on the pill with Retry mic.
async function resumeAfterSleep() {
  await refresh().catch(() => {});
  if (!state.room.call_id) return;
  await post("/call/resume", { call_id: state.room.call_id }).catch(() => {});
  await retryMicrophone();
}
window.talktomeDesktop?.onResume?.(() => void resumeAfterSleep());

// The floating call surface lives in its own window and cannot touch the
// microphone, the audio queue, or the agent session. This window owns all three,
// so it reports whether a call is live and carries out the surface's controls.
let reportedCallState = "";
function reportDesktopCallState(active) {
  const bridge = window.talktomeDesktop;
  if (!bridge?.setCallState) return;
  // A ringing call has no call id yet, but the surface has to be on screen: it is
  // where the question is asked.
  const ring = state.managed?.status === "ringing" ? state.managed.ring : null;
  const managed = active ? state.managed || {} : {};
  // A turn that failed, or a voice that stopped, is reported by the server.
  const serverAlert = managed.error && managed.error !== dismissedError
    ? { text: managed.error, action: null }
    : null;
  const next = {
    live: Boolean(active || ring),
    callId: state.room.call_id || null,
    startedAt: state.room.started_at || null,
    muted: !microphone || microphone.muted,
    state: ring ? "ringing" : active ? "active" : "idle",
    ring: ring ? { id: ring.id || "", name: ring.name || "" } : null,
    name: state.managed?.thread_name || state.room.agent?.name || "TalkToMe",
    // The call surface draws one thread per side from these two flags. They are
    // the signals this window already tracks — the microphone's own speech
    // detection and whether a reply is sounding — rather than a measurement, so
    // nothing has to be sampled or pushed on a timer.
    userActive: Boolean(active && recording && !microphone?.muted),
    agentActive: Boolean(active && speaking),
    thinking: Boolean(active && (transcribing || (state.room.turn_id && !state.room.answered)) && !recording && !speaking),
    partial: active ? partialTranscript : "",
    transcribing: Boolean(active && transcribing),
    working: ["working", "approval"].includes(managed.status),
    tool: managed.tool || "",
    approval: Boolean(managed.approvals?.length),
    alert: active ? callAlert || serverAlert : null,
  };
  // render() runs on every refresh, and this crosses a process boundary, so stop
  // when nothing changed.
  const key = JSON.stringify(next);
  if (key === reportedCallState) return;
  reportedCallState = key;
  bridge.setCallState(next).catch(() => {
    // Losing the desktop bridge is not a call failure; the window keeps working.
    reportedCallState = "";
  });
}

window.talktomeDesktop?.onCallCommand?.((type) => {
  if (type === "mute") void toggleMute();
  else if (type === "interrupt") void interruptReply();
  else if (type === "end") void endCall();
  else if (type === "accept") void answerRing();
  else if (type === "decline") void declineRing();
  else if (type === "retry-mic") void retryMicrophone();
  else if (type === "dismiss") {
    dismissedError = state.managed?.error || null;
    callAlert = null;
    render();
  }
  else if (type === "callback") void joinCallBack();
});

// A call back starts live with no ring to answer, so start the microphone here.
async function joinCallBack() {
  await refresh();
  if (state.room.call_id && !microphone) await startMicrophone();
}

async function declineRing() {
  try {
    await post("/attach/decline", { ring_id: state.managed?.ring?.id ?? null });
  } catch (error) {
    notice(error.message);
  }
  await refresh();
}

// Answering happens on the surface, which cannot reach the server's ring state
// itself. The id is sent back so a stale answer cannot take a later call.
async function answerRing() {
  try {
    await post("/attach/accept", { ring_id: state.managed?.ring?.id ?? null });
    await refresh();
    if (state.room.call_id) await startMicrophone();
  } catch (error) {
    callProblem(error.message);
  }
  await refresh();
}

$("refresh-agents").addEventListener("click", () => void loadAgents());
async function interruptReply() {
  if (!state.room.call_id) return;
  const interruption = interruptionCandidate || capturePlayback();
  stopPlayback();
  try {
    await post("/call/interrupt", interruption);
    await refresh();
  } catch (error) {
    notice(error.message);
  }
}

$("voice-select").addEventListener("change", async () => {
  try {
    await post("/tts/voice", { voice: $("voice-select").value });
  } catch (error) {
    notice(error.message);
  }
});
$("mic-select").addEventListener("change", () =>
  localStorage.setItem("talktome-microphone", $("mic-select").value),
);
$("turn-pause").value = localStorage.getItem("talktome-turn-pause") || "balanced";
$("turn-pause").addEventListener("change", () => {
  localStorage.setItem("talktome-turn-pause", $("turn-pause").value);
  if (microphone) microphone.pauseMode = $("turn-pause").value;
});
async function saveTurnDetection(enabled) {
  turnSettingsBusy = true;
  render();
  try {
    await post("/speech/turn-detection", { enabled });
    await refresh();
  } catch (error) {
    notice(error.message);
  } finally {
    turnSettingsBusy = false;
    render();
  }
}
$("turn-detection").addEventListener("change", () => {
  void saveTurnDetection($("turn-detection").value === "smart");
});
$("retry-turn-detection").addEventListener("click", () => void saveTurnDetection(true));
// The call surface placement. The main process owns the call window, so this
// window saves the setting and reports it across the bridge. The setting stays
// available during a call, because a change moves the live surface.
const PLACEMENT_KEY = "talktome-pill-placement";
function savedPlacement() {
  return localStorage.getItem(PLACEMENT_KEY) === "top-center"
    ? "top-center"
    : "bottom";
}
$("pill-placement").value = savedPlacement();
window.talktomeDesktop?.setPillPlacement?.(savedPlacement());
$("pill-placement").addEventListener("change", () => {
  const placement =
    $("pill-placement").value === "top-center" ? "top-center" : "bottom";
  localStorage.setItem(PLACEMENT_KEY, placement);
  window.talktomeDesktop?.setPillPlacement?.(placement);
});
$("preview-voice").addEventListener("click", async () => {
  stopPlayback();
  previewBusy = true;
  render();
  try {
    await playAudio(
      await post("/tts/speak", {
        text: "This is the selected voice.",
        voice: $("voice-select").value,
      }),
    );
  } catch (error) {
    notice(error.message);
  } finally {
    previewBusy = false;
    render();
  }
});

for (const id of ["tts-provider", "stt-provider"])
  $(id).addEventListener("change", async () => {
    providerBusy = true;
    stopPlayback();
    render();
    try {
      await post("/speech/providers", {
        tts_provider: $("tts-provider").value,
        stt_provider: $("stt-provider").value,
      });
      await refresh();
      await loadVoices();
    } catch (error) {
      notice(error.message);
    } finally {
      providerBusy = false;
      render();
    }
  });
$("download-kokoro").addEventListener("click", async () => {
  $("download-kokoro").disabled = true;
  try {
    await post("/tts/kokoro/download", {});
    await refresh();
  } catch (error) {
    notice(error.message);
    render();
  }
});
$("elevenlabs-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const apiKey = $("elevenlabs-key").value.trim();
  if (!apiKey) return;
  providerBusy = true;
  render();
  try {
    const wantsRemember = $("remember-elevenlabs").checked;
    const saved = await post("/speech/elevenlabs", {
      api_key: apiKey,
      remember: wantsRemember,
    });
    $("elevenlabs-key").value = "";
    await refresh();
    await loadVoices();
    // The key works either way; say so when only the remembering part failed, rather
    // than leaving the box ticked over a keychain that refused it.
    if (wantsRemember && !saved.remembered) {
      notice(
        `The key is connected for this session, but the system keychain would not store it.${saved.reason ? ` ${saved.reason}` : ""}`,
      );
    }
  } catch (error) {
    notice(error.message);
  } finally {
    providerBusy = false;
    render();
  }
});
$("forget-elevenlabs").addEventListener("click", async () => {
  providerBusy = true;
  stopPlayback();
  render();
  try {
    await api("/speech/elevenlabs", { method: "DELETE" });
    await refresh();
    await loadVoices();
  } catch (error) {
    notice(error.message);
  } finally {
    providerBusy = false;
    render();
  }
});
$("disconnect-agent").addEventListener("click", async () => {
  try {
    stopPlayback();
    await post("/agent/disconnect", {});
    await refresh();
  } catch (error) {
    notice(error.message);
  }
});
$("dismiss-notice").addEventListener("click", () =>
  $("notice").classList.add("hidden"),
);
document
  .querySelectorAll("[data-page]")
  .forEach((button) =>
    button.addEventListener("click", () => navigate(button.dataset.page)),
  );
// Closing settings hides the window. The renderer stays alive, so the
// microphone, the audio, and the event polling keep working.
for (const id of ["close-settings", "close-connection"])
  $(id).addEventListener("click", () =>
    window.talktomeDesktop?.hideWindow?.(),
  );
window.talktomeDesktop?.onOpenSettings?.(() => {
  if (!paired) return;
  navigate("setup");
  render();
});
window.talktomeDesktop?.onOnboardingComplete?.(() => {
  if (onboarding) onboardingStage("complete");
});

window.addEventListener("beforeunload", () => {
  microphone?.stop();
  stopRealtimeInput();
});

const token = new URLSearchParams(location.hash.slice(1)).get("token");
history.replaceState(null, "", location.pathname);
initialize(token).catch(() => {
  paired = false;
  navigate(page);
});
