const { contextBridge, ipcRenderer } = require("electron");

// The call window gets its own minimal surface. It never needs the clipboard or
// the microphone permission prompts, because the hidden main window owns the
// call; this window only draws it and sends commands back.
contextBridge.exposeInMainWorld("talktomeCall", {
  onState: (callback) => ipcRenderer.on("talktome:call-state", (_event, state) => callback(state)),
  command: (type) => ipcRenderer.send("talktome:call-command", type),
  setTranscriptOpen: (open) => ipcRenderer.send("talktome:call-resize", Boolean(open)),
  setTranscriptSize: (size) =>
    ipcRenderer.send("talktome:call-transcript-size", {
      width: Number(size?.width),
      height: Number(size?.height),
    }),
});
