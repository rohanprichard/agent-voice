const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  session,
  systemPreferences,
  Menu,
  Tray,
  nativeImage,
  nativeTheme,
  screen,
  shell,
} = require("electron");
const { execFile, spawn, spawnSync } = require("node:child_process");
const {
  readFileSync,
  mkdirSync,
  mkdtempSync,
  existsSync,
  rmSync,
  writeFileSync,
} = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  TRANSCRIPT_HEIGHT,
  TRANSCRIPT_WIDTH,
  anchoredBounds,
  pillBounds,
  transcriptBounds,
} = require("./geometry.cjs");
const { computeVisibility } = require("./lifecycle.cjs");
const {
  SETTINGS_PANES,
  adminInstallArgs,
  commandScript,
  loginItemState,
  shouldOfferMove,
} = require("./install.cjs");

app.setName("talktome");
if (process.env.TALKTOME_DATA_DIR) {
  app.setPath("userData", process.env.TALKTOME_DATA_DIR);
}
const port = Number(process.env.TALKTOME_PORT || 8765);
const origin = `http://127.0.0.1:${port}`;
const root = path.resolve(__dirname, "..");
// A live call takes over the desktop as a floating pill and the main window
// steps out of the way. Setting TALKTOME_FLOATING_CALL=0 turns off the call
// window.
const floatingCall = process.env.TALKTOME_FLOATING_CALL !== "0";
let backend;
let notchGlow;
let nativeNotch = false;
let nativePillBounds = null;
let nativeGeometry = null;
let refreshCallSurfaces = () => {};
let glowColor = "amber";
let window;
let onboardingWindow;
let callWindow;
let callToken;
// True once the renderer reports that setup is not complete. The main window
// shows only after that report, so a later launch never flashes the main window
// before it returns to the menu bar.
let onboardingActive = false;
// True while the user has settings open. Closing settings clears it and hides
// the window; the renderer keeps running.
let settingsOpen = false;
// True after the user closes the window. It stops setup from showing the window
// again until the user opens settings.
let mainDismissed = false;
// The display the call started on, so the pill does not jump between monitors.
let callDisplay;
let callTranscriptOpen = false;
// The size the user chose for the transcript panel, kept for the rest of this
// run so a close and a later open use the same size. The applied size can be
// smaller when the work area cannot hold the request.
let callTranscriptSize = { width: TRANSCRIPT_WIDTH, height: TRANSCRIPT_HEIGHT };
let callTranscriptApplied = { ...callTranscriptSize };
// An approval request shows in the transcript panel. The panel opens for it and
// is never smaller than this while the request waits. The main process closes
// the panel again only if it opened the panel for the request.
const APPROVAL_PANEL = { width: 300, height: 250 };
let callApproval = false;
let approvalOpenedPanel = false;
// Where the user put the call surface: "bottom" or "top-center". The hidden
// renderer reports this setting, and the default stays at the bottom.
let callPlacement = "bottom";
// Where the user dragged the pill. The anchor records both horizontal edges,
// so the placement decides which edge stays fixed across a resize. Null until
// the user moves it.
let callAnchor = null;
// The bounds this process last applied, so its own moves are not mistaken for a
// drag and turned into an anchor.
let appliedBounds = null;
let tray;
let callState = { live: false, muted: false, state: "idle" };
let quitting = false;
let shutdownStarted = false;
let backendLog = "";

function glowMode() {
  if (callState.ring) return "ringing";
  if (!callState.live) return "idle";
  if (callState.agentActive) return "speaking";
  if (callState.muted) return "muted";
  if (callState.userActive) return "listening";
  if (callState.thinking) return "thinking";
  return "connected";
}

function updateNotchGlow() {
  if (!notchGlow || !notchGlow.stdin.writable) return;
  notchGlow.stdin.write(`${JSON.stringify({
    mode: glowMode(),
    color: glowColor,
    name: callState.ring?.name || callState.name || "TalkToMe",
    muted: String(callState.muted),
    callId: callState.callId || "",
    ringId: callState.ring?.id || "",
    startedAt: Number.isFinite(Date.parse(callState.startedAt))
      ? String(Date.parse(callState.startedAt) / 1000) : "",
  })}\n`);
}

function startNotchGlow() {
  if (process.platform !== "darwin") return;
  const binary = app.isPackaged
    ? path.join(process.resourcesPath, "notch-surface", "NotchSurface.app", "Contents", "MacOS", "NotchSurface")
    : path.join(root, "dist", "native", "NotchSurface.app", "Contents", "MacOS", "NotchSurface");
  if (!existsSync(binary)) return;
  const measured = spawnSync(binary, ["--geometry"], { encoding: "utf8", timeout: 2000 });
  try {
    nativeGeometry = JSON.parse(measured.stdout);
    if (!Number.isFinite(nativeGeometry.notchDepth) || nativeGeometry.notchDepth <= 0)
      return;
  } catch { return; }
  const child = spawn(binary, [], { stdio: ["pipe", "pipe", "pipe"] });
  notchGlow = child;
  const readyTimer = setTimeout(() => {
    if (notchGlow === child && !nativeNotch) child.kill();
  }, 5000);
  function setNativeAvailable(available) {
    if (nativeNotch === available) return;
    nativeNotch = available;
    if (callWindow && !callWindow.isDestroyed()) callWindow.destroy();
    refreshCallSurfaces();
  }
  let output = "";
  child.stdout.on("data", (data) => {
    output += data.toString();
    while (output.includes("\n")) {
      const end = output.indexOf("\n");
      const line = output.slice(0, end);
      output = output.slice(end + 1);
      let message;
      try { message = JSON.parse(line); } catch { continue; }
      if (message.event === "ready") {
        clearTimeout(readyTimer);
        if (message.geometry && Number.isFinite(message.geometry.notchDepth))
          nativeGeometry = { ...nativeGeometry, ...message.geometry };
        // A display with no notch cannot hold the native surface. The normal
        // pill takes over, and the helper must not keep running.
        if (!(nativeGeometry.notchDepth > 0)) {
          child.kill();
          continue;
        }
        setNativeAvailable(true);
        continue;
      }
      if (message.event === "unavailable") {
        clearTimeout(readyTimer);
        nativePillBounds = null;
        setNativeAvailable(false);
        child.kill();
        continue;
      }
      if (message.event === "pill-bounds") {
        const bounds = message.bounds;
        if (bounds && [bounds.x, bounds.y, bounds.width, bounds.height].every(Number.isFinite)) {
          nativePillBounds = bounds;
          if (!callAnchor) applyCallBounds();
        }
        continue;
      }
      if (message.action === "transcript") {
        if (!callState.live || callState.ring) continue;
        callTranscriptOpen = !callTranscriptOpen;
        refreshCallSurfaces();
      } else if (["accept", "decline", "mute", "end"].includes(message.action)) {
        sendToWindow("talktome:call-command", message.action);
      }
    }
  });
  const stopped = () => {
    clearTimeout(readyTimer);
    if (notchGlow !== child) return;
    notchGlow = null;
    nativePillBounds = null;
    setNativeAvailable(false);
  };
  child.on("error", (error) => {
    process.stderr.write(`Notch glow: ${error.message}\n`);
    stopped();
  });
  child.on("exit", stopped);
  child.stdin.on("error", (error) => {
    process.stderr.write(`Notch glow input: ${error.message}\n`);
  });
  child.stderr.on("data", (data) => process.stderr.write(data));
  updateNotchGlow();
}

if (!app.requestSingleInstanceLock()) app.quit();

app.on("second-instance", () => {
  openSettings();
});

function trusted(url) {
  try {
    return new URL(url).origin === origin;
  } catch {
    return false;
  }
}

/**
 * The usable area of the display the call is on.
 *
 * The call display is recorded when the call starts and after each drag. When
 * it is unknown, the current call window position finds the display, because a
 * work area change must not move the call to the display of the hidden main
 * window. The primary display is the last fallback.
 */
function callWorkArea() {
  const display =
    (callDisplay && !callDisplay.isDestroyed?.() && callDisplay) ||
    (callWindow && !callWindow.isDestroyed()
      ? screen.getDisplayMatching(callWindow.getBounds())
      : window && !window.isDestroyed()
        ? screen.getDisplayMatching(window.getBounds())
        : screen.getPrimaryDisplay());
  return display.workArea;
}

function transcriptRequest() {
  if (!callApproval) return callTranscriptSize;
  return {
    width: Math.max(callTranscriptSize.width, APPROVAL_PANEL.width),
    height: Math.max(callTranscriptSize.height, APPROVAL_PANEL.height),
  };
}

function applyCallBounds() {
  if (!callWindow || callWindow.isDestroyed()) return;
  const request = transcriptRequest();
  if (nativeNotch) {
    const anchorBounds = callAnchor && callWindow.getBounds();
    const display = anchorBounds ? screen.getDisplayMatching(anchorBounds)
      : nativePillBounds ? screen.getDisplayMatching({
        x: Math.round(nativePillBounds.x), y: Math.round(nativePillBounds.y),
        width: Math.round(nativePillBounds.width), height: Math.round(nativePillBounds.height),
      }) : screen.getAllDisplays().find((item) =>
      Math.abs(item.bounds.x - nativeGeometry.screenX) < 2 &&
      Math.abs(item.bounds.width - nativeGeometry.screenWidth) < 2
    ) || screen.getPrimaryDisplay();
    const area = display.workArea;
    const width = Math.min(area.width, Math.max(200, request.width + 20));
    const height = Math.min(area.height, Math.max(140, request.height + 20));
    const center = nativePillBounds ? nativePillBounds.x + nativePillBounds.width / 2
      : nativeGeometry.screenX + nativeGeometry.screenWidth / 2;
    const defaultX = Math.round(center - width / 2);
    const defaultY = Math.round(nativePillBounds
      ? nativePillBounds.y + nativePillBounds.height + 12
      : display.bounds.y + nativeGeometry.notchDepth + 140);
    const x = Math.max(area.x, Math.min(callAnchor?.x ?? defaultX, area.x + area.width - width));
    const y = Math.max(area.y, Math.min(callAnchor?.top ?? defaultY, area.y + area.height - height));
    callTranscriptApplied = { width: width - 20, height: height - 20 };
    appliedBounds = { x, y, width, height };
    callWindow.setBounds(appliedBounds);
    return;
  }
  const area = callWorkArea();
  const base = anchoredBounds(
    pillBounds(area, { open: callTranscriptOpen, placement: callPlacement }),
    callAnchor,
    area,
    callPlacement,
  );
  const sized = transcriptBounds(base, area, {
    open: callTranscriptOpen,
    transcriptWidth: request.width,
    transcriptHeight: request.height,
    placement: callPlacement,
  });
  callTranscriptApplied = {
    width: sized.transcriptWidth,
    height: sized.transcriptHeight,
  };
  appliedBounds = sized.bounds;
  callWindow.setBounds(appliedBounds);
}

/**
 * Show the call surface.
 *
 * The window is shown inactive so it never pulls focus away from whatever the
 * user was typing in when the call started.
 */
function showCallWindow() {
  if (!callWindow || callWindow.isDestroyed()) return;
  if (nativeNotch && !callTranscriptOpen) return;
  applyCallBounds();
  callWindow.showInactive();
}

function hideCallWindow() {
  if (callWindow && !callWindow.isDestroyed()) callWindow.hide();
}

function restoreCallWindow(token) {
  if (!floatingCall || !callState.live) return;
  if (nativeNotch && callState.ring) return;
  if (nativeNotch) callTranscriptOpen = true;
  createCallWindow(token);
  callWindow.setAlwaysOnTop(true, "floating");
  callWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  showCallWindow();
  sendToCall(callState);
}

function createCallWindow(token) {
  if (callWindow && !callWindow.isDestroyed()) return callWindow;
  callDisplay = window && !window.isDestroyed()
    ? screen.getDisplayMatching(window.getBounds())
    : screen.getPrimaryDisplay();
  callWindow = new BrowserWindow({
    ...pillBounds(callWorkArea(), { open: false, placement: callPlacement }),
    // A pill floating over other applications: no chrome, no background, no
    // resize handles, and no native shadow (which would draw a rectangle around
    // the transparent window rather than following the pill).
    frame: false,
    // The window stays transparent so the pill's rounded corners and drop shadow
    // have somewhere to be. The pill itself is opaque.
    transparent: true,
    resizable: false,
    movable: true,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hasShadow: false,
    show: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "call-preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      autoplayPolicy: "no-user-gesture-required",
      // The call surface animates continuously; throttling it while it is in the
      // background would make the threads stutter.
      backgroundThrottling: false,
    },
  });
  callWindow.setAlwaysOnTop(true, "floating");
  callWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  callWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  callWindow.webContents.on("will-navigate", (event, url) => {
    if (!trusted(url)) event.preventDefault();
  });
  // The token is passed for the first load. The session cookie is shared with
  // the main window, so this window is authenticated from then on.
  callWindow.loadURL(`${origin}/call.html${nativeNotch ? "?surface=transcript" : ""}#token=${encodeURIComponent(token)}`);
  // Registered on every load rather than once: a reload of this window must not
  // leave it stuck waiting for a state message that already went out.
  callWindow.webContents.on("did-finish-load", () => {
    if (!callWindow || callWindow.isDestroyed()) return;
    // A call can end while this window loads. Show it only while the call is
    // still live, so a late load cannot put a pill on screen after it ended.
    if (callState.live && (!nativeNotch || callTranscriptOpen)) callWindow.showInactive();
    sendToCall(callState);
  });
  // A drag is remembered. Electron reports every move, including the ones made
  // above, so a move that matches what was just applied is ignored.
  callWindow.on("moved", () => {
    if (!callWindow || callWindow.isDestroyed()) return;
    const bounds = callWindow.getBounds();
    if (appliedBounds && bounds.x === appliedBounds.x && bounds.y === appliedBounds.y) return;
    // Keep both horizontal edges. The placement decides which edge stays fixed
    // when the transcript opens.
    callAnchor = {
      x: bounds.x,
      top: bounds.y,
      bottom: bounds.y + bounds.height,
    };
    // Follow the window to another display, so a later resize measures the
    // work area that the user can see.
    callDisplay = screen.getDisplayMatching(bounds);
  });
  callWindow.on("closed", () => {
    callWindow = null;
    appliedBounds = null;
  });
  return callWindow;
}

function sendToCall(state) {
  if (callWindow && !callWindow.isDestroyed()) {
    // The surface also needs the placement. It puts the transcript above the
    // pill at the bottom placement, and below the pill at the top placement.
    // The open flag and the applied transcript size keep the panel and the
    // window in step after a resize or a new call.
    callWindow.webContents.send("talktome:call-state", {
      ...state,
      placement: nativeNotch ? "top-center" : callPlacement,
      open: callTranscriptOpen,
      transcript: callTranscriptApplied,
    });
  }
}

function sendToWindow(channel, payload) {
  if (window && !window.isDestroyed()) window.webContents.send(channel, payload);
}

/**
 * Show the window on its Settings page.
 *
 * The Settings menu item and the menu bar item both use this, so the window is
 * always shown and focused before the renderer is told to open settings.
 */
// The --background token in tokens.css, so the window does not flash another
// color before the page paints.
function windowBackground() {
  return nativeTheme.shouldUseDarkColors ? "#0a0a0a" : "#ffffff";
}

function openSettings() {
  settingsOpen = true;
  mainDismissed = false;
  if (onboardingWindow && !onboardingWindow.isDestroyed()) onboardingWindow.hide();
  if (!window || window.isDestroyed()) return;
  if (window.isMinimized()) window.restore();
  window.show();
  window.focus();
  window.webContents.send("talktome:open-settings");
}

function onboardingBounds() {
  const display = screen.getPrimaryDisplay();
  const area = display.workArea;
  const width = Math.min(500, area.width);
  const height = Math.min(610, area.height);
  return {
    width,
    height,
    x: Math.round(area.x + (area.width - width) / 2),
    y: area.y,
  };
}

function createOnboardingWindow(token) {
  if (onboardingWindow && !onboardingWindow.isDestroyed()) return onboardingWindow;
  onboardingWindow = new BrowserWindow({
    ...onboardingBounds(),
    frame: false,
    transparent: true,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    hasShadow: false,
    show: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "onboarding-preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  onboardingWindow.setAlwaysOnTop(true, "floating");
  onboardingWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  onboardingWindow.webContents.on("will-navigate", (event, url) => {
    if (!trusted(url)) event.preventDefault();
  });
  onboardingWindow.loadURL(`${origin}/onboarding.html#token=${encodeURIComponent(token)}`);
  onboardingWindow.on("close", (event) => {
    if (quitting) return;
    event.preventDefault();
    mainDismissed = true;
    onboardingWindow.hide();
  });
  onboardingWindow.on("closed", () => { onboardingWindow = null; });
  return onboardingWindow;
}

function buildTray() {
  if (tray) return;
  const { createTrayIcon } = require("./tray-icon.cjs");
  tray = new Tray(createTrayIcon(nativeImage));
  tray.setToolTip("TalkToMe");
  tray.on("click", () => {
    if (callState.live) restoreCallWindow(callToken);
    else if (onboardingActive && onboardingWindow && !onboardingWindow.isDestroyed()) {
      settingsOpen = false;
      mainDismissed = false;
      if (window && !window.isDestroyed()) window.hide();
      onboardingWindow.show();
      onboardingWindow.focus();
    }
    else openSettings();
  });
  refreshTrayMenu();
}

function refreshTrayMenu() {
  if (!tray) return;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: "Open Settings",
        click: openSettings,
      },
      {
        label: nativeNotch ? "Open transcript" : "Show call",
        enabled: callState.live && !callState.ring,
        click: () => restoreCallWindow(callToken),
      },
      {
        label: "Answer call",
        enabled: Boolean(callState.ring),
        click: () => sendToWindow("talktome:call-command", "accept"),
      },
      {
        label: "Decline call",
        enabled: Boolean(callState.ring),
        click: () => sendToWindow("talktome:call-command", "decline"),
      },
      {
        label: callState.muted ? "Unmute microphone" : "Mute microphone",
        enabled: callState.live && !callState.ring,
        click: () => sendToWindow("talktome:call-command", "mute"),
      },
      {
        label: "End call",
        enabled: callState.live,
        click: () => sendToWindow("talktome:call-command", "end"),
      },
      { type: "separator" },
      { label: "Quit TalkToMe", click: () => app.quit() },
    ]),
  );
}

function dataDirectory() {
  return process.env.TALKTOME_DATA_DIR || app.getPath("userData");
}

/**
 * Offer to move a packaged app into the Applications folder.
 *
 * Returns true when the app moves, because Electron then starts the moved copy
 * and quits this one. A "no" is remembered, so the question comes only once.
 */
async function offerMoveToApplications() {
  const declined = path.join(dataDirectory(), "move-to-applications-declined");
  if (!shouldOfferMove({
    packaged: app.isPackaged,
    platform: process.platform,
    inApplications: process.platform === "darwin" && app.isInApplicationsFolder(),
    declined: existsSync(declined),
  })) return false;
  // The app has no Dock icon, so the dialog would open behind other windows.
  app.focus({ steal: true });
  const { response } = await dialog.showMessageBox({
    type: "question",
    buttons: ["Move to Applications", "Do Not Move"],
    defaultId: 0,
    cancelId: 1,
    message: "Move TalkToMe to the Applications folder?",
    detail: "Your agent finds TalkToMe there, and TalkToMe can open at login. If you do not move it, TalkToMe does not ask again.",
  });
  if (response !== 0) {
    mkdirSync(path.dirname(declined), { recursive: true, mode: 0o700 });
    writeFileSync(declined, "");
    return false;
  }
  try {
    return app.moveToApplicationsFolder({
      conflictHandler: (type) => {
        // Electron then brings the running copy forward and quits this one.
        if (type === "existsAndRunning") return true;
        return dialog.showMessageBoxSync({
          type: "question",
          buttons: ["Replace", "Cancel"],
          defaultId: 0,
          cancelId: 1,
          message: "The Applications folder already has a copy of TalkToMe.",
          detail: "Replace it with this copy? The older copy goes to the Trash.",
        }) === 0;
      },
    });
  } catch (error) {
    dialog.showErrorBox("TalkToMe could not move", error.message);
    return false;
  }
}

function loginItem() {
  return loginItemState({
    packaged: app.isPackaged,
    platform: process.platform,
    settings: app.isPackaged && process.platform === "darwin" ? app.getLoginItemSettings() : null,
  });
}

// The script is built here from what this process started the server with, and
// written to a private folder. The copy agents.py stages in the data folder is
// never read: any process of this user can change that file before the
// administrator prompt.
async function installCommandForAllUsers() {
  const text = commandScript(serverPath(), launchCommand());
  const folder = mkdtempSync(path.join(os.tmpdir(), "talktome-"));
  const source = path.join(folder, "talktome");
  writeFileSync(source, text, { mode: 0o644 });
  try {
    await new Promise((resolve, reject) => {
      execFile("/usr/bin/osascript", adminInstallArgs(source), (error, _stdout, stderr) => {
        if (!error) return resolve();
        // -128 is the Cancel button in the administrator prompt.
        reject(new Error(/-128/.test(stderr) ? "You cancelled the install." : stderr.trim() || error.message));
      });
    });
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
  return true;
}

// A packaged app has no checkout and no virtual environment: the server ships
// inside the bundle as the frozen build, so it is started as a binary rather
// than through an interpreter that would not be there.
function serverPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "talktome-server", "talktome-server")
    : path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
}

function launchCommand() {
  return app.isPackaged
    ? `open -g -a "${path.resolve(process.execPath, "..", "..", "..")}"`
    : `"${process.execPath}" "${root}"`;
}

async function launchBackend() {
  const directory = dataDirectory();
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const python = serverPath();
  const tokenPath = path.join(directory, "token");
  try {
    const response = await fetch(`${origin}/v1/health`, {
      signal: AbortSignal.timeout(800),
    });
    if (response.ok)
      throw new Error(
        `Port ${port} is already in use. Close the other server, then start TalkToMe again.`,
      );
  } catch (error) {
    if (error.message.includes("already in use")) throw error;
  }
  // The frozen server reads its port from the environment; the checkout's command
  // takes it as an argument. Passing both keeps one spawn call for either.
  const args = app.isPackaged ? [] : ["-m", "talktome", "serve", "--port", String(port)];
  backend = spawn(python, args, {
    // With no checkout there is no project folder either, so the server starts
    // somewhere that exists and lets the user pick a folder in the app.
    cwd: app.isPackaged ? app.getPath("home") : root,
    env: {
      ...process.env,
      TALKTOME_PORT: String(port),
      TALKTOME_DATA_DIR: directory,
      PYTHONUNBUFFERED: "1",
      // How to start this app again, baked into the `talktome` command the app
      // installs, so an agent can reach the user without them having opened it
      // first. Only this process knows whether it is a packaged bundle or a
      // checkout, so it is decided here rather than guessed at later. `-g` keeps
      // the launch from stealing focus: the ring is what asks for attention.
      // By path rather than by bundle identifier: an app that has never been
      // opened from its final home may not be registered with LaunchServices yet,
      // and this always knows where it is.
      TALKTOME_LAUNCH: launchCommand(),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let startupError;
  backend.on("error", (error) => {
    startupError = error;
  });
  backend.stdout.on("data", (data) => {
    backendLog = (backendLog + data).slice(-5000);
  });
  backend.stderr.on("data", (data) => {
    backendLog = (backendLog + data).slice(-5000);
    process.stderr.write(data);
  });
  backend.on("exit", () => {
    if (window && !quitting) {
      dialog.showErrorBox(
        "The local server stopped",
        "Restart TalkToMe to connect again.\n\n" + backendLog,
      );
      app.quit();
    }
  });
  for (let attempt = 0; attempt < 120; attempt++) {
    if (startupError) throw startupError;
    if (backend.exitCode !== null)
      throw new Error(backendLog || "The local server stopped.");
    try {
      const response = await fetch(`${origin}/v1/health`, {
        signal: AbortSignal.timeout(500),
      });
      if (response.ok && (await response.json()).service === "talktome") {
        return (
          process.env.TALKTOME_TOKEN || readFileSync(tokenPath, "utf8").trim()
        );
      }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    "The local server did not start within 30 seconds.\n" + backendLog,
  );
}

/**
 * Ask macOS for the microphone.
 *
 * The app has no Dock icon, so the macOS prompt can open behind other windows.
 * The window that asked comes forward first. macOS shows the prompt only once,
 * so focus is taken only while the answer is still open.
 */
async function askMicrophone(owner) {
  if (systemPreferences.getMediaAccessStatus("microphone") === "not-determined") {
    if (owner && !owner.isDestroyed()) {
      owner.show();
      owner.focus();
    }
    app.focus({ steal: true });
  }
  return systemPreferences.askForMediaAccess("microphone");
}

app.whenReady().then(async () => {
  try {
    // Dark is the default theme. Every window and the main window background
    // start dark, and the renderer reports the saved choice once it loads.
    nativeTheme.themeSource = "dark";
    if (await offerMoveToApplications()) return;
    startNotchGlow();
    const token = await launchBackend();
    session.defaultSession.setPermissionCheckHandler(
      (contents, permission, requestingOrigin, details) => {
        return (
          trusted(requestingOrigin) &&
          permission === "media" &&
          details.mediaType !== "video"
        );
      },
    );
    session.defaultSession.setPermissionRequestHandler(
      async (contents, permission, callback, details) => {
        if (
          !trusted(contents.getURL()) ||
          permission !== "media" ||
          details.mediaTypes?.includes("video")
        ) {
          callback(false);
          return;
        }
        const granted =
          app.commandLine.hasSwitch("use-fake-device-for-media-stream") ||
          process.platform !== "darwin" ||
          // The window that owns the call is often hidden, so it stays hidden.
          (await askMicrophone(null));
        callback(granted);
      },
    );
    ipcMain.handle("talktome:desktop-info", (event) => {
      if (!trusted(event.senderFrame.url))
        throw new Error("This window is not permitted.");
      return { platform: process.platform, version: app.getVersion(), nativeNotch };
    });
    function requireMainFrame(event) {
      if (
        !window ||
        event.sender !== window.webContents ||
        event.senderFrame !== window.webContents.mainFrame ||
        !trusted(event.senderFrame.url)
      )
        throw new Error("This window is not permitted.");
    }
    function requireOnboardingFrame(event) {
      if (
        !onboardingWindow ||
        event.sender !== onboardingWindow.webContents ||
        event.senderFrame !== onboardingWindow.webContents.mainFrame ||
        !trusted(event.senderFrame.url)
      )
        throw new Error("This window is not permitted.");
    }
    function requireSetupFrame(event) {
      if (onboardingWindow && event.sender === onboardingWindow.webContents)
        requireOnboardingFrame(event);
      else requireMainFrame(event);
    }
    // The theme setting lives in the renderer. The main process follows it so
    // the window background and every page's prefers-color-scheme agree.
    ipcMain.handle("talktome:theme", (event, mode) => {
      requireMainFrame(event);
      nativeTheme.themeSource = ["light", "dark"].includes(mode) ? mode : "system";
      return true;
    });
    ipcMain.handle("talktome:microphone-status", (event) => {
      requireSetupFrame(event);
      if (app.commandLine.hasSwitch("use-fake-device-for-media-stream"))
        return "granted";
      return ["darwin", "win32"].includes(process.platform)
        ? systemPreferences.getMediaAccessStatus("microphone")
        : "unknown";
    });
    ipcMain.handle("talktome:request-microphone", async (event) => {
      requireSetupFrame(event);
      if (app.commandLine.hasSwitch("use-fake-device-for-media-stream"))
        return "granted";
      if (process.platform !== "darwin") return "unknown";
      return (await askMicrophone(BrowserWindow.fromWebContents(event.sender)))
        ? "granted"
        : "denied";
    });
    ipcMain.handle("talktome:open-system-settings", async (event, pane) => {
      requireSetupFrame(event);
      if (!Object.hasOwn(SETTINGS_PANES, pane)) throw new Error("This settings pane is not permitted.");
      await shell.openExternal(SETTINGS_PANES[pane]);
      return true;
    });
    ipcMain.handle("talktome:login-item", (event) => {
      requireSetupFrame(event);
      return loginItem();
    });
    ipcMain.handle("talktome:set-login-item", (event, enabled) => {
      requireSetupFrame(event);
      if (!loginItem().available)
        throw new Error("Open at login works only in the installed app.");
      app.setLoginItemSettings({ openAtLogin: Boolean(enabled) });
      return loginItem();
    });
    // Settings only: this asks for an administrator password.
    ipcMain.handle("talktome:install-command-all-users", async (event) => {
      requireMainFrame(event);
      if (process.platform !== "darwin") throw new Error("This works only on macOS.");
      return installCommandForAllUsers();
    });
    ipcMain.handle("talktome:glow-color", (event, next) => {
      requireSetupFrame(event);
      const colors = ["amber", "blue", "violet", "green", "pink", "cyan"];
      if (!colors.includes(next)) throw new Error("The glow color is invalid.");
      glowColor = next;
      updateNotchGlow();
      return true;
    });
    // One place decides what is on screen. The hidden renderer owns the call, so
    // it reports the call state and the setup state; the main process shows the
    // call window for a ring or a live call, and the main window only for setup
    // or settings.
    let callHideTimer = null;
    function syncWindows() {
      if (!window || window.isDestroyed()) return;
      const view = computeVisibility({
        callLive: callState.live,
        onboarding: onboardingActive,
        settingsOpen,
        dismissed: mainDismissed,
        quitting,
      });
      if (view.call && floatingCall && nativeNotch) {
        clearTimeout(callHideTimer);
        callHideTimer = null;
        if (callTranscriptOpen && callState.state !== "ringing") {
          createCallWindow(token);
          showCallWindow();
          sendToCall(callState);
        } else if (callWindow && !callWindow.isDestroyed()) {
          sendToCall(callState);
          hideCallWindow();
        }
      } else if (view.call && floatingCall) {
        clearTimeout(callHideTimer);
        callHideTimer = null;
        createCallWindow(token);
        showCallWindow();
        sendToCall(callState);
      } else if (callWindow && !callWindow.isDestroyed()) {
        // Tell the surface the call is over before the window leaves. Without
        // this message the ring tone kept playing in the hidden window, because
        // the renderer only stops a ring when it hears the idle state.
        sendToCall(callState);
        // Wait for the closing animation before the window disappears. A later
        // call cancels the timer. When the timer does run, the window returns to
        // the pill size so the next call starts from a clean bound.
        if (!callHideTimer) {
          callHideTimer = setTimeout(() => {
            callHideTimer = null;
            if (!callState.live) {
              callTranscriptOpen = false;
              callAnchor = null;
              applyCallBounds();
              hideCallWindow();
            }
          }, 360);
        }
      }
      if (onboardingActive && !settingsOpen && !callState.live && !mainDismissed) {
        const existing = onboardingWindow && !onboardingWindow.isDestroyed();
        createOnboardingWindow(token);
        if (existing && !onboardingWindow.isVisible()) onboardingWindow.reload();
        onboardingWindow.show();
      } else if (onboardingWindow && !onboardingWindow.isDestroyed()) {
        onboardingWindow.hide();
      }
      if (view.main && (!onboardingActive || settingsOpen)) {
        if (window.isMinimized()) window.restore();
        window.show();
      } else if (window.isVisible()) {
        window.hide();
      }
      refreshTrayMenu();
    }
    refreshCallSurfaces = syncWindows;
    let lastServerCall = "";
    async function pollServerCall() {
      if (quitting) return;
      try {
        const response = await fetch(`${origin}/v1/state`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: AbortSignal.timeout(1500),
        });
        if (!response.ok) return;
        const snapshot = await response.json();
        const callId = snapshot.room?.call_id || null;
        const ring = snapshot.managed?.status === "ringing"
          ? snapshot.managed.ring || null
          : null;
        const approval = Boolean(callId && snapshot.managed?.approvals?.length);
        const key = JSON.stringify([callId, ring?.id || null, approval]);
        if (key === lastServerCall) return;
        lastServerCall = key;
        const changedCall = callId !== callState.callId;
        callState = {
          ...callState,
          live: Boolean(callId || ring),
          callId,
          startedAt: snapshot.room?.started_at || null,
          ring: ring ? { id: String(ring.id || ""), name: String(ring.name || "") } : null,
          state: ring ? "ringing" : callId ? "active" : "idle",
          name: snapshot.managed?.thread_name || snapshot.room?.agent?.name || "TalkToMe",
          muted: changedCall ? false : callState.muted,
          userActive: changedCall ? false : callState.userActive,
          agentActive: changedCall ? false : callState.agentActive,
          thinking: changedCall ? false : callState.thinking,
        };
        if (ring || changedCall) {
          callTranscriptOpen = false;
          callAnchor = null;
          approvalOpenedPanel = false;
        }
        // The call surface draws the request from its own state poll. This
        // side makes sure the panel is open and large enough to hold it.
        if (approval !== callApproval) {
          callApproval = approval;
          if (approval && !callTranscriptOpen) {
            callTranscriptOpen = true;
            approvalOpenedPanel = true;
          } else if (!approval && approvalOpenedPanel) {
            callTranscriptOpen = false;
            approvalOpenedPanel = false;
          }
          applyCallBounds();
        }
        updateNotchGlow();
        syncWindows();
      } catch {}
    }
    setInterval(() => { void pollServerCall(); }, 500);
    void pollServerCall();
    ipcMain.handle("talktome:call-state", (event, next) => {
      requireMainFrame(event);
      if (!next || typeof next !== "object") throw new Error("The call state is invalid.");
      const wasLive = callState.live;
      const previousCallId = callState.callId;
      // Rebuilt rather than forwarded, so this is the one place the shape of the
      // call state is defined. Every field the surface reads has to be copied
      // here or it silently never arrives.
      callState = {
        live: Boolean(next.live),
        callId: typeof next.callId === "string" ? next.callId : null,
        startedAt: typeof next.startedAt === "string" ? next.startedAt : null,
        muted: Boolean(next.muted),
        state: typeof next.state === "string" ? next.state : "idle",
        name: typeof next.name === "string" ? next.name.slice(0, 80) : "TalkToMe",
        userActive: Boolean(next.userActive),
        agentActive: Boolean(next.agentActive),
        thinking: Boolean(next.thinking),
        partial: typeof next.partial === "string" ? next.partial.slice(0, 6000) : "",
        ring: next.ring && typeof next.ring === "object"
          ? { id: String(next.ring.id || ""), name: String(next.ring.name || "") }
          : null,
      };
      // A call that starts or ends begins with a closed transcript and the pill
      // back at its place. The window is reused between calls, so without this
      // the last call's panel and drag anchor survived into the next ring.
      if (wasLive !== callState.live || previousCallId !== callState.callId) {
        callTranscriptOpen = false;
        callAnchor = null;
      }
      // The ring asks one question and has no transcript.
      if (callState.state === "ringing") callTranscriptOpen = false;
      updateNotchGlow();
      syncWindows();
      return true;
    });
    // The renderer knows whether setup is complete, because setup progress lives
    // in its own storage. It reports the state so the main process can hide the
    // window after setup without stopping the renderer.
    ipcMain.handle("talktome:onboarding", (event, active) => {
      requireMainFrame(event);
      onboardingActive = Boolean(active);
      // A fresh report of setup clears an earlier dismissal, so a new install
      // always shows onboarding.
      if (onboardingActive) mainDismissed = false;
      syncWindows();
      return true;
    });
    ipcMain.handle("talktome:onboarding-complete", (event) => {
      requireOnboardingFrame(event);
      sendToWindow("talktome:onboarding-complete");
      return true;
    });
    ipcMain.handle("talktome:onboarding-settings", (event) => {
      requireOnboardingFrame(event);
      openSettings();
      return true;
    });
    // Closing settings hides the window and keeps the app in the menu bar. The
    // renderer stays alive, so it keeps the microphone, the audio, and the event
    // polling for the next call.
    ipcMain.handle("talktome:hide-window", (event) => {
      requireMainFrame(event);
      settingsOpen = false;
      mainDismissed = !onboardingActive;
      syncWindows();
      return true;
    });
    // The renderer reports the call placement from its saved settings. A
    // placement change moves a live call at once, so the user sees the result.
    // The drag anchor is cleared, because a remembered drag belongs to the old
    // placement.
    ipcMain.handle("talktome:pill-placement", (event, value) => {
      requireMainFrame(event);
      callPlacement = value === "top-center" ? "top-center" : "bottom";
      callAnchor = null;
      if (callWindow && !callWindow.isDestroyed()) {
        applyCallBounds();
        sendToCall(callState);
      }
      return true;
    });
    if (floatingCall) {
      // The hidden window owns the audio, so it is the only place either level can
      // be measured. It pushes them here and they are relayed to the surface.
      ipcMain.on("talktome:call-command", (event, type) => {
        if (!callWindow || event.sender !== callWindow.webContents) return;
        if (!["mute", "interrupt", "end", "accept"].includes(type)) return;
        sendToWindow("talktome:call-command", type);
      });
      ipcMain.on("talktome:call-resize", (event, open) => {
        if (!callWindow || event.sender !== callWindow.webContents) return;
        callTranscriptOpen = Boolean(open);
        // The user decides about the panel from now on.
        approvalOpenedPanel = false;
        syncWindows();
      });
      ipcMain.on("talktome:call-transcript-size", (event, size) => {
        if (!callWindow || event.sender !== callWindow.webContents) return;
        if (!size || typeof size !== "object") return;
        const width = Number(size.width);
        const height = Number(size.height);
        if (!Number.isFinite(width) || !Number.isFinite(height)) return;
        callTranscriptSize = { width, height };
        applyCallBounds();
        sendToCall(callState);
      });
    }
    window = new BrowserWindow({
      width: 980,
      height: 760,
      minWidth: 760,
      minHeight: 580,
      title: "TalkToMe",
      backgroundColor: windowBackground(),
      titleBarStyle: "hiddenInset",
      trafficLightPosition: { x: 22, y: 22 },
      // The renderer reports whether setup is complete. Until then the window
      // stays hidden, so a later launch does not flash the main window before it
      // returns to the menu bar.
      show: false,
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        // The window is hidden for the length of a call while it keeps owning the
        // microphone, the agent session, and playback. Throttling a hidden window
        // would stall all three.
        backgroundThrottling: false,
      },
    });
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event, url) => {
      if (!trusted(url)) event.preventDefault();
    });
    Menu.setApplicationMenu(
      Menu.buildFromTemplate([
        {
          label: "TalkToMe",
          submenu: [
            { role: "about" },
            { type: "separator" },
            {
              label: "Settings…",
              accelerator: "CmdOrCtrl+,",
              click: openSettings,
            },
            { type: "separator" },
            { role: "quit" },
          ],
        },
        {
          label: "Edit",
          submenu: [
            { role: "undo" },
            { role: "redo" },
            { type: "separator" },
            { role: "cut" },
            { role: "copy" },
            { role: "paste" },
            { role: "selectAll" },
          ],
        },
        {
          label: "View",
          submenu: [
            { role: "reload" },
            { role: "toggleDevTools" },
            { role: "resetZoom" },
            { role: "zoomIn" },
            { role: "zoomOut" },
          ],
        },
      ]),
    );
    await window.loadURL(`${origin}/#token=${encodeURIComponent(token)}`);
    // Closing settings hides the window and keeps the app in the menu bar. The
    // renderer keeps running, so the microphone, the audio, and the event polling
    // stay ready for the next call. Only the Quit command stops the app.
    window.on("close", (event) => {
      if (quitting) return;
      event.preventDefault();
      settingsOpen = false;
      mainDismissed = !onboardingActive;
      window.hide();
      syncWindows();
    });
    window.on("closed", () => {
      window = null;
    });
    nativeTheme.on("updated", () => {
      if (window && !window.isDestroyed()) window.setBackgroundColor(windowBackground());
    });
    // TalkToMe keeps running in the menu bar while a call is live and the window
    // is hidden, and it is also how Settings is reached again.
    callToken = token;
    buildTray();
    // The call can stay active when macOS hides its window. Show the call again
    // without changing the agent session or the audio in the main window.
    setInterval(() => {
      if (
        callState.live &&
        floatingCall &&
        (!nativeNotch || callTranscriptOpen) &&
        (!callWindow || callWindow.isDestroyed() || !callWindow.isVisible())
      ) {
        restoreCallWindow(token);
      }
    }, 1000);
    // A display can change size, gain or lose a Dock, or be unplugged while a
    // call is running, so recompute the position from the current work area
    // instead of trusting the values captured when the call started.
    for (const event of [
      "display-metrics-changed",
      "display-added",
      "display-removed",
    ]) {
      screen.on(event, () => {
        if (onboardingWindow && !onboardingWindow.isDestroyed()) {
          onboardingWindow.setBounds(onboardingBounds());
        }
        if (callWindow && !callWindow.isDestroyed() && callWindow.isVisible()) {
          callDisplay = null;
          applyCallBounds();
        }
      });
    }
  } catch (error) {
    dialog.showErrorBox("TalkToMe could not start", error.message);
    app.quit();
  }
});

app.on("window-all-closed", () => {
  // TalkToMe lives in the menu bar. Closing every window must not stop it, and
  // the hidden renderer must stay alive for the next call. Only the Quit command
  // stops the app.
});
app.on("before-quit", (event) => {
  quitting = true;
  if (notchGlow) {
    notchGlow.stdin.end();
    notchGlow = null;
  }
  if (backend && backend.exitCode === null && !shutdownStarted) {
    event.preventDefault();
    shutdownStarted = true;
    if (callWindow && !callWindow.isDestroyed()) callWindow.destroy();
    if (onboardingWindow && !onboardingWindow.isDestroyed()) onboardingWindow.destroy();
    if (window && !window.isDestroyed()) window.destroy();
    const timer = setTimeout(() => {
      if (backend.exitCode === null) backend.kill("SIGKILL");
      app.quit();
    }, 3000);
    backend.once("exit", () => {
      clearTimeout(timer);
      app.quit();
    });
    backend.kill("SIGTERM");
  }
});
