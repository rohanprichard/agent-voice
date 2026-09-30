// The talktome app: a menu bar item, a call pill, and an agents window. The
// main process holds the connections and the call state. The windows show a
// snapshot and send actions over IPC.
//
// The app is the hub: it runs talktome-server on this computer and on each
// server over SSH. Speech uses the user's own ElevenLabs key.

import { app, BrowserWindow, ipcMain, Menu, nativeImage, Notification, powerMonitor, safeStorage, screen, Tray } from "electron";
import path from "node:path";

import { Hub } from "./phone/hub";
import { Phone, type Snapshot } from "./phone/phone";
import * as servers from "./phone/servers";

const { createTrayIcon } = require("../tray-icon.cjs") as { createTrayIcon: (images: typeof nativeImage) => Electron.NativeImage };

const ui = path.join(__dirname, "..", "ui");

app.setName("talktome");
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
if (process.env.TALKTOME_DATA_DIR) app.setPath("userData", process.env.TALKTOME_DATA_DIR);

let hub: Hub | null = null;
let phone: Phone | null = null;
let tray: Tray | null = null;
let pill: BrowserWindow | null = null;
let agents: BrowserWindow | null = null;
let settings: servers.Settings = { servers: [] };

function settingsFile(): string {
  return path.join(app.getPath("userData"), "settings.json");
}

// The speech key is kept with safeStorage, which uses the macOS keychain.
function elevenLabsKey(): string {
  if (!settings.elevenlabs) return "";
  try {
    return settings.sealed ? safeStorage.decryptString(Buffer.from(settings.elevenlabs, "base64")) : settings.elevenlabs;
  } catch {
    return "";
  }
}

type AppState = Snapshot & {
  servers: ReturnType<Hub["servers"]>;
  localInstalled: boolean;
  speechKey: boolean;
};

function snapshot(): AppState {
  const base = phone?.snapshot() ?? { connected: false, agents: [], calls: [], notices: [] };
  return { ...base, servers: hub?.servers() ?? [], localInstalled: servers.localServerBin() !== null, speechKey: elevenLabsKey() !== "" };
}

function broadcast(): void {
  const state = snapshot();
  for (const window of [pill, agents]) {
    if (window && !window.isDestroyed()) window.webContents.send("state", state);
  }
  updatePill(state.calls.length > 0);
  updateTray();
}

// startHub connects to this computer, when talktome-server is installed here,
// and to each saved server.
function startHub(): void {
  hub = new Hub();
  hub.on("connected", broadcast);
  hub.on("disconnected", broadcast);
  phone = new Phone(hub);
  phone.on("state", broadcast);
  phone.on("ring", (call) => {
    showPill();
    new Notification({ title: `${call.agent.name} is calling`, body: call.reason ?? "", silent: false }).show();
  });
  phone.on("notice", (notice) => {
    new Notification({ title: `${notice.from}: ${notice.reason}`, body: notice.message }).show();
  });
  if (servers.localServerBin()) hub.add(servers.linkFor(servers.LOCAL), "This Mac");
  for (const host of settings.servers) hub.add(servers.linkFor(host), host);
  broadcast();
}

function createPill(): BrowserWindow {
  const window = new BrowserWindow({
    width: 380,
    height: 340,
    frame: false,
    transparent: true,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    hasShadow: false,
    show: false,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  window.setAlwaysOnTop(true, "floating");
  window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  window.loadFile(path.join(ui, "pill.html"));
  window.webContents.on("did-finish-load", () => window.webContents.send("state", snapshot()));
  return window;
}

function showPill(): void {
  if (!pill || pill.isDestroyed()) pill = createPill();
  const area = screen.getPrimaryDisplay().workArea;
  const [width] = pill.getSize();
  pill.setPosition(Math.round(area.x + (area.width - width) / 2), area.y + 12);
  if (pill.webContents.isLoading()) pill.once("ready-to-show", () => pill?.showInactive());
  else pill.showInactive();
}

function updatePill(open: boolean): void {
  if (open) showPill();
  else if (pill && !pill.isDestroyed() && pill.isVisible()) pill.hide();
}

function openAgents(): void {
  if (agents && !agents.isDestroyed()) {
    agents.show();
    agents.focus();
    return;
  }
  agents = new BrowserWindow({
    width: 720,
    height: 680,
    minWidth: 560,
    minHeight: 460,
    title: "talktome",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 18, y: 18 },
    show: false,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  agents.loadFile(path.join(ui, "agents.html"));
  agents.webContents.on("did-finish-load", () => agents?.webContents.send("state", snapshot()));
  agents.once("ready-to-show", () => agents?.show());
}

function updateTray(): void {
  if (!tray) return;
  const state = snapshot();
  const up = state.servers.filter((s) => s.state === "connected").length;
  const status = state.servers.length === 0 ? "No machines set up" : `${up} of ${state.servers.length} machines connected`;
  const machines = state.agents.map((agent) => ({
    label: `${agent.online ? "●" : "○"} ${agent.name}`,
    enabled: agent.online && agent.targets.length > 0,
    submenu: agent.targets.length
      ? agent.targets.slice(0, 10).map((target) => ({
          label: target.project,
          click: () => void phone?.callAgent(agent.agent_id, target.target_id, target.joinable ? "join" : "continue"),
        }))
      : undefined,
  }));
  tray.setToolTip(`talktome: ${status}`);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: status, enabled: false },
      ...(machines.length ? [{ type: "separator" as const }, ...machines] : []),
      { type: "separator" },
      { label: "Machines and agents…", click: openAgents },
      { type: "separator" },
      { label: "Quit talktome", role: "quit" as const },
    ]),
  );
}

type Handler = (...args: never[]) => unknown;

function handle(channel: string, fn: Handler): void {
  ipcMain.handle(channel, (_event, ...args) => (fn as (...a: unknown[]) => unknown)(...args));
}

handle("state", () => snapshot());
handle("answer", (callId: string) => phone?.answer(callId));
handle("decline", (callId: string) => phone?.decline(callId));
handle("say", (callId: string, text: string) => phone?.say(callId, text));
handle("speech-token", (callId: string, kind: "realtime_scribe" | "tts_websocket") => {
  if (!phone?.snapshot().calls.some((call) => call.id === callId && call.state === "live")) {
    throw new Error("The call is not live.");
  }
  if (kind !== "realtime_scribe" && kind !== "tts_websocket") throw new Error("The speech token type is not valid.");
  const key = elevenLabsKey();
  if (!key) throw new Error("Add your ElevenLabs key in talktome to talk. You can type for now.");
  return servers.elevenLabsToken(key, kind);
});
handle("hang-up", (callId: string) => phone?.hangUp(callId));
handle("call-agent", (agentId: string, targetId: string, mode: "join" | "continue" | "new") => phone?.callAgent(agentId, targetId, mode));
handle("dismiss-notice", (noticeId: string) => phone?.dismissNotice(noticeId));
handle("open-agents", () => openAgents());

// Setting up machines.
handle("ssh-hosts", () => servers.sshHosts());
handle("inspect", (place: string) => servers.inspect(place));
handle("install-uv", (place: string) => servers.installUv(place));
handle("install-server", async (place: string) => {
  const failed = await servers.installServer(place);
  if (failed || !hub) return failed;
  // Restart the machine's link, so the new version takes over.
  const id = place === servers.LOCAL ? servers.LOCAL : `ssh:${place}`;
  const known = hub.servers().find((s) => s.id === id);
  if (known) hub.add(servers.linkFor(place), known.label);
  else if (place === servers.LOCAL) hub.add(servers.linkFor(servers.LOCAL), "This Mac");
  return "";
});
handle("install-plugin", (place: string, host: string) => servers.installPlugin(place, host));
handle("add-server", (host: string) => {
  host = host.trim();
  if (!host || host === servers.LOCAL) return;
  if (!settings.servers.includes(host)) settings.servers.push(host);
  servers.saveSettings(settingsFile(), settings);
  hub?.add(servers.linkFor(host), host);
  broadcast();
});
handle("remove-server", (host: string) => {
  settings.servers = settings.servers.filter((h) => h !== host);
  servers.saveSettings(settingsFile(), settings);
  hub?.remove(`ssh:${host}`);
  broadcast();
});
handle("reconnect", () => hub?.retry());
handle("set-speech-key", (key: string) => {
  key = key.trim();
  if (key) {
    const sealed = safeStorage.isEncryptionAvailable();
    settings = { ...settings, elevenlabs: sealed ? safeStorage.encryptString(key).toString("base64") : key, sealed };
  } else {
    settings = { servers: settings.servers };
  }
  servers.saveSettings(settingsFile(), settings);
  broadcast();
});

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", openAgents);
  app.on("window-all-closed", () => undefined); // the menu bar item keeps running
  app.whenReady().then(() => {
    app.dock?.hide();
    tray = new Tray(createTrayIcon(nativeImage));
    settings = servers.loadSettings(settingsFile());
    startHub();
    powerMonitor.on("resume", () => hub?.retry());
    if (!servers.localServerBin() && settings.servers.length === 0) openAgents();
    updateTray();
  });
  app.on("before-quit", () => hub?.stop());
}
