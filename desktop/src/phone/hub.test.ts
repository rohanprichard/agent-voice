import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { Hub } from "./hub";
import { ServerLink } from "./link";
import { Phone, type Snapshot } from "./phone";

// The server from `uv sync` in server/. The test sets HOME, so it cannot go through uv itself.
const serverBin = path.resolve(__dirname, "../../../server/.venv/bin/talktome-server");

function until(phone: Phone, check: (s: Snapshot) => boolean, ms = 15_000): Promise<Snapshot> {
  return new Promise((resolve, reject) => {
    if (check(phone.snapshot())) return resolve(phone.snapshot());
    const timer = setTimeout(() => reject(new Error("timed out: " + JSON.stringify(phone.snapshot()))), ms);
    const listener = (s: Snapshot) => {
      if (check(s)) {
        clearTimeout(timer);
        phone.off("state", listener);
        resolve(s);
      }
    };
    phone.on("state", listener);
  });
}

function post(socket: string, route: string, body: object): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const req = http.request({ socketPath: socket, path: route, method: "POST", headers: { "content-type": "application/json" } }, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => resolve(JSON.parse(data || "{}")));
    });
    req.on("error", reject);
    req.end(JSON.stringify(body));
  });
}

test("calls through a real talktome-server", { skip: !fs.existsSync(serverBin) && "run uv sync in server/ first" }, async () => {
  const dir = fs.mkdtempSync("/tmp/tt-hub-");
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "tt-home-"));
  const project = path.join(home, "code", "site");
  fs.mkdirSync(project, { recursive: true });
  const socket = path.join(dir, "server.sock");
  const link = new ServerLink({
    id: "local",
    command: "env",
    args: [`TALKTOME_DIR=${dir}`, `HOME=${home}`, serverBin],
    minBackoffMs: 200,
    maxBackoffMs: 400,
  });
  const hub = new Hub();
  const phone = new Phone(hub);
  hub.add(link, "This Mac");
  try {
    await until(phone, (s) => s.agents.some((a) => a.online), 60_000);

    // The agent rings with a question, and the user picks a choice.
    const asked = post(socket, "/v1/call", { reason: "Deploy", question: "Ship it?", choices: ["yes", "no"] });
    const ringing = await until(phone, (s) => s.calls.some((c) => c.state === "ringing"));
    const ring = ringing.calls[0];
    assert.equal(ring.agent.name, "This Mac");
    assert.equal(ring.question, "Ship it?");
    await phone.answer(ring.id);
    await phone.say(ring.id, "yes");
    assert.deepEqual(await asked, { answered: true, answer: "yes", choice: { index: 0, label: "yes" } });
    await until(phone, (s) => s.calls.find((c) => c.id === ring.id)?.state === "ended");

    // An open session reports through its hooks, and the user joins it.
    const session = { host: "claude", session_id: "open1", cwd: project };
    await post(socket, "/v1/hook", { ...session, event: "SessionStart" });
    await post(socket, "/v1/hook", { ...session, event: "UserPromptSubmit" });
    const seen = await until(phone, (s) => s.agents.some((a) => a.targets.some((t) => t.joinable)));
    const target = seen.agents[0].targets.find((t) => t.joinable)!;
    assert.equal(target.project, "site (open session)");
    const callId = await phone.callAgent("local", target.target_id, "join");
    await until(phone, (s) => s.calls.find((c) => c.id === callId)?.state === "live");
    await phone.say(callId, "Skip the docs.");
    await until(phone, (s) => s.calls.find((c) => c.id === callId)!.lines.some((l) => l.text === "I'll pass that on."));
    const context = await post(socket, "/v1/hook", { ...session, event: "PostToolUse" });
    assert.match(String(context.context), /Skip the docs/);
    const stopped = post(socket, "/v1/hook", { ...session, event: "Stop", last_assistant_message: "Done, **no docs**." });
    const replied = await until(phone, (s) => s.calls.find((c) => c.id === callId)?.waiting === false);
    assert.equal(replied.calls.find((c) => c.id === callId)!.lines.at(-1)!.text, "Done, no docs.");

    // When the server stops, the call ends and the link comes back.
    await phone.hangUp(callId);
    assert.deepEqual(await stopped, {});
    await post(socket, "/v1/quit", {});
    await until(phone, (s) => s.agents.every((a) => !a.online));
    await until(phone, (s) => s.agents.some((a) => a.online), 60_000);
  } finally {
    hub.stop();
    fs.rmSync(dir, { recursive: true, force: true });
    fs.rmSync(home, { recursive: true, force: true });
  }
});
