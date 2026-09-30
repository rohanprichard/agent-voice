// The hub for calls. The app is the relay for one user: each talktome-server
// link is one agent. The hub rings, times out rings, and ends a server's calls
// when its link drops.

import { EventEmitter } from "node:events";

import { ServerLink, type LinkFrame } from "./link";
import type { Agent, Frame, Target } from "./phone";

const ringMs = 30_000;

type HubCall = { id: string; link: ServerLink; state: "ringing" | "calling" | "live"; timer?: NodeJS.Timeout };

export type ServerState = { id: string; label: string; name: string; state: string; error: string };

export class Hub extends EventEmitter {
  private links = new Map<string, { link: ServerLink; label: string; targets: Target[] }>();
  private calls = new Map<string, HubCall>();
  private seq = 0;

  get connected(): boolean {
    return [...this.links.values()].some(({ link }) => link.state === "connected");
  }

  servers(): ServerState[] {
    return [...this.links.values()].map(({ link, label }) => ({ id: link.id, label, name: link.name, state: link.state, error: link.error }));
  }

  add(link: ServerLink, label: string): void {
    this.remove(link.id);
    this.links.set(link.id, { link, label, targets: [] });
    link.on("frame", (frame: LinkFrame) => this.fromServer(link, frame));
    link.on("state", () => {
      this.presence();
      this.emit(this.connected ? "connected" : "disconnected");
    });
    link.on("dropped", () => this.dropped(link));
    link.start();
  }

  remove(id: string): void {
    const entry = this.links.get(id);
    if (!entry) return;
    this.links.delete(id);
    this.dropped(entry.link);
    entry.link.removeAllListeners();
    entry.link.stop();
    this.presence();
  }

  retry(): void {
    for (const { link } of this.links.values()) link.retry();
  }

  stop(): void {
    for (const id of [...this.links.keys()]) this.remove(id);
  }

  // request takes what the phone module sends.
  async request(type: string, fields: Record<string, unknown> = {}): Promise<unknown> {
    const callId = fields.call_id as string;
    if (type === "call.start") {
      const to = fields.to as { agent_id: string; target_id: string };
      const entry = this.links.get(to.agent_id);
      if (!entry || entry.link.state !== "connected") throw new Error("That machine is not connected.");
      const call: HubCall = { id: callId, link: entry.link, state: "calling" };
      call.timer = setTimeout(() => this.end(call, "The agent did not take the call.", "relay"), ringMs);
      this.calls.set(callId, call);
      entry.link.send({ type: "call.incoming", call_id: callId, target_id: to.target_id, mode: fields.mode });
      return {};
    }
    const call = this.calls.get(callId);
    if (!call) throw new Error("The call is over.");
    switch (type) {
      case "call.answer":
        if (call.state !== "ringing") throw new Error("The call is over.");
        clearTimeout(call.timer);
        call.state = "live";
        call.link.send({ type: "call.answered", call_id: callId });
        break;
      case "call.decline":
        this.forget(call);
        call.link.send({ type: "call.missed", call_id: callId, reason: "declined" });
        break;
      case "call.end":
        this.forget(call);
        call.link.send({ type: "call.ended", call_id: callId, reason: fields.reason ?? "hung up", by: "device" });
        break;
      case "turn.user":
      case "turn.cancel":
        call.link.send({ type, ...fields });
        break;
    }
    return {};
  }

  private fromServer(link: ServerLink, frame: LinkFrame): void {
    const entry = this.links.get(link.id);
    if (!entry || entry.link !== link) return;
    const callId = frame.call_id as string;
    const call = callId ? this.calls.get(callId) : undefined;
    switch (frame.type) {
      case "hello":
      case "targets":
        if (frame.type === "targets") entry.targets = (frame.targets as Target[]) ?? [];
        this.presence();
        return;
      case "call.start": {
        // One call at a time: a second ring while the user is busy is missed.
        if (this.calls.size > 0) {
          link.send({ type: "call.missed", call_id: callId, reason: "busy" });
          return;
        }
        const ringing: HubCall = { id: callId, link, state: "ringing" };
        ringing.timer = setTimeout(() => {
          this.forget(ringing);
          link.send({ type: "call.missed", call_id: callId, reason: "no_answer" });
          this.deliver({ type: "call.ended", call_id: callId, reason: "no_answer", by: "relay" });
        }, ringMs);
        this.calls.set(callId, ringing);
        this.deliver({ ...frame, type: "call.ring", from: { agent_id: link.id, name: this.label(link) } });
        return;
      }
      case "call.accept":
        if (!call) return;
        clearTimeout(call.timer);
        call.state = "live";
        this.deliver({ type: "call.accepted", call_id: callId, agent_id: link.id });
        return;
      case "call.reject":
        if (call) this.end(call, (frame.reason as string) || "The agent did not take the call.", "agent", false);
        return;
      case "call.end":
        if (call) this.end(call, (frame.reason as string) || "", "agent", false);
        return;
      case "turn.agent":
        if (call?.state === "live") this.deliver(frame);
        return;
      case "notify":
        this.deliver({ ...frame, from: { agent_id: link.id, name: this.label(link) } });
        return;
    }
  }

  private label(link: ServerLink): string {
    return this.links.get(link.id)?.label || link.name || link.id;
  }

  private presence(): void {
    const agents: Agent[] = [...this.links.values()].map(({ link, label, targets }) => ({
      agent_id: link.id,
      name: label || link.name || link.id,
      online: link.state === "connected",
      targets: link.state === "connected" ? targets : [],
    }));
    this.deliver({ type: "presence", agents });
  }

  private dropped(link: ServerLink): void {
    for (const call of [...this.calls.values()]) {
      if (call.link === link) this.end(call, "The connection to the server dropped.", "relay", false);
    }
  }

  // end stops a call on the phone's side, and on the server's side when asked.
  private end(call: HubCall, reason: string, by: string, tellServer = true): void {
    this.forget(call);
    if (tellServer) call.link.send({ type: "call.ended", call_id: call.id, reason, by });
    this.deliver({ type: "call.ended", call_id: call.id, reason, by });
  }

  private forget(call: HubCall): void {
    clearTimeout(call.timer);
    this.calls.delete(call.id);
  }

  private deliver(frame: LinkFrame): void {
    this.seq += 1;
    this.emit("frame", { v: 1, id: `hub_${this.seq}`, seq: this.seq, ...frame } as Frame);
  }
}
