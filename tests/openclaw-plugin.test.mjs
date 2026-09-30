import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  TalkToMeClient,
  TalkToMeError,
  VoiceCall,
  firstJson,
  run,
  speakable,
  speechSeconds,
} from "../src/talktome/plugins/openclaw/talktome.mjs";

// A laptop that plays back a scripted list of listen results.
class FakeClient {
  constructor(listens) {
    this.listens = listens;
    this.replies = [];
    this.remote = true;
  }

  async listen() {
    const next = this.listens.shift();
    if (typeof next === "function") return next();
    if (next) return next;
    // Hang up only after the queued turns finish, as a user would.
    await this.call?.queue;
    return { closed: true, seq: 99 };
  }

  async reply(thread, callId, turnId, itemId, text, final) {
    this.replies.push([itemId, text, final]);
    return { ok: true };
  }

  async end() {
    return { status: "ended" };
  }
}

const turn = (id, text) => ({ seq: 1, events: [], pending: { call_id: "call-1", turn_id: id, text } });

async function callWith(listens, runAgent) {
  const client = new FakeClient(listens);
  const call = new VoiceCall({ thread: "openclaw-1", client, runAgent, sleep: async () => {} });
  client.call = call;
  await call.start().listening;
  await call.queue;
  return client;
}

test("each spoken turn runs the agent and its answer ends the turn", async () => {
  const prompts = [];
  const client = await callWith([turn("t1", "What time is it?")], async (prompt) => {
    prompts.push(prompt);
    return { texts: ["It is **noon**."] };
  });
  assert.deepEqual(prompts, ["What time is it?"]);
  assert.deepEqual(client.replies, [["t1-final", "It is noon.", true]]);
});

test("block replies speak as progress and the last one is the final reply", async () => {
  const client = await callWith([turn("t1", "Check the disk")], async (_prompt, { onBlockReply }) => {
    await onBlockReply({ text: "Let me check." });
    await onBlockReply({ text: "It has 163 GB free." });
    // The run also returns the text it streamed. It must not be spoken twice.
    return { texts: ["Let me check.", "It has 163 GB free."] };
  });
  assert.deepEqual(client.replies, [
    ["t1-1", "Let me check.", false],
    ["t1-final", "It has 163 GB free.", true],
  ]);
});

test("a failed run still ends the turn with something spoken", async () => {
  const client = await callWith([turn("t1", "Hello")], async () => {
    throw new Error("model offline");
  });
  assert.deepEqual(client.replies, [["t1-final", "Sorry, something went wrong on my side.", true]]);
});

test("talking over a turn aborts the run and speaks nothing for it", async () => {
  let aborted = false;
  let release;
  const running = new Promise((resolve) => (release = resolve));
  const listens = [
    turn("t1", "Tell me a long story"),
    async () => {
      await running;
      return { seq: 2, events: [{ type: "turn.cancelled", turn_id: "t1" }], pending: null };
    },
  ];
  const client = await callWith(listens, async (_prompt, { abortSignal, onBlockReply }) => {
    abortSignal.addEventListener("abort", () => (aborted = true));
    release();
    await new Promise((resolve) => abortSignal.addEventListener("abort", resolve));
    await onBlockReply({ text: "Once upon a time" });
    return { texts: ["Once upon a time"] };
  });
  assert.equal(aborted, true);
  assert.deepEqual(client.replies, []);
});

test("hanging up mid-turn speaks the goodbye and lets the work finish", async () => {
  let finished = false;
  let aborted = false;
  let call;
  const client = new FakeClient([turn("t1", "Refactor the whole repo")]);
  client.end = async () => {
    client.ended = client.replies.slice();
    return { status: "ended" };
  };
  call = new VoiceCall({
    thread: "openclaw-1",
    client,
    sleep: async () => {},
    runAgent: async (_prompt, { onBlockReply, abortSignal }) => {
      abortSignal.addEventListener("abort", () => (aborted = true));
      await onBlockReply({ text: "I'll call you back when I'm done with that." });
      await call.end();
      finished = true;
      await onBlockReply({ text: "All done." });
      return { texts: ["All done."] };
    },
  });
  client.call = call;
  await call.start().listening;
  await call.queue;
  assert.deepEqual(client.ended, [["t1-final", "I'll call you back when I'm done with that.", true]]);
  assert.equal(finished, true);
  assert.equal(aborted, false);
  assert.equal(client.replies.length, 1);
});

test("a goodbye gets time to play before the hang-up", () => {
  assert.equal(speechSeconds(""), 1.5);
  assert.equal(speechSeconds("word ".repeat(1000)), 20);
});

test("a turn is run once even when listen repeats it", async () => {
  let runs = 0;
  await callWith([turn("t1", "Hi"), turn("t1", "Hi")], async () => {
    runs += 1;
    return { texts: ["Hello"] };
  });
  assert.equal(runs, 1);
});

test("a laptop that keeps failing ends the call", async () => {
  let listens = 0;
  const failing = () => {
    listens += 1;
    throw new TalkToMeError("No cooperative remote call is active.");
  };
  const client = new FakeClient([failing, failing, failing, failing, failing]);
  const call = new VoiceCall({ thread: "openclaw-1", client, runAgent: async () => ({}), sleep: async () => {} });
  await call.start().listening;
  assert.equal(listens, 4);
  assert.equal(call.closed, true);
});

test("markdown and code are not read aloud", () => {
  const text = "## Result\n\n- **Disk**: 163 GB free\n- See [the docs](https://x.io)\n```sh\ndf -h\n```\nDone.";
  assert.equal(speakable(text), "Result Disk: 163 GB free See the docs Done.");
});

test("remote-status is read past its inbox lines", () => {
  const output = 'inbox: /x\nfallback inbox: /y\n{"configured": true, "role": "agent", "note": "a } b"}\n';
  assert.deepEqual(firstJson(output), { configured: true, role: "agent", note: "a } b" });
  assert.throws(() => firstJson("nothing"), TalkToMeError);
});

function echoCommand() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "talktome-openclaw-"));
  const script = path.join(dir, "talktome");
  fs.writeFileSync(
    script,
    [
      "#!/usr/bin/env node",
      "const argv = process.argv.slice(2);",
      "if (argv.includes('fail')) { console.error('The laptop is offline.'); process.exit(1); }",
      "if (argv.includes('remote-status')) { console.log('inbox: /x'); console.log(JSON.stringify({configured: true, role: 'agent'})); process.exit(0); }",
      "console.log(JSON.stringify({argv}));",
    ].join("\n"),
  );
  fs.chmodSync(script, 0o755);
  return script;
}

test("a paired server sends every command across the bridge", async () => {
  const client = await TalkToMeClient.discover({}, { TALKTOME_COMMAND: echoCommand() });
  assert.equal(client.remote, true);
  const { argv } = await client.call("openclaw-1", "-Hi there", null);
  assert.deepEqual(argv.slice(0, 4), ["--remote", "call", "--agent", "openclaw"]);
  assert.ok(argv.includes("--greeting=-Hi there"));
  assert.ok(!argv.includes("--connection"));
});

test("on the Mac a call is cooperative", async () => {
  const client = await TalkToMeClient.discover({ command: echoCommand(), remote: "false" });
  const { argv } = await client.call("openclaw-1", "Hi", "Deploy");
  assert.equal(argv[0], "call");
  assert.deepEqual(argv.slice(-3), ["--connection", "cooperative", "--name=Deploy"]);
});

test("a refused command reports its last line", async () => {
  await assert.rejects(run(echoCommand(), ["listen", "fail"], 10_000), /The laptop is offline\./);
});
