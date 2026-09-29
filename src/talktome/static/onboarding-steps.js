export const ALL_STEPS = ["welcome", "microphone", "voice", "agent", "color", "ready"];

// The glow color is for the native notch surface. A Mac without it uses the
// normal pill, so setup skips that step.
export function setupSteps(nativeNotch) {
  return nativeNotch ? ALL_STEPS : ALL_STEPS.filter((step) => step !== "color");
}

// A saved step can be one that this Mac does not show. Continue at the step that
// comes after it.
export function resumeStep(saved, steps) {
  if (steps.includes(saved)) return saved;
  const index = ALL_STEPS.indexOf(saved);
  if (index < 0) return steps[0];
  return ALL_STEPS.slice(index + 1).find((step) => steps.includes(step)) || steps[0];
}

const AGENT_NAMES = { codex: "Codex", claude: "Claude Code", hermes: "Hermes", openclaw: "OpenClaw" };

export function agentNames(hosts) {
  return (hosts || []).map((host) => AGENT_NAMES[host.id] || host.id);
}

export function listText(items, word = "and") {
  if (items.length < 2) return items.join("");
  return `${items.slice(0, -1).join(", ")} ${word} ${items.at(-1)}`;
}

// The sizes come from the server, so this text cannot drift from the catalog.
export function localSpeechNotice(models, kokoroBytes) {
  const whisper = (models || [])
    .filter((model) => Number.isFinite(model.size_mb))
    .map((model) => `${model.name} ${model.size_mb} MB`);
  if (!whisper.length) return "";
  const parts = [listText(whisper, "or")];
  if (kokoroBytes > 0) parts.push(`Kokoro ${Math.round(kokoroBytes / 1e6)} MB`);
  return `Local speech downloads models first: ${parts.join(", and ")}.`;
}
