// Show a short summary and expandable details from the agent host.
// The page inserts all content as text.

export const MAX_TOOL = 60;
export const MAX_COMMAND = 160;

export function truncate(value, limit) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function firstText(details, keys) {
  for (const key of keys) {
    const value = details[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

export function approvalSummary(approval) {
  const details =
    approval?.details && typeof approval.details === "object" && !Array.isArray(approval.details)
      ? approval.details
      : {};
  // Hermes names every request "approval", which says nothing about the tool.
  const action = typeof approval?.action === "string" && approval.action !== "approval"
    ? approval.action
    : "";
  const tool = firstText(details, ["tool", "tool_name", "name"]) || action || "A tool";
  let command = firstText(details, ["command", "cmd", "description", "path", "file"]);
  if (!command) {
    try {
      command = JSON.stringify(approval?.details ?? "") || "";
    } catch {
      command = "";
    }
    if (command === "{}" || command === '""') command = "";
  }
  return { tool: truncate(tool, MAX_TOOL), command: truncate(command, MAX_COMMAND) };
}

export function approvalDetails(approval) {
  const sections = [];
  if (typeof approval?.action === "string") sections.push(`Action: ${approval.action}`);
  const details = approval?.details;
  if (details && typeof details === "object") {
    const command = firstText(details, ["command", "cmd"]);
    if (command) sections.push(`Command:\n${command}`);
  }
  // Retain all fields and the original command line breaks.
  if (details != null) {
    sections.push(typeof details === "string" ? details : JSON.stringify(details, null, 2));
  }
  return sections.join("\n\n") || "No details supplied.";
}
