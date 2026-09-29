"use strict";

const path = require("node:path");

const RECENT = 5;
const POLL_MS = 3000;

// One entry per session, newest first, so a session that called three times
// takes one place in the menu.
function recentCallers(calls, limit = RECENT) {
  const seen = new Set();
  const result = [];
  for (const call of calls) {
    const key = `${call.agent}:${call.session_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(call);
    if (result.length === limit) break;
  }
  return result;
}

// Missed calls this process has not told the user about yet. A call that is
// still ringing has no outcome, so it is not yet seen.
function newMissed(calls, seen) {
  return calls.filter((call) => call.outcome === "missed" && !seen.has(call.id));
}

function trayBadge(count) {
  return count > 0 ? ` ${count}` : "";
}

function errorOf(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return { message: detail, action: null };
  if (detail && typeof detail.message === "string")
    return { message: detail.message, action: detail.action || null };
  return { message: `The call back failed (${status}).`, action: null };
}

function createCalls({ electron, origin, trusted, onCallBack, refreshTray }) {
  const { app, BrowserWindow, Notification, ipcMain, nativeTheme } = electron;
  let token = null;
  let tray = null;
  let window = null;
  let calls = [];
  let seen = null;
  let missed = 0;
  let listKey = "";
  // Kept so a notification is not collected before its click arrives.
  const notices = new Set();

  function request(method, pathname) {
    return fetch(`${origin}/v1${pathname}`, {
      method,
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(20000),
    });
  }

  function setMissed(count) {
    missed = count;
    if (tray && !tray.isDestroyed()) tray.setTitle(trayBadge(missed));
  }

  function open() {
    setMissed(0);
    if (!token) return;
    if (window && !window.isDestroyed()) {
      window.show();
      window.focus();
      return;
    }
    window = new BrowserWindow({
      width: 560,
      height: 640,
      minWidth: 420,
      minHeight: 360,
      title: "Calls",
      backgroundColor: nativeTheme.shouldUseDarkColors ? "#0a0a0a" : "#ffffff",
      show: false,
      webPreferences: {
        preload: path.join(__dirname, "calls-preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event, url) => {
      if (!trusted(url)) event.preventDefault();
    });
    window.loadURL(`${origin}/calls.html#token=${encodeURIComponent(token)}`);
    window.once("ready-to-show", () => {
      // The app has no Dock icon, so the window would open behind others.
      app.focus({ steal: true });
      window.show();
    });
    window.on("closed", () => { window = null; });
  }

  async function callBack(id) {
    try {
      const response = await request("POST", `/calls/${encodeURIComponent(id)}/callback`);
      if (response.ok) {
        onCallBack();
        void poll();
        return { ok: true };
      }
      return { ok: false, ...errorOf(await response.json().catch(() => ({})), response.status) };
    } catch (error) {
      return { ok: false, message: error.message, action: null };
    }
  }

  async function callBackFromMenu(id) {
    const result = await callBack(id);
    if (result.ok) return;
    open();
    const send = () => window?.webContents.send("talktome:calls-error", { id, ...result });
    if (window.webContents.isLoading()) window.webContents.once("did-finish-load", send);
    else send();
  }

  function notify(call) {
    if (!Notification.isSupported()) return;
    const notice = new Notification({
      title: `Missed call from ${call.name}`,
      body: call.cwd ? path.basename(call.cwd) : "",
    });
    notices.add(notice);
    notice.on("click", open);
    notice.on("close", () => notices.delete(notice));
    notice.show();
  }

  async function poll() {
    if (!token) return;
    try {
      const response = await request("GET", "/calls");
      if (!response.ok) return;
      calls = (await response.json()).calls || [];
    } catch {
      return;
    }
    const finished = calls.filter((call) => call.outcome);
    if (seen === null) {
      // Calls from before this launch were already there to see.
      seen = new Set(finished.map((call) => call.id));
    } else {
      const fresh = newMissed(calls, seen);
      for (const call of finished) seen.add(call.id);
      if (fresh.length) {
        if (!window || window.isDestroyed() || !window.isFocused()) setMissed(missed + fresh.length);
        for (const call of fresh) notify(call);
      }
    }
    const key = JSON.stringify(recentCallers(calls).map((call) => [call.id, call.name, call.callback_reason]));
    if (key !== listKey) {
      listKey = key;
      refreshTray();
    }
  }

  function menuItems() {
    const recent = recentCallers(calls);
    return [
      { label: "Calls…", click: open },
      {
        label: "Recent",
        submenu: recent.length
          ? recent.map((call) => ({
              label: call.name,
              sublabel: call.callback_reason || undefined,
              enabled: !call.callback_reason,
              click: () => void callBackFromMenu(call.id),
            }))
          : [{ label: "No calls yet", enabled: false }],
      },
    ];
  }

  function start(nextToken, nextTray) {
    token = nextToken;
    tray = nextTray;
    const fromCalls = (event) => {
      if (!window || event.sender !== window.webContents || !trusted(event.senderFrame.url))
        throw new Error("This window is not permitted.");
    };
    ipcMain.handle("talktome:calls-callback", (event, id) => {
      fromCalls(event);
      if (typeof id !== "string") throw new Error("The call is invalid.");
      return callBack(id);
    });
    ipcMain.handle("talktome:open-calls", (event) => {
      if (!trusted(event.senderFrame.url)) throw new Error("This window is not permitted.");
      open();
      return true;
    });
    setInterval(() => void poll(), POLL_MS);
    void poll();
  }

  return { open, start, menuItems };
}

module.exports = { createCalls, newMissed, recentCallers, trayBadge };
