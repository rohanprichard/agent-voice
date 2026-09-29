const { contextBridge, ipcRenderer } = require("electron");

// The main process starts a call back, because the hidden main window has to
// start the microphone once the call is live.
contextBridge.exposeInMainWorld("talktomeCalls", {
  callBack: (id) => ipcRenderer.invoke("talktome:calls-callback", String(id)),
  onError: (callback) =>
    ipcRenderer.on("talktome:calls-error", (_event, error) => callback(error)),
});
