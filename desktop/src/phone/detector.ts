import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";

export type Detection = { probabilities?: number[]; probability?: number };

// One process holds the models for a call. No audio reaches an agent server.
export class SpeechDetector {
  private child: ChildProcessWithoutNullStreams;
  private serial = 0;
  private pending = new Map<number, { resolve: (value: Detection) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }>();
  private closed = false;
  readonly ready: Promise<void>;

  constructor(script: string, cache: string) {
    const uv = [path.join(os.homedir(), ".local/bin/uv"), "/opt/homebrew/bin/uv", "/usr/local/bin/uv"].find(fs.existsSync) ?? "uv";
    this.child = spawn(uv, ["run", "--locked", "--script", script, cache], { stdio: ["pipe", "pipe", "pipe"] });
    this.child.stderr.resume();
    this.ready = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { reject(new Error("Speech detection preparation took too long.")); this.close(); }, 180_000);
      let prepared = false;
      const lines = createInterface({ input: this.child.stdout });
      lines.on("line", (line) => {
        let result: Detection & { id?: number; ready?: boolean; error?: string };
        try { result = JSON.parse(line); } catch { return; }
        if (result.ready) { prepared = true; clearTimeout(timeout); resolve(); return; }
        if (typeof result.id !== "number") return;
        const request = this.pending.get(result.id);
        if (!request) return;
        clearTimeout(request.timer);
        this.pending.delete(result.id);
        if (result.error) request.reject(new Error(result.error));
        else request.resolve(result);
      });
      const failed = () => {
        clearTimeout(timeout);
        if (!prepared) reject(new Error("Speech detection could not start. Examine the uv installation and network connection."));
        this.close();
      };
      this.child.once("error", failed);
      this.child.once("exit", failed);
      this.child.stdin.on("error", failed);
    });
  }

  async request(kind: "vad" | "turn" | "reset", audio = ""): Promise<Detection> {
    await this.ready;
    if (this.closed) throw new Error("Speech detection stopped.");
    if (this.pending.size >= 24) throw new Error("Speech detection cannot keep pace with the microphone.");
    return new Promise((resolve, reject) => {
      const id = ++this.serial;
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("Speech detection took too long.")); this.close(); }, 4000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(`${JSON.stringify({ id, kind, audio })}\n`);
    });
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.child.kill();
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error("Speech detection stopped."));
    }
    this.pending.clear();
  }
}
