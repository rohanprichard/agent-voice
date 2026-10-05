import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";

function harness() {
  const sent: string[] = [];
  const commits: unknown[] = [];
  const audio = { paused: false, pauses: 0, plays: 0, pause() { this.paused = true; this.pauses++; }, play() { this.paused = false; this.plays++; return Promise.resolve(); }, dispatchEvent() {} };
  let vad: () => Promise<{ probabilities: number[] }> = async () => ({ probabilities: [0, 0] });
  let endpoint: () => Promise<{ probability: number }> = async () => ({ probability: 0 });
  let token: () => Promise<string> = async () => "token";
  let sockets = 0;
  let microphone: () => Promise<unknown> = async () => { throw new Error("No test microphone."); };
  const sandbox = vm.createContext({
    window: { talktome: {
      detectorStart: async () => undefined,
      detectorAudio: (_id: string, kind: string) => kind === "turn" ? endpoint() : kind === "vad" ? vad() : Promise.resolve({}),
      detectorStop: async () => undefined,
      speechToken: () => token(),
      speechVoice: async () => "voice",
    } },
    WebSocket: class { static OPEN = 1; constructor() { sockets++; } },
    setTimeout, clearTimeout, URLSearchParams, Float32Array, Uint8Array, DataView, Event, btoa,
    navigator: { mediaDevices: { getUserMedia: () => microphone() } },
  });
  const turns = fs.readFileSync(path.join(__dirname, "turns.js"), "utf8");
  const voice = fs.readFileSync(path.join(__dirname, "voice.js"), "utf8");
  vm.runInContext(`${turns}\n${voice}\nglobalThis.subject = new VoiceCall("call", text => sent.push(text), () => {});`, Object.assign(sandbox, { sent }));
  const subject = sandbox.subject;
  subject.input = { readyState: 1, send: (data: string) => commits.push(JSON.parse(data)), close() {} };
  const feed = (probability: number, frames: number) => { for (let i = 0; i < frames; i++) subject.detectSpeech(probability); };
  const receive = (message_type: string, text: string) => subject.receive(JSON.stringify({ message_type, text }));
  return { subject, sent, commits, feed, receive, audio,
    vad: (fn: typeof vad) => { vad = fn; },
    endpoint: (fn: typeof endpoint) => { endpoint = fn; },
    token: (fn: typeof token) => { token = fn; },
    sockets: () => sockets,
    microphone: (fn: typeof microphone) => { microphone = fn; },
  };
}

const settle = async () => { await new Promise((resolve) => setImmediate(resolve)); };

test("an incomplete pause keeps committed segments in one thought", async () => {
  const h = harness();
  h.feed(0.9, 10);
  h.receive("committed_transcript", "Change the button to");
  h.feed(0, 45);
  await settle();
  assert.equal(h.sent.length, 0);
  assert.equal(h.commits.length, 0);
  h.feed(0.9, 10);
  h.receive("partial_transcript", "Use blue.");
  h.feed(0, 12);
  h.subject.commitTurn();
  h.receive("committed_transcript", "blue.");
  assert.deepEqual(h.sent, ["Change the button to blue."]);
  h.subject.stop();
});

test("speech that resumes while transcription waits cancels delivery", () => {
  const h = harness();
  h.feed(0.9, 10);
  h.receive("partial_transcript", "Use blue.");
  h.feed(0, 12);
  h.subject.commitTurn();
  h.feed(0.9, 5);
  h.receive("committed_transcript", "Use blue.");
  assert.equal(h.sent.length, 0);
  h.feed(0, 12);
  h.subject.commitTurn();
  h.receive("committed_transcript", "Actually, use green.");
  assert.deepEqual(h.sent, ["Use blue. Actually, use green."]);
  h.subject.stop();
});

test("delivery waits for microphone frames that VAD has not examined", () => {
  const h = harness();
  h.feed(0.9, 10);
  h.receive("partial_transcript", "Use blue.");
  h.feed(0, 12);
  h.subject.commitTurn();
  h.subject.detectorPending = 1;
  h.receive("committed_transcript", "Use blue.");
  assert.equal(h.sent.length, 0);
  h.feed(0.9, 3);
  h.subject.detectorPending = 0;
  h.subject.deliverTurn();
  assert.equal(h.sent.length, 0);
  h.subject.stop();
});

test("a stale semantic result cannot end resumed speech", async () => {
  const h = harness();
  let finish!: (value: { probability: number }) => void;
  h.endpoint(() => new Promise((resolve) => { finish = resolve; }));
  h.feed(0.9, 10);
  h.feed(0, 12);
  h.feed(0.9, 3);
  finish({ probability: 0.95 });
  await settle();
  assert.equal(h.commits.length, 0);
  h.subject.stop();
});

test("a complete thought requests one commit and delivers once", async () => {
  const h = harness();
  h.endpoint(async () => ({ probability: 0.95 }));
  h.feed(0.9, 3);
  h.receive("partial_transcript", "Yes.");
  h.feed(0, 12);
  await settle();
  h.feed(0, 25);
  await settle();
  assert.equal(h.commits.length, 1);
  h.receive("committed_transcript", "Yes.");
  h.receive("committed_transcript", "");
  assert.deepEqual(h.sent, ["Yes."]);
  h.subject.stop();
});

test("the maximum silence wait permits a reply when the model remains uncertain", () => {
  const h = harness();
  h.feed(0.9, 10);
  h.receive("partial_transcript", "Yes.");
  h.feed(0, 160);
  assert.equal(h.commits.length, 1);
  h.subject.stop();
});

test("a brief acknowledgment resumes a paused reply without a new agent request", () => {
  const h = harness();
  h.subject.speaking = true;
  h.subject.audio = h.audio;
  h.feed(0.9, 3);
  assert.equal(h.audio.pauses, 1);
  h.receive("partial_transcript", "mm-hmm");
  assert.equal(h.subject.suppressReplies, false);
  h.feed(0, 12);
  h.subject.commitTurn();
  h.receive("committed_transcript", "mm-hmm");
  assert.equal(h.audio.plays, 1);
  assert.equal(h.sent.length, 0);
  h.subject.stop();
});

test("a short stop command interrupts and discards queued replies", () => {
  const h = harness();
  h.subject.speaking = true;
  h.subject.audio = h.audio;
  h.subject.queued = 3;
  h.feed(0.9, 3);
  h.receive("partial_transcript", "Stop.");
  assert.equal(h.subject.suppressReplies, true);
  assert.equal(h.subject.skipTo, 3);
  h.subject.speak("An old reply.");
  assert.equal(h.subject.queued, 3);
  h.feed(0, 12);
  h.subject.commitTurn();
  h.receive("committed_transcript", "Stop.");
  assert.deepEqual(h.sent, ["Stop."]);
  assert.equal(h.subject.suppressReplies, false);
  h.subject.stop();
});

test("a noise event without words resumes playback", () => {
  const h = harness();
  h.subject.speaking = true;
  h.subject.audio = h.audio;
  h.feed(0.9, 3);
  h.feed(0, 65);
  assert.equal(h.audio.plays, 1);
  assert.equal(h.sent.length, 0);
  h.subject.stop();
});

test("stopping a reply before its token arrives prevents late playback", async () => {
  const h = harness();
  let finish!: (token: string) => void;
  h.token(() => new Promise((resolve) => { finish = resolve; }));
  const playing = h.subject.playSpeech("Old reply.");
  h.subject.stopSpeaking();
  finish("token");
  await playing;
  assert.equal(h.sockets(), 0);
  h.subject.stop();
});


test("a short answer waits for its first transcript before requesting final text", async () => {
  const h = harness();
  h.endpoint(async () => ({ probability: 0.95 }));
  h.feed(0.9, 3);
  h.feed(0, 12);
  await settle();
  assert.equal(h.commits.length, 0);
  h.receive("partial_transcript", "No.");
  assert.equal(h.commits.length, 1);
  h.receive("committed_transcript", "No.");
  assert.deepEqual(h.sent, ["No."]);
  h.subject.stop();
});


test("ending a call while microphone permission waits releases the late stream", async () => {
  const h = harness();
  let finish!: (stream: unknown) => void;
  let stopped = 0;
  h.microphone(() => new Promise((resolve) => { finish = resolve; }));
  const starting = h.subject.start();
  await settle();
  h.subject.stop();
  finish({ getTracks: () => [{ stop: () => { stopped++; } }] });
  await starting;
  assert.equal(stopped, 1);
  assert.equal(h.sockets(), 0);
});

test("muting an interrupted turn clears reply suppression and rejects late text", () => {
  const h = harness();
  h.subject.speaking = true;
  h.subject.audio = h.audio;
  h.feed(0.9, 3);
  h.receive("partial_transcript", "Wait.");
  assert.equal(h.subject.suppressReplies, true);
  h.subject.setMuted(true);
  h.receive("committed_transcript", "Wait.");
  assert.equal(h.subject.suppressReplies, false);
  assert.equal(h.sent.length, 0);
  assert.equal(h.subject.input, null);
  h.subject.stop();
});


test("a longer pause does not replace the model's speech context with silence", async () => {
  const h = harness();
  let analyses = 0;
  h.endpoint(async () => { analyses++; return { probability: 0 }; });
  h.feed(0.9, 10);
  h.feed(0, 12);
  await settle();
  h.feed(0, 70);
  await settle();
  assert.equal(analyses, 1);
  assert.equal(h.commits.length, 0);
  h.feed(0.9, 3);
  h.feed(0, 12);
  await settle();
  assert.equal(analyses, 2);
  h.subject.stop();
});


test("interruption retains the first microphone frames without transcribing the agent's playback", async () => {
  const h = harness();
  h.vad(async () => ({ probabilities: [0.9, 0.9] }));
  h.subject.context = { sampleRate: 16000, close: async () => undefined };
  h.subject.speaking = true;
  h.subject.audio = h.audio;
  const frame = new Float32Array(1024).fill(0.25);
  h.subject.capture(frame);
  await settle();
  h.subject.capture(frame);
  await settle();
  const packets = h.commits as { audio_base_64: string }[];
  assert.equal(Buffer.from(packets[0].audio_base_64, "base64").readInt16LE(0), 0);
  assert.equal(Buffer.from(packets[1].audio_base_64, "base64").readInt16LE(0), 0);
  const retained = Buffer.from(packets[2].audio_base_64, "base64");
  assert.equal(retained.length, 4096);
  assert.equal(retained.readInt16LE(0), 8191);
  assert.equal(h.audio.pauses, 1);
  h.subject.stop();
});

test("a VAD result from before mute cannot start a new user turn", async () => {
  const h = harness();
  let finish!: (value: { probabilities: number[] }) => void;
  h.vad(() => new Promise((resolve) => { finish = resolve; }));
  h.subject.capture(new Float32Array(1024).fill(0.25));
  h.subject.setMuted(true);
  h.subject.muted = false;
  finish({ probabilities: [0.9, 0.9, 0.9] });
  await settle();
  assert.equal(h.subject.hasUserTurn(), false);
  h.subject.stop();
});
