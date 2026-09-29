const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("talktomeDesktop", {
  info: () => ipcRenderer.invoke("talktome:desktop-info"),
  setTheme: (mode) => ipcRenderer.invoke("talktome:theme", mode),
  microphoneStatus: () => ipcRenderer.invoke("talktome:microphone-status"),
  requestMicrophone: () => ipcRenderer.invoke("talktome:request-microphone"),
  openSystemSettings: (pane) => ipcRenderer.invoke("talktome:open-system-settings", pane),
  loginItem: () => ipcRenderer.invoke("talktome:login-item"),
  setLoginItem: (enabled) => ipcRenderer.invoke("talktome:set-login-item", Boolean(enabled)),
  installCommandForAllUsers: () => ipcRenderer.invoke("talktome:install-command-all-users"),
  setGlowColor: (color) => ipcRenderer.invoke("talktome:glow-color", color),
  openCalls: () => ipcRenderer.invoke("talktome:open-calls"),
  onOpenSettings: (callback) =>
    ipcRenderer.on("talktome:open-settings", () => callback()),
  onOnboardingComplete: (callback) =>
    ipcRenderer.on("talktome:onboarding-complete", () => callback()),
  // Setup progress lives in this window's storage, so the main process learns
  // whether setup is complete from here. Closing settings asks the main process
  // to hide the window instead of stopping the app.
  setOnboarding: (active) =>
    ipcRenderer.invoke("talktome:onboarding", Boolean(active)),
  hideWindow: () => ipcRenderer.invoke("talktome:hide-window"),
  // The call surface placement lives in this window's settings. The main
  // process needs it to put the call window at the bottom or at the top center.
  setPillPlacement: (placement) =>
    ipcRenderer.invoke("talktome:pill-placement", placement),
  // This window owns the call, so it reports whether the floating surface should
  // be on screen, and listens for the controls the surface offers.
  setCallState: (state) => ipcRenderer.invoke("talktome:call-state", state),
  onCallCommand: (callback) =>
    ipcRenderer.on("talktome:call-command", (_event, type) => callback(type)),
  onResume: (callback) => ipcRenderer.on("talktome:resume", () => callback()),
});
