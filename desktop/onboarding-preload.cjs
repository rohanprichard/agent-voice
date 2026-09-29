const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("talktomeSetup", {
  info: () => ipcRenderer.invoke("talktome:desktop-info"),
  microphoneStatus: () => ipcRenderer.invoke("talktome:microphone-status"),
  requestMicrophone: () => ipcRenderer.invoke("talktome:request-microphone"),
  setGlowColor: (color) => ipcRenderer.invoke("talktome:glow-color", color),
  openSettings: () => ipcRenderer.invoke("talktome:onboarding-settings"),
  complete: () => ipcRenderer.invoke("talktome:onboarding-complete"),
});
