import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const {
  SETTINGS_PANES,
  adminInstallArgs,
  loginItemState,
  shouldOfferMove,
  validCommandScript,
} = require("../desktop/install.cjs");

const main = readFileSync(fileURLToPath(new URL("../desktop/main.cjs", import.meta.url)), "utf8");

test("A development run cannot register a login item", () => {
  assert.deepEqual(loginItemState({ packaged: false, platform: "darwin", settings: { openAtLogin: true } }), {
    available: false,
    enabled: false,
    needsApproval: false,
  });
});

test("A login item that waits for approval counts as on and asks for approval", () => {
  assert.deepEqual(
    loginItemState({ packaged: true, platform: "darwin", settings: { openAtLogin: false, status: "requires-approval" } }),
    { available: true, enabled: true, needsApproval: true },
  );
  assert.deepEqual(
    loginItemState({ packaged: true, platform: "darwin", settings: { openAtLogin: true, status: "enabled" } }),
    { available: true, enabled: true, needsApproval: false },
  );
  assert.equal(
    loginItemState({ packaged: true, platform: "darwin", settings: { status: "not-registered" } }).enabled,
    false,
  );
});

test("Only a packaged app outside Applications is asked to move, and only once", () => {
  const base = { packaged: true, platform: "darwin", inApplications: false, declined: false };
  assert.equal(shouldOfferMove(base), true);
  assert.equal(shouldOfferMove({ ...base, declined: true }), false);
  assert.equal(shouldOfferMove({ ...base, inApplications: true }), false);
  assert.equal(shouldOfferMove({ ...base, packaged: false }), false);
});

test("Only a script that TalkToMe wrote is installed for all users", () => {
  assert.equal(validCommandScript("#!/bin/sh\n# Written by TalkToMe so an agent can run it.\n"), true);
  assert.equal(validCommandScript("#!/bin/sh\nrm -rf ~\n"), false);
  assert.equal(validCommandScript(`#!/bin/sh\n# Written by TalkToMe\n${"x".repeat(9000)}`), false);
  assert.equal(validCommandScript(null), false);
});

test("The administrator script takes its paths as arguments", () => {
  const source = "/tmp/it's \"odd\"/talktome";
  const args = adminInstallArgs(source);
  const script = args.filter((_, index) => args[index - 1] === "-e").join("\n");
  assert.ok(!script.includes(source));
  assert.match(script, /with administrator privileges/);
  assert.deepEqual(args.slice(-3), [source, "/usr/local/bin/talktome", "/usr/local/bin"]);
});

test("Pages can open only the named System Settings panes", () => {
  assert.deepEqual(Object.keys(SETTINGS_PANES).sort(), ["login-items", "microphone"]);
  assert.match(main, /Object\.hasOwn\(SETTINGS_PANES, pane\)/);
});

test("Only the Settings window can ask for the administrator install", () => {
  const handler = main.split('ipcMain.handle("talktome:install-command-all-users"')[1];
  assert.ok(handler);
  assert.match(handler.slice(0, 200), /requireMainFrame\(event\)/);
  for (const channel of ["login-item", "set-login-item", "open-system-settings"]) {
    const body = main.split(`ipcMain.handle("talktome:${channel}"`)[1];
    assert.match(body.slice(0, 200), /requireSetupFrame\(event\)/, channel);
  }
});
