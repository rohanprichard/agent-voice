import { resumeStep, setupSteps } from "./onboarding-steps.js";

const $ = (id) => document.getElementById(id);
const colors = ["amber", "blue", "violet", "green", "pink", "cyan"];
// False until the main process says the native notch surface is running.
let nativeNotch = false;
let steps = setupSteps(nativeNotch);
let step = resumeStep(localStorage.getItem("talktome-setup-step") || "welcome", steps);
let microphone = "unknown";
let voiceReady = false;
let speechReady = false;
let speechName = "Speech";
let agentReady = false;
let busy = false;
let color = localStorage.getItem("talktome-notch-glow") || "amber";
if (!colors.includes(color)) color = "amber";

function setStatus(id, message, error = false) {
  const item = $(id);
  item.textContent = message;
  item.classList.toggle("error", error);
}

function setColor(next) {
  color = next;
  localStorage.setItem("talktome-notch-glow", next);
  if (nativeNotch) window.talktomeSetup?.setGlowColor?.(next)?.catch(() => {});
  document.documentElement.dataset.color = next;
  $("color-name").textContent = next[0].toUpperCase() + next.slice(1);
  for (const item of $("color-list").querySelectorAll("button"))
    item.setAttribute("aria-checked", String(item.dataset.color === next));
}

function renderReady() {
  const allReady = microphone === "granted" && speechReady && agentReady;
  $("ready-eyebrow").textContent = allReady ? "All set" : "Setup saved";
  $("ready-title").textContent = allReady ? "Ask your agent to call." : "Ready when you are.";
  $("ready-copy").textContent = allReady
    ? "Say “Call me with TalkToMe.”"
    : "Add the missing items in Settings before a call.";
  const rows = [
    [microphone === "granted", microphone === "granted" ? "Microphone ready" : "Allow microphone access"],
    [speechReady, speechReady ? `${speechName} ready` : "Add speech in Settings"],
    [agentReady, agentReady ? "Agent ready" : "Install the agent skill"],
  ];
  $("ready-checks").replaceChildren(...rows.map(([done, label]) => {
    const row = document.createElement("p");
    row.className = done ? "done" : "pending";
    row.textContent = label;
    return row;
  }));
}

function render() {
  const index = steps.indexOf(step);
  for (const section of document.querySelectorAll(".step"))
    section.hidden = section.dataset.step !== step;
  $("step-count").textContent = `${index + 1} / ${steps.length}`;
  $("back-button").hidden = index === 0;
  $("progress").replaceChildren(...steps.map((_, position) => {
    const dot = document.createElement("span");
    if (position === index) dot.className = "current";
    return dot;
  }));
  $("microphone-next").textContent = microphone === "granted" ? "Continue" : "Allow microphone";
  $("microphone-skip").hidden = microphone === "granted";
  $("voice-save").textContent = voiceReady ? "Continue" : busy ? "Connecting…" : "Connect";
  $("agent-install").textContent = agentReady ? "Continue" : busy ? "Installing…" : "Install";
  $("voice-save").disabled = busy;
  $("agent-install").disabled = busy;
  renderReady();
}

function go(next) {
  step = next;
  localStorage.setItem("talktome-setup-step", next);
  render();
}

function next() {
  const index = steps.indexOf(step);
  if (index < steps.length - 1) go(steps[index + 1]);
}

async function api(path, options = {}) {
  const response = await fetch(`/v1${path}`, {
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `The request failed (${response.status}).`);
  }
  return response.json();
}

async function post(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

async function readStatus() {
  try {
    microphone = await window.talktomeSetup?.microphoneStatus?.() || "unknown";
    setStatus("microphone-status", microphone === "granted" ? "Access on" : microphone === "denied" ? "Access off in macOS Settings" : "Access off");
  } catch {
    setStatus("microphone-status", "Access off");
  }
  try {
    const [models, skill] = await Promise.all([api("/models"), api("/skill")]);
    voiceReady = Boolean(models.speech?.elevenlabs?.configured);
    speechReady = models.speech?.status === "ready" && Boolean(models.speech?.tts_available);
    speechName = models.speech?.stt_provider === "elevenlabs" ? "ElevenLabs" : "Local speech";
    agentReady = Boolean(skill.installed);
    if (voiceReady) setStatus("voice-status", "Connected");
    setStatus("agent-status", agentReady ? "Installed" : "Not installed");
  } catch {
    setStatus("agent-status", "Could not check the skill", true);
  }
  render();
}

$("welcome-next").addEventListener("click", next);
$("close-setup").addEventListener("click", () => window.close());
$("back-button").addEventListener("click", () => {
  const index = steps.indexOf(step);
  if (index > 0) go(steps[index - 1]);
});
$("microphone-next").addEventListener("click", async () => {
  if (microphone === "granted") return next();
  try {
    microphone = await window.talktomeSetup?.requestMicrophone?.() || "unknown";
    setStatus("microphone-status", microphone === "granted" ? "Access on" : "Allow access in macOS Settings", microphone !== "granted");
    render();
  } catch (error) {
    setStatus("microphone-status", error.message, true);
  }
});
$("microphone-skip").addEventListener("click", next);
$("key-visibility").addEventListener("click", () => {
  const input = $("voice-key");
  input.type = input.type === "password" ? "text" : "password";
  $("key-visibility").textContent = input.type === "password" ? "Show" : "Hide";
  $("key-visibility").setAttribute("aria-label", `${input.type === "password" ? "Show" : "Hide"} API key`);
});
$("voice-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (voiceReady) return next();
  const key = $("voice-key").value.trim();
  if (!key) return setStatus("voice-status", "Enter an API key", true);
  busy = true;
  render();
  try {
    const wantsRemember = $("remember-key").checked;
    const saved = await post("/speech/elevenlabs", { api_key: key, remember: wantsRemember });
    const providers = await post("/speech/providers", { stt_provider: "elevenlabs", tts_provider: "elevenlabs" });
    $("voice-key").value = "";
    voiceReady = true;
    speechReady = providers.status === "ready" && Boolean(providers.tts_available);
    speechName = "ElevenLabs";
    setStatus("voice-status", saved.remembered || !wantsRemember ? "Connected" : "Connected. The system keychain did not save the key.");
    if (saved.remembered || !wantsRemember) next();
  } catch (error) {
    setStatus("voice-status", error.message, true);
  } finally {
    busy = false;
    render();
  }
});
$("voice-skip").addEventListener("click", next);
$("local-models").addEventListener("click", () => window.talktomeSetup?.openSettings?.());
$("agent-install").addEventListener("click", async () => {
  if (agentReady) return next();
  busy = true;
  render();
  try {
    const result = await post("/skill/install", {});
    agentReady = Boolean(result.installed);
    setStatus("agent-status", agentReady ? "Installed" : "Could not install the skill", !agentReady);
    if (agentReady) next();
  } catch (error) {
    setStatus("agent-status", error.message, true);
  } finally {
    busy = false;
    render();
  }
});
$("agent-skip").addEventListener("click", next);
for (const button of $("color-list").querySelectorAll("button"))
  button.addEventListener("click", () => setColor(button.dataset.color));
$("color-next").addEventListener("click", next);
$("finish-setup").addEventListener("click", async () => {
  $("finish-setup").disabled = true;
  try {
    await window.talktomeSetup?.complete?.();
    localStorage.removeItem("talktome-setup-step");
  } catch (error) {
    $("finish-status").hidden = false;
    setStatus("finish-status", error.message, true);
    $("finish-setup").disabled = false;
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") window.close();
});

setColor(color);
render();
window.talktomeSetup?.info?.()?.then((info) => {
  nativeNotch = Boolean(info?.nativeNotch);
  steps = setupSteps(nativeNotch);
  step = resumeStep(step, steps);
  if (nativeNotch) setColor(color);
  render();
})?.catch(() => {});
const token = decodeURIComponent(location.hash.replace(/^#token=/, ""));
history.replaceState(null, "", location.pathname);
if (token) {
  post("/auth", { token }).then(readStatus).catch(() => readStatus());
} else {
  readStatus();
}
