// The bridge between the windows and the main process. The windows get the
// call state and a small set of actions, and nothing else.

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("talktome", {
  state: () => ipcRenderer.invoke("state"),
  onState: (listener: (state: unknown) => void) => {
    ipcRenderer.on("state", (_event, state) => listener(state));
  },
  answer: (callId: string) => ipcRenderer.invoke("answer", callId),
  decline: (callId: string) => ipcRenderer.invoke("decline", callId),
  say: (callId: string, text: string) => ipcRenderer.invoke("say", callId, text),
  speechToken: (callId: string, kind: string) =>
    ipcRenderer.invoke("speech-token", callId, kind).catch((error: Error) => {
      // Electron wraps the main process's error; the window shows only its words.
      throw new Error(error.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ""));
    }),
  hangUp: (callId: string) => ipcRenderer.invoke("hang-up", callId),
  callAgent: (agentId: string, targetId: string, mode: string) => ipcRenderer.invoke("call-agent", agentId, targetId, mode),
  dismissNotice: (noticeId: string) => ipcRenderer.invoke("dismiss-notice", noticeId),
  openAgents: () => ipcRenderer.invoke("open-agents"),
  sshHosts: () => ipcRenderer.invoke("ssh-hosts"),
  inspect: (place: string) => ipcRenderer.invoke("inspect", place),
  installUv: (place: string) => ipcRenderer.invoke("install-uv", place),
  installServer: (place: string) => ipcRenderer.invoke("install-server", place),
  installPlugin: (place: string, host: string) => ipcRenderer.invoke("install-plugin", place, host),
  addServer: (host: string) => ipcRenderer.invoke("add-server", host),
  removeServer: (host: string) => ipcRenderer.invoke("remove-server", host),
  reconnect: () => ipcRenderer.invoke("reconnect"),
  setSpeechKey: (key: string) => ipcRenderer.invoke("set-speech-key", key),
});
