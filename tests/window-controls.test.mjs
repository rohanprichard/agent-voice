import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// These checks read the shipped source. They guard the window lifecycle and the
// call controls without starting the application, which the desktop smoke tests
// do separately.

const read = (relative) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8");

const main = read("../desktop/main.cjs");
const preload = read("../desktop/preload.cjs");
const app = read("../src/talktome/static/app.js");
const html = read("../src/talktome/static/index.html");
const callCss = read("../src/talktome/static/call.css");

test("Closing the main window hides it and keeps the app alive", () => {
  assert.match(
    main,
    /window\.on\("close", \(event\) => \{[\s\S]*?event\.preventDefault\(\);[\s\S]*?mainDismissed = [^;]+;[\s\S]*?window\.hide\(\);/,
    "The close handler must prevent the close and hide the window.",
  );
});

test("The app does not stop when every window is closed", () => {
  const handler = main.match(
    /app\.on\("window-all-closed", \(\) => \{([\s\S]*?)\n\}\);/,
  );
  assert.ok(handler, "The window-all-closed handler is missing.");
  assert.doesNotMatch(
    handler[1],
    /app\.quit\(\)/,
    "Only the Quit command may stop the app.",
  );
});

test("The Settings menu item opens settings", () => {
  assert.match(
    main,
    /label: "Settings…",\s*accelerator: "CmdOrCtrl[^"]*",\s*click: openSettings,/,
  );
});

test("The menu bar item opens settings", () => {
  // During a call or setup the click shows that window. Otherwise it opens settings.
  assert.match(main, /tray\.on\("click", \(\) => \{[\s\S]*?else openSettings\(\);\s*\}\);/);
  assert.match(main, /label: "Open Settings",\s*click: openSettings,/);
});

test("The main process decides visibility through the lifecycle rules", () => {
  assert.match(main, /const \{ computeVisibility \} = require\("\.\/lifecycle\.cjs"\)/);
  assert.match(main, /computeVisibility\(\{/);
  assert.match(main, /ipcMain\.handle\("talktome:onboarding"/);
  assert.match(main, /ipcMain\.handle\("talktome:hide-window"/);
});

test("The call window refuses a late show after the call ends", () => {
  assert.match(
    main,
    /if \(callState\.live[^)]*\)?\) callWindow\.showInactive\(\);/,
    "A window that finishes loading after a call must not appear.",
  );
});

test("The renderer reports setup and can hide the window", () => {
  for (const name of ["setOnboarding", "hideWindow"]) {
    assert.match(preload, new RegExp(name));
    assert.match(app, new RegExp(name));
  }
});

test("Opening settings does not stop reply audio", () => {
  const navigation = app.match(/function navigate\(next\) \{([\s\S]*?)\n\}/);
  assert.ok(navigation);
  assert.doesNotMatch(navigation[1], /stopPlayback\(\)/);
  const openSettings = app.match(/onOpenSettings\?\.\(\(\) => \{([\s\S]*?)\n\}\);/);
  assert.ok(openSettings);
  assert.doesNotMatch(openSettings[1], /stopPlayback\(\)/);
});

test("The main window has no conversation start control or composer", () => {
  for (const id of [
    "new-conversation",
    "call-button",
    "message-form",
    "message-input",
    "send-button",
    "mute-button",
    "suggestions",
  ])
    assert.doesNotMatch(
      html,
      new RegExp(`id="${id}"`),
      `${id} must not be in the main window`,
    );
  // The renderer must not start a call. The agent starts every call.
  assert.doesNotMatch(app, /post\("\/call\/start"/);
});

test("Every page uses the shared tokens and theme", () => {
  for (const page of ["index.html", "onboarding.html", "call.html"]) {
    const source = read(`../src/talktome/static/${page}`);
    assert.match(source, /<script src="\/theme\.js"><\/script>/, `${page} must load theme.js`);
    assert.match(source, /href="\/tokens\.css"/, `${page} must load tokens.css`);
  }
  assert.match(callCss, /--end: var\(--destructive\);/);
  assert.match(callCss, /#ringing button#accept \{[\s\S]*?background: var\(--answer\);/);
});

test("The visible end call circle is 36 px in a 44 px target", () => {
  assert.match(callCss, /--end-size: 36px;/);
  assert.match(callCss, /--end-target: 44px;/);
  assert.match(
    callCss,
    /#pill button#end \{[\s\S]*?width: var\(--end-target\);/,
    "The end button must use the 44 px target.",
  );
  assert.match(
    callCss,
    /#pill button#end \.icon \{[\s\S]*?width: var\(--end-size\);[\s\S]*?height: var\(--end-size\);[\s\S]*?background: var\(--end\);/,
    "The red circle must use the 36 px size.",
  );
});

test("The transcript stays in the call surface", () => {
  const callHtml = read("../src/talktome/static/call.html");
  assert.match(callHtml, /id="transcript"[\s\S]*?id="transcript-list"/);
});

// The call surface placement setting. The default stays at the bottom, and the
// top center placement keeps the transcript below the pill.

test("The Settings screen offers the two call placements", () => {
  assert.match(html, /id="pill-placement"/);
  assert.match(html, /<option value="bottom">Bottom<\/option>/);
  assert.match(html, /<option value="top-center">Top center<\/option>/);
  assert.match(html, /Top center sits below the menu bar\./);
});

test("The placement setting persists and reaches the main process", () => {
  assert.match(app, /talktome-pill-placement/);
  assert.match(app, /setPillPlacement\?\.\(savedPlacement\(\)\)/);
  assert.match(app, /setPillPlacement\?\.\(placement\)/);
  assert.match(preload, /setPillPlacement/);
  assert.match(main, /ipcMain\.handle\("talktome:pill-placement"/);
  assert.match(main, /callPlacement = value === "top-center" \? "top-center" : "bottom"/);
});

test("The placement setting stays available during a call", () => {
  const lock = app.match(
    /for \(const id of \[([^\]]*)\]\)\s*\$\(id\)\.disabled = active/,
  );
  assert.ok(lock, "The settings lock list was not found.");
  assert.doesNotMatch(lock[1], /pill-placement/);
});

test("The main process measures the call window from the chosen placement", () => {
  assert.match(
    main,
    /pillBounds\(area, \{ open: callTranscriptOpen, placement: callPlacement \}\)/,
  );
  assert.match(main, /anchoredBounds\([\s\S]*?callPlacement,[\s\S]*?\)/);
});

test("The call surface puts the transcript below the pill at the top center", () => {
  const callJs = read("../src/talktome/static/call.js");
  assert.match(callJs, /state\.placement/);
  assert.match(
    callCss,
    /#surface\[data-placement="top-center"\]\s*\{[\s\S]*?justify-content: flex-start;/,
  );
  assert.match(
    callCss,
    /#surface\[data-placement="top-center"\] #pill,[\s\S]*?order: -1;/,
  );
});

test("Dark is the default theme in every window", () => {
  const theme = read("../src/talktome/static/theme.js");
  assert.match(theme, /const DEFAULT = "dark";/);
  // A missing or unknown saved value falls back to the default, not to System.
  assert.match(theme, /\["system", "light", "dark"\]\.includes\(value\) \? value : DEFAULT/);
  assert.doesNotMatch(theme, /: "system"/);
  assert.match(app, /themePreference \|\| "dark"/);
  // The main process starts dark before it makes a window.
  const start = main.indexOf('nativeTheme.themeSource = "dark";');
  assert.ok(start > 0, "The main process must start in dark mode.");
  assert.ok(start < main.indexOf("window = new BrowserWindow("));
  assert.ok(start < main.indexOf("void startNotchGlow();"));
});

test("The native notch is off, even when an old helper build is on disk", () => {
  assert.match(main, /const NATIVE_NOTCH = false;/);
  const glow = main.slice(main.indexOf("async function startNotchGlow()"));
  const guard = glow.indexOf('if (!NATIVE_NOTCH || process.platform !== "darwin") return;');
  assert.ok(guard > 0 && guard < glow.indexOf("existsSync(binary)"));
  // Nothing at startup waits on the helper.
  assert.doesNotMatch(main, /spawnSync/);
});

test("A missing or invalid saved theme starts dark, and System still works", () => {
  const source = read("../src/talktome/static/theme.js");
  const run = (saved, systemDark = false) => {
    const root = { dataset: {} };
    const window = {
      matchMedia: () => ({ matches: systemDark, addEventListener() {} }),
      addEventListener() {},
    };
    const localStorage = {
      getItem: () => saved,
      setItem: (_key, value) => { saved = value; },
    };
    new Function("window", "document", "localStorage", source)(
      window, { documentElement: root }, localStorage,
    );
    return { root, window };
  };
  for (const saved of [null, "", "sepia"]) {
    const { root } = run(saved);
    assert.equal(root.dataset.theme, "dark", `saved ${JSON.stringify(saved)}`);
    assert.equal(root.dataset.themePreference, "dark");
  }
  assert.equal(run("light", true).root.dataset.theme, "light");
  assert.equal(run("system", false).root.dataset.theme, "light");
  assert.equal(run("system", true).root.dataset.theme, "dark");
  const { root, window } = run(null);
  window.setTalktomeTheme("system");
  assert.equal(root.dataset.themePreference, "system");
  window.setTalktomeTheme("nonsense");
  assert.equal(root.dataset.themePreference, "dark");
});

test("The ring can be declined on the pill, and it shows a notification", () => {
  const callHtml = read("../src/talktome/static/call.html");
  const callJs = read("../src/talktome/static/call.js");
  assert.match(callHtml, /<button id="decline" aria-label="Decline the call"/);
  assert.match(callJs, /declineButton\.addEventListener\("click", \(\) => command\("decline"\)\)/);
  assert.match(main, /\["mute", "interrupt", "end", "accept", "decline",/);
  assert.match(main, /new Notification\(\{/);
  assert.match(main, /ringNotice\.on\("click", \(\) => restoreCallWindow\(callToken\)\)/);
  // The surface stops its tone a little after the server's 30 second ring.
  assert.match(callJs, /const RING_GUARD_MS = 32000;/);
});
