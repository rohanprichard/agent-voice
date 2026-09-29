"use strict";

const path = require("node:path");

// The only System Settings panes the pages can open. A page names a pane, and
// never gives a URL.
const SETTINGS_PANES = {
  "login-items": "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
  microphone: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
};

const SYSTEM_COMMAND = "/usr/local/bin/talktome";
// The first lines of every script that agents.py writes.
const COMMAND_HEADER = "#!/bin/sh\n# Written by TalkToMe";

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

function validCommandScript(text) {
  return typeof text === "string" && text.startsWith(COMMAND_HEADER) && text.length < 8192;
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
  loginItemState,
  shouldOfferMove,
  validCommandScript,
};
