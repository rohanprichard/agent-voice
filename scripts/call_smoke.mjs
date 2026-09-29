// Verify the floating call surface as a real desktop window.
//
// A page screenshot cannot show whether the window is transparent, where macOS
// actually put it, or whether it is above other applications. This drives the
// real Electron application and inspects the real BrowserWindows, which is the
// only way to check the parts of this interface that are window behaviour rather
// than web page rendering.
//
//   npm run test:call

import { _electron as electron } from "@playwright/test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import net from "node:net";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const require = createRequire(import.meta.url);
const { PILL_HEIGHT, PILL_WIDTH, SHADOW_MARGIN } = require("../desktop/geometry.cjs");

const root = fileURLToPath(new URL("..", import.meta.url));
const directory = mkdtempSync(path.join(tmpdir(), "talktome-call-test-"));
const server = net.createServer();
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
await new Promise((resolve) => server.close(resolve));
const origin = `http://127.0.0.1:${port}`;
const env = {
  ...process.env,
  TALKTOME_DATA_DIR: directory,
  TALKTOME_PORT: String(port),
  TALKTOME_URL: origin,
};
delete env.ELECTRON_RUN_AS_NODE;

const report = [];
const check = (name, ok, detail = "") => {
  report.push({ name, ok, detail });
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  ${detail}` : ""}`);
};

const SURFACE = "call";

/**
 * Every window the main process owns, with the facts a screenshot cannot show.
 *
 * The call surface is identified by its URL, because the window title comes from
 * the loaded document and is not something this test should depend on.
 */
const windows = (app) =>
  app.evaluate(({ BrowserWindow }, marker) => {
    return BrowserWindow.getAllWindows().map((win) => ({
      surface: win.webContents.getURL().includes(`${marker}.html`),
      visible: win.isVisible(),
      focused: win.isFocused(),
      alwaysOnTop: win.isAlwaysOnTop(),
      resizable: win.isResizable(),
      movable: win.isMovable(),
      bounds: win.getBounds(),
    }));
  }, SURFACE).then((all) => all.map((win) => ({ ...win, title: win.surface ? SURFACE : "main" })));

const surfaceOf = (all) => all.find((win) => win.title === SURFACE);
const mainOf = (all) => all.find((win) => win.title === "main");

const desktop = await electron.launch({
  args: [root, "--no-sandbox"],
  env,
  timeout: 40000,
});
let window;
try {
  window = await desktop.firstWindow();
  await window.waitForSelector("#app");
  const token = readFileSync(path.join(directory, "token"), "utf8").trim();
  const api = async (route, body) => {
    const response = await fetch(`${origin}/v1${route}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`${route} failed: ${response.status}`);
    return response.json();
  };

  // This test runs after setup. The main window must wait hidden in the menu
  // bar, and it must not appear again when a call ends.
  await window.evaluate(() =>
    localStorage.setItem("talktome-onboarding", "complete"),
  );
  await window.reload();
  await window.waitForSelector("#page-setup:not(.hidden)");

  const before = await windows(desktop);
  check("Before a call there is one window", before.length === 1, `${before.length} window(s)`);
  check("After setup the main window waits hidden", !mainOf(before).visible);

  // Driven through the API rather than the interface so the test does not depend
  // on a downloaded speech model. A cooperative agent rings, and the ring is
  // answered at once. The renderer polls the room and reports the live call to
  // the main process either way, which is the path being tested.
  const thread = "call-smoke";
  const ringAndAnswer = async () => {
    const ring = await api("/attach/start", {
      thread, cwd: root, agent: "generic", name: "Call test agent",
    });
    await api("/attach/accept", { ring_id: ring.ring.id });
    return (await api("/state")).room;
  };
  // The agent side speaks through the same inbox commands an agent runs.
  const talktome = async (...args) => {
    const python = path.join(root, ".venv", "bin", "python");
    const { stdout } = await promisify(execFile)(python, ["-m", "talktome", ...args], { env });
    return JSON.parse(stdout);
  };
  const call = await ringAndAnswer();

  // The call surface is a second window created by the main process.
  let callWindow = null;
  for (let attempt = 0; attempt < 60 && !callWindow; attempt++) {
    const all = await windows(desktop);
    callWindow = surfaceOf(all) || null;
    if (!callWindow) await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert.ok(callWindow, "The call surface window never appeared.");
  const mainWindow = mainOf(await windows(desktop));

  check("The call surface is on screen", callWindow.visible);
  check("The main window is hidden during a call", !mainWindow.visible);
  check("The call surface floats above other applications", callWindow.alwaysOnTop);
  check("The call surface cannot be resized by the user", !callWindow.resizable);
  check("The call surface can be dragged", callWindow.movable);
  // The window is the pill plus the shadow ring and nothing else. Every
  // transparent pixel still takes the mouse, so a larger window would swallow
  // clicks meant for the application underneath.
  const expected = {
    width: PILL_WIDTH + SHADOW_MARGIN * 2,
    height: PILL_HEIGHT + SHADOW_MARGIN * 2,
  };
  check(
    "The window is exactly the pill plus its shadow ring",
    callWindow.bounds.width === expected.width && callWindow.bounds.height === expected.height,
    `${callWindow.bounds.width}x${callWindow.bounds.height}, expected ${expected.width}x${expected.height}`,
  );

  // Positioned against the usable area of its display, centred, near the bottom.
  const geometry = await desktop.evaluate(({ screen, BrowserWindow }, marker) => {
    const win = BrowserWindow.getAllWindows().find((item) =>
      item.webContents.getURL().includes(`${marker}.html`),
    );
    const bounds = win.getBounds();
    const display = screen.getDisplayMatching(bounds);
    return { bounds, workArea: display.workArea };
  }, SURFACE);
  const centre = geometry.bounds.x + geometry.bounds.width / 2;
  const workCentre = geometry.workArea.x + geometry.workArea.width / 2;
  const bottomGap =
    geometry.workArea.y + geometry.workArea.height - (geometry.bounds.y + geometry.bounds.height);
  check("The call surface is horizontally centred", Math.abs(centre - workCentre) <= 1,
    `centre ${centre} vs ${workCentre}`);
  check("The call surface sits just above the usable bottom edge",
    bottomGap >= 12 && bottomGap <= 40, `${bottomGap}px`);

  // The pill must not steal focus from whatever the user was doing.
  const focused = (await windows(desktop)).some((win) => win.focused);
  check("Opening the call surface does not take focus from the user's work", !focused);

  const pillPage = desktop
    .windows()
    .find((page) => page.url().includes(`${SURFACE}.html`));
  assert.ok(pillPage, "The call surface page was not found.");
  await pillPage.getByRole("button", { name: "Transcript panel" }).click();
  await new Promise((resolve) => setTimeout(resolve, 500));
  const opened = await desktop.evaluate(({ BrowserWindow }, marker) => {
    const win = BrowserWindow.getAllWindows().find((item) =>
      item.webContents.getURL().includes(`${marker}.html`),
    );
    return win.getBounds();
  }, SURFACE);
  check("The transcript opens by growing the window upward",
    opened.height > callWindow.bounds.height, `${opened.height}px tall`);
  check("The pill's bottom edge does not move when the transcript opens",
    opened.y + opened.height === callWindow.bounds.y + callWindow.bounds.height,
    `${opened.y + opened.height} vs ${callWindow.bounds.y + callWindow.bounds.height}`);
  check("The transcript keeps the same width", opened.width === callWindow.bounds.width);

  await pillPage.getByRole("button", { name: "Close transcript", exact: true }).click();
  await new Promise((resolve) => setTimeout(resolve, 400));
  const closed = await desktop.evaluate(({ BrowserWindow }, marker) => {
    const win = BrowserWindow.getAllWindows().find((item) =>
      item.webContents.getURL().includes(`${marker}.html`),
    );
    return win.getBounds();
  }, SURFACE);
  check("Closing the transcript returns the exact starting bounds",
    JSON.stringify(closed) === JSON.stringify(callWindow.bounds),
    `${JSON.stringify(closed)} vs ${JSON.stringify(callWindow.bounds)}`);

  // The agent's own audio has to reach the pink thread. A reply is synthesized for
  // real through the local speech engine, played by the hidden window, measured
  // there, and relayed here, so this covers the whole path rather than a mock.
  const spoken = await api("/call/text", { call_id: call.call_id, text: "Say something." });
  const heard = await talktome("listen", "--thread", thread, "--timeout", "5");
  assert.equal(heard.pending?.turn_id, spoken.turn_id, "The agent did not hear the turn.");
  await talktome(
    "reply", "--thread", thread, "--call-id", call.call_id, "--turn-id", spoken.turn_id,
    "--item-id", "smoke-1", "--text", "This reply is long enough to be measured while it plays.",
  );
  let speaker = null;
  for (let attempt = 0; attempt < 60 && !speaker; attempt++) {
    speaker = await pillPage.evaluate(
      () => document.getElementById("surface").dataset.speaker,
    );
    if (speaker !== "agent" && speaker !== "both") {
      speaker = null;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  check("The agent's audio drives the agent thread", speaker !== null, `speaker=${speaker}`);

  // The user thread travels the same relay. The microphone's own speech detection
  // is what the desktop suite drives for real; this checks that the flag reaches
  // the thread, by reporting a call state with the user speaking.
  await window.evaluate(() =>
    window.talktomeDesktop.setCallState({
      live: true,
      muted: false,
      state: "active",
      userActive: true,
      agentActive: false,
    }),
  );
  let userHeard = null;
  for (let attempt = 0; attempt < 40 && !userHeard; attempt++) {
    const seen = await pillPage.evaluate(
      () => document.getElementById("surface").dataset.speaker,
    );
    userHeard = seen === "user" || seen === "both" ? seen : null;
    if (!userHeard) await new Promise((resolve) => setTimeout(resolve, 100));
  }
  check("The user speaking drives the user thread", userHeard !== null,
    `speaker=${userHeard ?? "null"}`);

  // A dragged position is remembered rather than reset by the next resize. Moving
  // the window from here looks the same to the application as a user drag.
  const dragged = { x: callWindow.bounds.x - 60, y: callWindow.bounds.y - 90 };
  await desktop.evaluate(({ BrowserWindow }, position) => {
    const win = BrowserWindow.getAllWindows().find((item) =>
      item.webContents.getURL().includes("call.html"),
    );
    const bounds = win.getBounds();
    win.setBounds({ ...bounds, x: position.x, y: position.y });
  }, dragged);
  await new Promise((resolve) => setTimeout(resolve, 400));
  await pillPage.getByRole("button", { name: "Transcript panel" }).click();
  await new Promise((resolve) => setTimeout(resolve, 500));
  const afterDrag = await desktop.evaluate(({ BrowserWindow }) => {
    const win = BrowserWindow.getAllWindows().find((item) =>
      item.webContents.getURL().includes("call.html"),
    );
    return win.getBounds();
  });
  check("A dragged pill keeps its position when the transcript opens",
    afterDrag.x === dragged.x, `x ${afterDrag.x}, expected ${dragged.x}`);
  check("A dragged pill grows upward from where it was put",
    afterDrag.y + afterDrag.height === dragged.y + callWindow.bounds.height,
    `bottom ${afterDrag.y + afterDrag.height}, expected ${dragged.y + callWindow.bounds.height}`);

  // A call can also be ended from the terminal, which has no call identifier and no
  // window to press. That arrives by a different route — a server hangup the hidden
  // window notices on its next poll — so it is worth its own check rather than
  // assuming it behaves like the button.
  await api("/hangup", {});
  let goneByTerminal = false;
  for (let attempt = 0; attempt < 40 && !goneByTerminal; attempt++) {
    const all = await windows(desktop);
    goneByTerminal = !surfaceOf(all)?.visible && !mainOf(all)?.visible;
    if (!goneByTerminal) await new Promise((resolve) => setTimeout(resolve, 250));
  }
  check(
    "Ending the call from the terminal hides the surface and leaves the main window hidden",
    goneByTerminal,
  );

  // Put a call back so the button path below is exercised as well.
  await ringAndAnswer();

  // Ending the call from the surface must not show the large window again.
  await pillPage.getByRole("button", { name: "End call" }).click();
  let restored = false;
  for (let attempt = 0; attempt < 40 && !restored; attempt++) {
    const all = await windows(desktop);
    restored = !surfaceOf(all)?.visible && !mainOf(all)?.visible;
    if (!restored) await new Promise((resolve) => setTimeout(resolve, 250));
  }
  check(
    "Ending the call hides the surface and leaves the main window hidden",
    restored,
  );

  const errors = [];
  window.on("pageerror", (error) => errors.push(error.message));
  check("No page errors in the main window", errors.length === 0, errors.join("; "));
} finally {
  await desktop.close();
}

const failed = report.filter((entry) => !entry.ok);
console.log(`\n${report.length - failed.length}/${report.length} checks passed`);
process.exitCode = failed.length ? 1 : 0;
