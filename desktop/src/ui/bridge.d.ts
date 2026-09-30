// What the preload script gives the windows, as window.talktome.

type ServerState = import("../phone/hub").ServerState;
type Inspection = import("../phone/servers").Inspection;
type Snapshot = import("../phone/phone").Snapshot & {
  servers: ServerState[];
  localInstalled: boolean;
  speechKey: boolean;
};
type Call = import("../phone/phone").Call;
type Agent = import("../phone/phone").Agent;
type Target = import("../phone/phone").Target;

interface Window {
  talktome: {
    state(): Promise<Snapshot>;
    onState(listener: (state: Snapshot) => void): void;
    answer(callId: string): Promise<void>;
    decline(callId: string): Promise<void>;
    say(callId: string, text: string): Promise<void>;
    speechToken(callId: string, kind: "realtime_scribe" | "tts_websocket"): Promise<string>;
    hangUp(callId: string): Promise<void>;
    callAgent(agentId: string, targetId: string, mode: "join" | "continue" | "new"): Promise<string>;
    dismissNotice(noticeId: string): Promise<void>;
    openAgents(): Promise<void>;
    pointer(inside: boolean): Promise<void>;
    sshHosts(): Promise<string[]>;
    inspect(place: string): Promise<Inspection>;
    installUv(place: string): Promise<string>;
    installServer(place: string): Promise<string>;
    installPlugin(place: string, host: string): Promise<string>;
    addServer(host: string): Promise<void>;
    removeServer(host: string): Promise<void>;
    reconnect(): Promise<void>;
    setSpeechKey(key: string): Promise<void>;
  };
}
