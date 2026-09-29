import assert from "node:assert/strict";
import test from "node:test";
import { Microphone, wavBlob } from "../src/talktome/static/audio.js";

test("The WAV encoder preserves samples, duration, and channel metadata", async () => {
  const blob = wavBlob([new Float32Array([0, 0.5, -0.5, 2, -2])], 16000);
  const data = new DataView(await blob.arrayBuffer());
  assert.equal(data.getUint16(22, true), 1);
  assert.equal(data.getUint32(24, true), 16000);
  assert.equal(data.getUint32(40, true), 10);
  assert.equal(data.getInt16(50, true), 32767);
  assert.equal(data.getInt16(52, true), -32768);
});

test("A repeated unpause does not erase speech in progress", () => {
  const recordings = [];
  const mic = new Microphone({
    onAudio() {},
    onRecording(value) {
      recordings.push(value);
    },
    onError() {},
  });
  mic.context = { sampleRate: 16000 };
  mic.consume(new Float32Array(2048).fill(0.1));
  const chunks = mic.chunks;
  mic.setPaused(false);
  assert.equal(mic.recording, true);
  assert.equal(mic.chunks, chunks);
  assert.deepEqual(recordings, [false, true]);
  mic.setPaused(true);
  assert.equal(mic.chunks.length, 0);
});

test("Silence closes one utterance and keeps later speech separate", () => {
  const utterances = [];
  const mic = new Microphone({
    onAudio(blob, timing) {
      utterances.push({ blob, timing });
    },
    onRecording() {},
    onError() {},
  });
  mic.context = { sampleRate: 16000 };
  for (let i = 0; i < 5; i++) mic.consume(new Float32Array(2048).fill(0.1));
  for (let i = 0; i < 10; i++) mic.consume(new Float32Array(2048));
  assert.equal(utterances.length, 1);
  assert.ok(Number.isFinite(utterances[0].timing.speechEndMs));
  assert.ok(utterances[0].timing.captureEndMs >= utterances[0].timing.speechEndMs);
  assert.equal(mic.recording, false);
  assert.equal(mic.chunks.length, 0);
});

test("A brief noise onset signals recording without producing an utterance", () => {
  // One loud buffer starts a recording. An utterance needs 0.22 s of speech.
  // The recording signal does not mean that the user sent a message.
  const signals = [];
  const utterances = [];
  const mic = new Microphone({
    onAudio(blob) {
      utterances.push(blob);
    },
    onRecording(value) {
      signals.push(value);
    },
    onError() {},
  });
  mic.context = { sampleRate: 16000 };
  mic.consume(new Float32Array(2048).fill(0.05));
  for (let i = 0; i < 10; i++) mic.consume(new Float32Array(2048));
  assert.deepEqual(signals, [false, true, false]);
  assert.equal(utterances.length, 0);
});

test("The pause mode sets the silence wait", () => {
  const make = (pauseMode) =>
    new Microphone({
      onAudio() {},
      onRecording() {},
      onError() {},
      pauseMode,
    });
  assert.equal(make("quick").settled(), 0.7);
  assert.equal(make("balanced").settled(), 0.9);
  assert.equal(make("patient").settled(), 1.8);
  assert.equal(make("invalid").settled(), 0.9);
});

test("A pause ends speech after the selected wait", () => {
  const utterances = [];
  const mic = new Microphone({
    pauseMode: "quick",
    onAudio(blob) {
      utterances.push(blob);
    },
    onRecording() {},
    onError() {},
  });
  mic.context = { sampleRate: 16000 };
  for (let i = 0; i < 30; i++) mic.consume(new Float32Array(2048).fill(0.1));
  for (let i = 0; i < 6; i++) mic.consume(new Float32Array(2048));
  assert.equal(utterances.length, 1);
});

test("A breath early in an utterance does not close it", () => {
  const utterances = [];
  const mic = new Microphone({
    onAudio(blob) {
      utterances.push(blob);
    },
    onRecording() {},
    onError() {},
  });
  mic.context = { sampleRate: 16000 };
  for (let i = 0; i < 4; i++) mic.consume(new Float32Array(2048).fill(0.1));
  for (let i = 0; i < 5; i++) mic.consume(new Float32Array(2048)); // 0.64 s
  assert.equal(utterances.length, 0, "a pause this early is a breath, not an ending");
  for (let i = 0; i < 4; i++) mic.consume(new Float32Array(2048).fill(0.1));
  for (let i = 0; i < 10; i++) mic.consume(new Float32Array(2048));
  assert.equal(utterances.length, 1);
});
