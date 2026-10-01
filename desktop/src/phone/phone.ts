// The call state of this computer, in the main process. It turns frames from
// the hub into a snapshot for the windows, and window actions into requests.
//
// Calls go both ways. An agent rings the user with call.ring, and the user
// calls an agent with call.start. After that, both kinds use the same turns:
// the user says something with turn.user, and the agent answers with
// turn.agent items, the last one final.

import { randomBytes } from "node:crypto";
import { EventEmitter } from "node:events";

// A message between the app and an agent. The names follow the talktome relay protocol.
export type Frame = { v: number; type: string; id: string; seq?: number; re?: string; [field: string]: unknown };

export function newID(prefix = ""): string {
  const id = randomBytes(12).toString("hex");
  return prefix ? `${prefix}_${id}` : id;
}

// Transport is what carries calls: the hub of talktome-server links.
export type Transport = EventEmitter & {
  readonly connected: boolean;
  request(type: string, fields?: Record<string, unknown>): Promise<unknown>;
};

export type Target = { target_id: string; host: string; project: string; last_active?: string; joinable?: boolean };
export type Agent = { agent_id: string; name: string; online: boolean; targets: Target[] };

export type Line = { who: "agent" | "user" | "note"; text: string; final?: boolean };

export type Call = {
  id: string;
  direction: "incoming" | "outgoing";
  state: "ringing" | "calling" | "live" | "ended";
  agent: { id: string; name: string };
  reason?: string;
  urgency?: string;
  question?: string;
  choices?: string[];
  target?: Target;
  mode?: string;
  waiting: boolean; // the user spoke and the final reply has not come yet
  lines: Line[];
  ended?: string;
};

export type Notice = { id: string; from: string; reason: string; message: string; urgency?: string; at: number };

export type Snapshot = { connected: boolean; agents: Agent[]; calls: Call[]; notices: Notice[] };

// Ended calls stay in the snapshot for a short time, so the window can show
// how the call ended.
const endedLinger = 4000;

export class Phone extends EventEmitter {
  private agents: Agent[] = [];
  private calls = new Map<string, Call>();
  private notices: Notice[] = [];
  private turn = new Map<string, string>(); // the open turn of each call

  constructor(private readonly transport: Transport) {
    super();
    transport.on("frame", (frame: Frame) => this.receive(frame));
    transport.on("connected", () => this.changed());
    transport.on("disconnected", () => this.changed());
  }

  snapshot(): Snapshot {
    return {
      connected: this.transport.connected,
      agents: this.agents,
      calls: [...this.calls.values()],
      notices: this.notices,
    };
  }

  async answer(callId: string): Promise<void> {
    const call = this.calls.get(callId);
    if (!call || call.state !== "ringing") return;
    try {
      await this.transport.request("call.answer", { call_id: callId });
    } catch (error) {
      this.end(call, (error as Error).message);
      return;
    }
    call.state = "live";
    if (call.question) call.lines.push({ who: "agent", text: call.question, final: true });
    this.changed();
  }

  async decline(callId: string): Promise<void> {
    const call = this.calls.get(callId);
    if (!call || call.state !== "ringing") return;
    this.end(call, "Declined");
    await this.transport.request("call.decline", { call_id: callId }).catch(() => undefined);
  }

  // say sends what the user said. A turn that has no final reply yet is
  // replaced by this one, so the agent answers the newest words.
  async say(callId: string, text: string): Promise<void> {
    const call = this.calls.get(callId);
    text = text.trim();
    if (!call || call.state !== "live" || !text) return;
    const turnId = newID("turn");
    this.turn.set(callId, turnId);
    call.lines.push({ who: "user", text });
    call.waiting = true;
    this.changed();
    await this.transport.request("turn.user", { call_id: callId, turn_id: turnId, text });
  }

  async hangUp(callId: string): Promise<void> {
    const call = this.calls.get(callId);
    if (!call || call.state === "ended") return;
    this.end(call, "You hung up");
    await this.transport.request("call.end", { call_id: callId, reason: "hung up" }).catch(() => undefined);
  }

  async callAgent(agentId: string, targetId: string, mode: "join" | "continue" | "new"): Promise<string> {
    const agent = this.agents.find((a) => a.agent_id === agentId);
    const target = agent?.targets.find((t) => t.target_id === targetId);
    const call: Call = {
      id: newID("call"),
      direction: "outgoing",
      state: "calling",
      agent: { id: agentId, name: agent?.name ?? "Agent" },
      target,
      mode,
      waiting: false,
      lines: [],
    };
    this.calls.set(call.id, call);
    this.changed();
    try {
      await this.transport.request("call.start", { call_id: call.id, mode, to: { agent_id: agentId, target_id: targetId } });
    } catch (error) {
      this.end(call, (error as Error).message);
    }
    return call.id;
  }

  dismissNotice(noticeId: string): void {
    this.notices = this.notices.filter((n) => n.id !== noticeId);
    this.changed();
  }

  private receive(frame: Frame): void {
    const callId = frame.call_id as string | undefined;
    const call = callId ? this.calls.get(callId) : undefined;
    switch (frame.type) {
      case "presence":
        this.agents = (frame.agents as Agent[]) ?? [];
        break;
      case "call.ring": {
        const from = frame.from as { agent_id: string; name: string };
        const body = (frame.body as { question?: string; choices?: string[]; greeting?: string }) ?? {};
        const ringing: Call = {
          id: callId!,
          direction: "incoming",
          state: "ringing",
          agent: { id: from.agent_id, name: from.name },
          reason: frame.reason as string,
          urgency: frame.urgency as string,
          question: body.question,
          choices: body.choices,
          waiting: false,
          lines: body.greeting ? [{ who: "agent", text: body.greeting }] : [],
        };
        this.calls.set(ringing.id, ringing);
        this.emit("ring", ringing);
        break;
      }
      case "call.accepted":
        if (!call) return;
        call.state = "live";
        break;
      case "call.taken":
        if (!call) return;
        this.end(call, "Answered on another device");
        return;
      case "call.ended":
        if (!call || call.state === "ended") return;
        this.end(call, endedReason(frame, call));
        return;
      case "turn.agent": {
        if (!call) return;
        const text = frame.text as string;
        const final = frame.final === true;
        const turnId = (frame.turn_id as string) || "";
        // A reply to a turn the user has already replaced is not shown.
        if (turnId && turnId !== this.turn.get(call.id)) return;
        call.lines.push({ who: "agent", text, final });
        if (final) call.waiting = false;
        this.emit("speak", { callId: call.id, text, final });
        break;
      }
      case "notify": {
        const from = frame.from as { name?: string } | undefined;
        const body = (frame.body as { message?: string }) ?? {};
        this.notices = [
          { id: frame.notice_id as string, from: from?.name ?? "Agent", reason: frame.reason as string, message: body.message ?? "", urgency: frame.urgency as string, at: Date.now() },
          ...this.notices,
        ].slice(0, 20);
        this.emit("notice", this.notices[0]);
        break;
      }
      default:
        return;
    }
    this.changed();
  }

  private end(call: Call, reason: string): void {
    call.state = "ended";
    call.ended = reason;
    call.waiting = false;
    this.turn.delete(call.id);
    this.changed();
    setTimeout(() => {
      if (this.calls.get(call.id) === call) {
        this.calls.delete(call.id);
        this.changed();
      }
    }, endedLinger).unref?.();
  }

  private changed(): void {
    this.emit("state", this.snapshot());
  }
}

function endedReason(frame: Frame, call: Call): string {
  const reason = (frame.reason as string) || "";
  if (call.state === "ringing") return "Missed";
  if (call.state === "calling") return reason || "The agent did not take the call";
  if (frame.by === "agent") return reason || "The agent hung up";
  if (frame.by === "relay") return reason || "The call dropped";
  return reason || "Call ended";
}
