// A link to one talktome-server: a child process on this computer, or the same
// program over SSH on a server. They talk in JSON lines on stdin and stdout.
// When the process stops, the link starts it again with backoff.

import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import readline from "node:readline";

export type LinkFrame = { type: string; [field: string]: unknown };

export type LinkState = "connecting" | "connected" | "failed";

export type LinkOptions = {
  id: string; // "local", or "ssh:" and the SSH host
  command: string;
  args: string[];
  minBackoffMs?: number;
  maxBackoffMs?: number;
};

// The command that starts talktome-server on a server, found on PATH or where
// `uv tool install` puts it. A shell over SSH often has no ~/.local/bin on PATH.
export const REMOTE_SERVER = 'exec "$(command -v talktome-server || echo ~/.local/bin/talktome-server)"';

export function sshArgs(host: string, command: string): string[] {
  return [
    "-T",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
    host,
    command,
  ]; // prettier-ignore
}

export class ServerLink extends EventEmitter {
  state: LinkState = "connecting";
  error = "";
  name = "";
  private child: ChildProcess | null = null;
  private stopped = false;
  private failures = 0;
  private timer: NodeJS.Timeout | null = null;

  constructor(readonly options: LinkOptions) {
    super();
  }

  get id(): string {
    return this.options.id;
  }

  start(): void {
    this.stopped = false;
    this.launch();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.child?.kill();
  }

  // retry reconnects now, for example after the computer wakes from sleep.
  retry(): void {
    if (this.stopped || this.state === "connected") return;
    if (this.timer) clearTimeout(this.timer);
    this.failures = 0;
    this.child?.kill();
    if (!this.child) this.launch();
  }

  send(frame: LinkFrame): boolean {
    if (!this.child?.stdin?.writable || this.state !== "connected") return false;
    this.child.stdin.write(JSON.stringify(frame) + "\n");
    return true;
  }

  private launch(): void {
    this.setState("connecting", "");
    const child = spawn(this.options.command, this.options.args, { stdio: ["pipe", "pipe", "pipe"] });
    this.child = child;
    let lastError = "";
    child.stderr?.setEncoding("utf8");
    child.stderr?.on("data", (text: string) => {
      const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
      if (lines.length) lastError = lines[lines.length - 1];
    });
    readline.createInterface({ input: child.stdout! }).on("line", (line) => {
      let frame: LinkFrame;
      try {
        frame = JSON.parse(line);
      } catch {
        return;
      }
      if (frame.type === "hello") {
        this.name = String(frame.name ?? "");
        this.failures = 0;
        this.setState("connected", "");
      }
      this.emit("frame", frame);
    });
    child.on("error", (error) => {
      lastError = error.message;
    });
    child.on("close", (code) => {
      if (this.child !== child) return;
      this.child = null;
      const wasConnected = this.state === "connected";
      this.setState("failed", explain(lastError, code));
      if (wasConnected) this.emit("dropped");
      if (this.stopped) return;
      this.failures += 1;
      const min = this.options.minBackoffMs ?? 1000;
      const max = this.options.maxBackoffMs ?? 60_000;
      const wait = Math.min(max, min * 2 ** Math.min(this.failures - 1, 10));
      this.timer = setTimeout(() => this.launch(), wait);
    });
  }

  private setState(state: LinkState, error: string): void {
    this.state = state;
    this.error = error;
    this.emit("state");
  }
}

// explain turns what ssh or the server printed into something the user can act on.
export function explain(stderr: string, code: number | null): string {
  if (/Permission denied/i.test(stderr)) return "SSH asked for a password. talktome uses SSH keys only. Run ssh-copy-id with this host in Terminal, then try again.";
  if (/Host key verification failed/i.test(stderr)) return "SSH does not know this server yet. Run ssh with this host once in Terminal to accept its key.";
  if (/Could not resolve hostname/i.test(stderr)) return "SSH could not find this host. Check the name.";
  if (/Connection (timed out|refused)|Operation timed out|No route to host/i.test(stderr)) return "The server did not answer. Check that it is on and reachable.";
  if (code === 127 || /not found|No such file/i.test(stderr)) return "talktome-server is not installed there.";
  return stderr || (code === null ? "The connection stopped." : `The server stopped (exit ${code}).`);
}
