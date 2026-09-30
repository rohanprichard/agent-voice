// Run the talktome command for the OpenClaw plugin.
//
// This file has no OpenClaw imports, so the TalkToMe tests can load it directly.
// The command already knows whether this computer is the Mac or a server that
// is paired with it through the remote bridge.

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const LISTEN_TIMEOUT = 25;
// A ring lasts 30 seconds, and a remote call waits up to 60 for the laptop.
const CALL_TIMEOUT_MS = 100_000;
const REPLY_TIMEOUT_MS = 60_000;

export class TalkToMeError extends Error {}

export function findCommand(env = process.env) {
  const configured = (env.TALKTOME_COMMAND || "").trim();
  if (configured) return configured;
  for (const dir of (env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    const candidate = path.join(dir, "talktome");
    if (isExecutable(candidate)) return candidate;
  }
  const local = path.join(os.homedir(), ".local", "bin", "talktome");
  return isExecutable(local) ? local : null;
}

function isExecutable(file) {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

// remote-status also prints inbox lines, so read the first JSON object.
export function firstJson(output) {
  const start = output.indexOf("{");
  if (start < 0) throw new TalkToMeError("talktome printed no result.");
  let depth = 0;
  let inString = false;
  for (let i = start; i < output.length; i += 1) {
    const ch = output[i];
    if (inString) {
      if (ch === "\\") i += 1;
      else if (ch === '"') inString = false;
    } else if (ch === '"') inString = true;
    else if (ch === "{") depth += 1;
    else if (ch === "}" && --depth === 0) {
      try {
        return JSON.parse(output.slice(start, i + 1));
      } catch {
        break;
      }
    }
  }
  throw new TalkToMeError("talktome printed a result that is not JSON.");
}

export function remoteSetting(value) {
  const setting = String(value ?? "auto").trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(setting)) return true;
  if (["0", "false", "no", "off"].includes(setting)) return false;
  return null;
}

// Markdown and code do not read aloud well.
export function speakable(text) {
  return String(text ?? "")
    .replace(/```[\s\S]*?(```|$)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "a link")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, "")
    .replace(/(\*\*|__|\*|`)/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function run(command, args, timeoutMs) {
  const name = args.find((arg) => !arg.startsWith("-")) ?? "command";
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    let err = "";
    child.stdout.on("data", (chunk) => (out += chunk));
    child.stderr.on("data", (chunk) => (err += chunk));
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new TalkToMeError(`talktome ${name} did not answer in ${timeoutMs / 1000} seconds.`));
    }, timeoutMs);
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(new TalkToMeError(error.message));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code) {
        const lines = err.trim().split("\n").filter(Boolean);
        reject(new TalkToMeError(lines.at(-1) || `talktome ${name} failed.`));
      } else {
        resolve(out);
      }
    });
  });
}

export class TalkToMeClient {
  constructor(command, remote) {
    this.command = command;
    this.remote = remote;
  }

  static async discover(settings = {}, env = process.env) {
    const command = settings.command || findCommand(env);
    if (!command) {
      throw new TalkToMeError(
        "The talktome command is not installed on this computer. " +
          "Install it with `uv tool install git+https://github.com/rohanprichard/talktome`.",
      );
    }
    let remote = remoteSetting(settings.remote ?? env.TALKTOME_REMOTE);
    if (remote === null) {
      const status = firstJson(await run(command, ["remote-status"], 15_000));
      remote = Boolean(status.configured) && status.role === "agent";
    }
    return new TalkToMeClient(command, remote);
  }

  async json(args, timeoutMs) {
    const full = this.remote ? ["--remote", ...args] : args;
    return firstJson(await run(this.command, full, timeoutMs));
  }

  call(thread, greeting, name) {
    const args = ["call", "--agent", "openclaw", "--thread", thread, `--greeting=${greeting}`];
    if (!this.remote) args.push("--connection", "cooperative");
    if (name) args.push(`--name=${name}`);
    return this.json(args, CALL_TIMEOUT_MS);
  }

  listen(thread, after) {
    const args = ["listen", "--thread", thread, "--after", String(after), "--timeout", String(LISTEN_TIMEOUT)];
    return this.json(args, (LISTEN_TIMEOUT + 45) * 1000);
  }

  reply(thread, callId, turnId, itemId, text, final) {
    const args = [
      "reply",
      "--thread", thread,
      "--call-id", callId,
      "--turn-id", turnId,
      "--item-id", itemId,
      `--text=${text}`,
    ];
    if (!final) args.push("--progress");
    return this.json(args, REPLY_TIMEOUT_MS);
  }

  end() {
    return this.json(["end"], REPLY_TIMEOUT_MS);
  }
}

const MAX_LISTEN_FAILURES = 4;
const FAILED = "Sorry, something went wrong on my side.";

// One live call. It listens for spoken turns and runs each one through
// `runAgent`, which receives the text, an `onBlockReply` callback, and an abort
// signal. The newest block reply is held, and the one before it is spoken as
// progress. When the run ends, the held reply is spoken as the final reply.
// When the user talks over a turn, the laptop cancels it and the run is aborted.
export class VoiceCall {
  constructor({ thread, client, runAgent, log = () => {}, sleep }) {
    this.thread = thread;
    this.client = client;
    this.runAgent = runAgent;
    this.log = log;
    this.sleep = sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.closed = false;
    this.seen = new Set();
    this.cancelled = new Set();
    this.current = null;
    this.queue = Promise.resolve();
  }

  start() {
    this.listening = this.listen();
    return this;
  }

  async listen() {
    let after = 0;
    let failures = 0;
    try {
      while (!this.closed) {
        let result;
        try {
          result = await this.client.listen(this.thread, after);
        } catch (error) {
          failures += 1;
          this.log(`listen failed (${failures}): ${error.message}`);
          if (failures >= MAX_LISTEN_FAILURES) break;
          await this.sleep(2 ** failures * 1000);
          continue;
        }
        failures = 0;
        after = Number(result.seq) || 0;
        for (const event of result.events ?? []) {
          if (event.type === "turn.cancelled") this.cancel(event.turn_id);
        }
        if (result.closed) break;
        const pending = result.pending;
        if (pending && !this.seen.has(pending.turn_id)) this.enqueue(pending);
      }
    } finally {
      this.close();
    }
  }

  enqueue(pending) {
    this.seen.add(pending.turn_id);
    this.queue = this.queue
      .then(() => this.runTurn(pending))
      .catch((error) => this.log(`turn failed: ${error.message}`));
  }

  cancel(turnId) {
    this.cancelled.add(turnId);
    if (this.current?.turnId === turnId) this.current.abort.abort();
  }

  close() {
    this.closed = true;
    this.current?.abort.abort();
  }

  async end() {
    this.close();
    return this.client.end();
  }

  async runTurn(pending) {
    if (this.closed || this.cancelled.has(pending.turn_id)) return;
    const turn = {
      callId: pending.call_id,
      turnId: pending.turn_id,
      abort: new AbortController(),
      held: null,
      items: 0,
    };
    this.current = turn;
    const live = () => !this.closed && !turn.abort.signal.aborted;
    const onBlockReply = async (payload) => {
      const text = speakable(payload?.text);
      if (!text || !live()) return;
      if (turn.held) await this.speak(turn, turn.held, false);
      turn.held = text;
    };
    let result;
    try {
      result = await this.runAgent(pending.text, {
        onBlockReply,
        abortSignal: turn.abort.signal,
        turnId: turn.turnId,
      });
    } catch (error) {
      this.log(`agent run failed: ${error.message}`);
      result = { texts: [], failed: true };
    } finally {
      if (this.current === turn) this.current = null;
    }
    if (!live()) return;
    let text = turn.held;
    if (text === null) text = speakable((result?.texts ?? []).join(" "));
    if (!text && result?.failed) text = FAILED;
    await this.speak(turn, text, true);
  }

  async speak(turn, text, final) {
    const itemId = final ? `${turn.turnId}-final` : `${turn.turnId}-${++turn.items}`;
    try {
      await this.client.reply(this.thread, turn.callId, turn.turnId, itemId, text, final);
    } catch (error) {
      // A cancelled or replaced turn refuses replies. The next turn is already
      // on its way, so the reply is dropped.
      this.log(`reply not spoken: ${error.message}`);
    }
  }
}
