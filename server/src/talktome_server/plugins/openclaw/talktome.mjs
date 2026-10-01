// Talk to the talktome server for the OpenClaw plugin.
//
// The server runs on this machine while the talktome app is connected to it.
// Its local API is HTTP over a Unix socket that only this user can open.
// This file has no OpenClaw imports, so the tests can load it directly.

import http from "node:http";
import os from "node:os";
import path from "node:path";

// A call rings for up to 45 seconds and then waits up to 90 for the answer.
const CALL_TIMEOUT_MS = 240_000;
const TURN_TIMEOUT_MS = 150_000;
const SHORT_TIMEOUT_MS = 30_000;
const FAILED = "Sorry, something went wrong on my side.";
export const NOT_RUNNING = "The talktome server is not running on this machine. Connect to it from the talktome app.";

export class TalkToMeError extends Error {}

// The server's folder. talktome-server uses the same rule.
export function dataDir(env = process.env, platform = process.platform) {
  if (env.TALKTOME_DIR) return env.TALKTOME_DIR;
  const home = env.HOME || os.homedir();
  if (platform === "darwin") return path.join(home, "Library", "Application Support", "talktome-server");
  return path.join(env.XDG_CONFIG_HOME || path.join(home, ".config"), "talktome-server");
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

export class LocalClient {
  constructor(socketPath) {
    this.socketPath = socketPath;
  }

  static default(settings = {}, env = process.env) {
    return new LocalClient(path.join(settings.dataDir || dataDir(env), "server.sock"));
  }

  request(method, route, body, timeoutMs) {
    return new Promise((resolve, reject) => {
      const data = body === undefined ? undefined : JSON.stringify(body);
      const req = http.request(
        { socketPath: this.socketPath, path: route, method, headers: { "Content-Type": "application/json" } },
        (res) => {
          let raw = "";
          res.setEncoding("utf8");
          res.on("data", (chunk) => (raw += chunk));
          res.on("end", () => {
            let result;
            try {
              result = JSON.parse(raw || "{}");
            } catch {
              reject(new TalkToMeError("The talktome server sent a reply that is not JSON."));
              return;
            }
            if (res.statusCode !== 200) {
              reject(new TalkToMeError(result.message || `The talktome server failed (${res.statusCode}).`));
            } else {
              resolve(result);
            }
          });
        },
      );
      req.setTimeout(timeoutMs, () => req.destroy(new TalkToMeError("The talktome server did not answer in time.")));
      req.on("error", (error) => {
        if (error instanceof TalkToMeError) reject(error);
        else if (error.code === "ENOENT" || error.code === "ECONNREFUSED") reject(new TalkToMeError(NOT_RUNNING));
        else reject(new TalkToMeError(`The talktome server did not answer: ${error.message}`));
      });
      if (data !== undefined) req.write(data);
      req.end();
    });
  }

  status() {
    return this.request("GET", "/v1/status", undefined, SHORT_TIMEOUT_MS);
  }

  call({ reason, greeting = "", question = "", choices = [] }) {
    return this.request("POST", "/v1/call", { reason, greeting, question, choices }, CALL_TIMEOUT_MS);
  }

  turn(say) {
    return this.request("POST", "/v1/turn", { say }, TURN_TIMEOUT_MS);
  }

  async progress(say) {
    return Boolean((await this.request("POST", "/v1/progress", { say }, SHORT_TIMEOUT_MS)).spoken);
  }

  end(say = "") {
    return this.request("POST", "/v1/end", { say }, SHORT_TIMEOUT_MS);
  }
}

// One live call. Each thing the user says runs through `runAgent`, which gets
// the text, an `onBlockReply` callback, and an abort signal. The newest block
// reply is held, and the one before it is spoken as progress. When the run
// ends, the held reply is the answer, and `turn` speaks it and returns what the
// user says next. A hang-up by the agent does not abort its run: the agent may
// end the call, keep working, and call back with the result.
export class VoiceCall {
  constructor({ client, runAgent, log = () => {} }) {
    this.client = client;
    this.runAgent = runAgent;
    this.log = log;
    this.closed = false;
    this.current = null;
  }

  start(first) {
    this.done = this.converse(first);
    return this;
  }

  async converse(first) {
    let heard = first.user_said;
    let ended = first.ended;
    try {
      while (!this.closed && !ended) {
        const answer = heard ? await this.runTurn(heard) : "";
        if (this.closed) break;
        const result = await this.client.turn(answer);
        heard = result.user_said;
        ended = result.ended;
      }
    } catch (error) {
      this.log(`the call stopped: ${error.message}`);
    } finally {
      this.closed = true;
    }
  }

  async runTurn(text) {
    const turn = { abort: new AbortController(), held: null };
    this.current = turn;
    const onBlockReply = async (payload) => {
      const spoken = speakable(payload?.text);
      if (!spoken || this.closed) return;
      if (turn.held) {
        try {
          await this.client.progress(turn.held);
        } catch (error) {
          this.log(`progress not spoken: ${error.message}`);
        }
      }
      turn.held = spoken;
    };
    let result;
    try {
      result = await this.runAgent(text, { onBlockReply, abortSignal: turn.abort.signal });
    } catch (error) {
      this.log(`agent run failed: ${error.message}`);
      result = { texts: [], failed: true };
    } finally {
      if (this.current === turn) this.current = null;
    }
    let answer = turn.held ?? speakable((result?.texts ?? []).join(" "));
    if (!answer && result?.failed) answer = FAILED;
    return answer;
  }

  // Hang up. What the agent already said in this turn is the goodbye.
  async end() {
    const goodbye = this.current?.held ?? "";
    this.closed = true;
    return this.client.end(goodbye);
  }

  // Stop, for example when the gateway stops. This aborts the running turn.
  close() {
    this.closed = true;
    this.current?.abort.abort();
  }
}
