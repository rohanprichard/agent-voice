import assert from "node:assert/strict";
import test from "node:test";

import { AudioQueue, currentAudioEvent } from "../src/talktome/static/playback.js";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
}

test("the greeting plays before the first user turn", () => {
  const room = { call_id: "call", turn_id: null };
  const greeting = { call_id: "call", turn_id: "greeting-1", kind: "greeting" };
  assert.equal(currentAudioEvent(greeting, room), true);
  assert.equal(currentAudioEvent(greeting, { ...room, turn_id: "turn-1" }), false);
  assert.equal(currentAudioEvent({ ...greeting, call_id: "old" }, room), false);
  assert.equal(currentAudioEvent({ call_id: "call", turn_id: "turn-1" }, room), false);
  assert.equal(currentAudioEvent({ call_id: "call", turn_id: "turn-1" }, { ...room, turn_id: "turn-1" }), true);
});

test("plays queued audio in order", async () => {
  const played = [];
  const queue = new AudioQueue(async (item) => { played.push(item.audio_id); }, () => {});
  queue.enqueue({ audio_id: "a" });
  queue.enqueue({ audio_id: "b" });
  queue.enqueue({ audio_id: "c" });
  await settle();
  assert.deepEqual(played, ["a", "b", "c"]);
});

test("ignores duplicate audio IDs", async () => {
  const played = [];
  const queue = new AudioQueue(async (item) => { played.push(item.text); }, () => {});
  queue.enqueue({ audio_id: "same", text: "first" });
  queue.enqueue({ audio_id: "same", text: "duplicate" });
  await settle();
  assert.deepEqual(played, ["first"]);
});

test("clear stops queued work and cancels active playback", async () => {
  const active = deferred();
  const played = [];
  let cancellations = 0;
  const queue = new AudioQueue((item) => {
    played.push(item.audio_id);
    return active.promise;
  }, () => { cancellations += 1; });
  queue.enqueue({ audio_id: "active" });
  queue.enqueue({ audio_id: "queued" });
  await settle();
  queue.clear();
  active.resolve();
  await settle();
  assert.deepEqual(played, ["active"]);
  assert.equal(cancellations, 1);
  assert.equal(queue.items.length, 0);
});

test("new generation runs while old playback exits", async () => {
  const oldPlayback = deferred();
  const newPlayback = deferred();
  const played = [];
  const queue = new AudioQueue((item) => {
    played.push(item.audio_id);
    return item.audio_id === "old" ? oldPlayback.promise : newPlayback.promise;
  }, () => {});
  queue.enqueue({ audio_id: "old" });
  await settle();
  queue.clear();
  queue.enqueue({ audio_id: "new" });
  await settle();
  assert.deepEqual(played, ["old", "new"]);
  oldPlayback.resolve();
  await settle();
  assert.equal(queue.running, true);
  queue.enqueue({ audio_id: "next" });
  newPlayback.resolve();
  await settle();
  assert.deepEqual(played, ["old", "new", "next"]);
});
