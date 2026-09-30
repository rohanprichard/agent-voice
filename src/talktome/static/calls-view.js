const AGENTS = {
  codex: "Codex",
  claude: "Claude Code",
  hermes: "Hermes",
  openclaw: "OpenClaw",
  generic: "Agent",
};

const OUTCOMES = {
  answered: "Answered",
  missed: "Missed",
  declined: "Declined",
  failed: "Failed",
};

export function agentLabel(agent) {
  return AGENTS[agent] || "Agent";
}

export function outcomeLabel(call) {
  if (call.callback && call.outcome === "answered") return "You called";
  return OUTCOMES[call.outcome] || "Ringing";
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const whole = Math.round(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

export function relativeTime(iso, now = Date.now()) {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "";
  const seconds = Math.max(0, (now - time) / 1000);
  if (seconds < 45) return "Just now";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} hr ago`;
  const days = Math.floor(seconds / 86400);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return new Date(time).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// The line under the caller's name: agent, when, how long, and how it ended.
export function callMeta(call, now = Date.now()) {
  return [
    agentLabel(call.agent),
    relativeTime(call.started_at, now),
    call.outcome === "answered" ? formatDuration(call.duration) : "",
    outcomeLabel(call),
  ].filter(Boolean);
}
