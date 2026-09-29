"use strict";

const path = require("node:path");

// The only System Settings panes the pages can open. A page names a pane, and
// never gives a URL.
const SETTINGS_PANES = {
  "login-items": "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
  microphone: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
};

const SYSTEM_COMMAND = "/usr/local/bin/talktome";

// The same values as agents.py. A test compares the two scripts byte for byte.
const APP_ID = "com.rohanprichard.talktome";
const SERVER_IN_APP = "Contents/Resources/talktome-server/talktome-server";
const APP_FOLDERS = ["/Applications/TalkToMe.app", "$HOME/Applications/TalkToMe.app"];

// Python's shlex.quote.
function shellQuote(value) {
  if (!value) return "''";
  if (/^[\w@%+=:,./-]+$/.test(value)) return value;
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

// The `talktome` script that agents.py writes for the same interpreter and
// launcher. The main process installs this text, and never a file that another
// process could change before the administrator prompt.
function commandScript(python, launcher) {
  const lines = ["#!/bin/sh", "# Written by TalkToMe so an agent can run `talktome call`."];
  if (!python.endsWith(`/${SERVER_IN_APP}`)) {
    if (launcher) lines.push(`export TALKTOME_LAUNCH=${shellQuote(launcher)}`);
    lines.push(`exec ${shellQuote(python)} -m talktome "$@"`);
    return `${lines.join("\n")}\n`;
  }
  const folders = APP_FOLDERS.map((folder) => `"${folder}"`).join(" ");
  lines.push(
    "# It finds the app each time it runs, so it keeps working after the app moves.",
    `server="${SERVER_IN_APP}"`,
    "app=",
    `for candidate in ${folders}; do`,
    '  if [ -x "$candidate/$server" ]; then app=$candidate; break; fi',
    "done",
    'if [ -z "$app" ]; then',
    `  app=$(mdfind "kMDItemCFBundleIdentifier == '${APP_ID}'" 2>/dev/null |`,
    "    grep -v -e /AppTranslocation/ -e '^/Volumes/' | while IFS= read -r candidate; do",
    '      if [ -x "$candidate/$server" ]; then echo "$candidate"; break; fi',
    "    done)",
    "fi",
    'if [ -z "$app" ]; then',
    '  echo "TalkToMe was not found. Move TalkToMe to the Applications folder, then try again." >&2',
    "  exit 1",
    "fi",
    'export TALKTOME_LAUNCH="open -g -a \\"$app\\""',
    'exec "$app/$server" -m talktome "$@"',
  );
  return `${lines.join("\n")}\n`;
}

function loginItemState({ packaged, platform, settings }) {
  // A development run would register the Electron binary, not TalkToMe.
  if (!packaged || platform !== "darwin")
    return { available: false, enabled: false, needsApproval: false };
  const status = settings?.status;
  return {
    available: true,
    enabled: Boolean(settings?.openAtLogin) || status === "enabled" || status === "requires-approval",
    needsApproval: status === "requires-approval",
  };
}

function shouldOfferMove({ packaged, platform, inApplications, declined }) {
  return Boolean(packaged) && platform === "darwin" && !inApplications && !declined;
}

// The paths go in as arguments, so no path is ever part of the script text.
function adminInstallArgs(source, target = SYSTEM_COMMAND) {
  return [
    "-e", "on run argv",
    "-e",
    'do shell script "/bin/mkdir -p " & quoted form of (item 3 of argv) & ' +
      '" && /usr/bin/install -m 0755 " & quoted form of (item 1 of argv) & " " & ' +
      "quoted form of (item 2 of argv) " +
      'with prompt "TalkToMe wants to add the talktome command for all users." ' +
      "with administrator privileges",
    "-e", "end run",
    source, target, path.dirname(target),
  ];
}

module.exports = {
  SETTINGS_PANES,
  SYSTEM_COMMAND,
  adminInstallArgs,
  commandScript,
  loginItemState,
  shouldOfferMove,
};
