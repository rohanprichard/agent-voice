import assert from "node:assert/strict";
import test from "node:test";

import { applyEvent } from "../src/talktome/static/stream.js";

const delta = (text, extra = {}) => ({
  type: "message.delta",
  item_id: "m-1",
  turn_id: "t-1",
  call_id: "c-1",
  name: "Codex",
  kind: "message",
  text,
  ...extra,
});

test("A streamed reply builds one message from its deltas", () => {
  const room = { messages: [] };
  applyEvent(room, { type: "user.utterance", text: "Hi", turn_id: "t-1", call_id: "c-1" });
  applyEvent(room, delta("Hel"));
  applyEvent(room, delta("lo."));
  assert.deepEqual(
    room.messages.map((message) => [message.role, message.text, message.name]),
    [["user", "Hi", undefined], ["agent", "Hello.", "Codex"]],
  );
});

test("The done event sets the final text", () => {
  const room = { messages: [] };
  applyEvent(room, delta("Hel"));
  applyEvent(room, { ...delta("Hello there."), type: "message.done", kind: "final_answer" });
  assert.equal(room.messages.length, 1);
  assert.equal(room.messages[0].text, "Hello there.");
  assert.equal(room.messages[0].kind, "final_answer");
});

test("A greeting and a new call change the transcript", () => {
  const room = { messages: [{ role: "user", text: "old" }] };
  assert.equal(applyEvent(room, { type: "call.started" }), true);
  assert.deepEqual(room.messages, []);
  applyEvent(room, { type: "agent.greeting", item_id: "g-1", text: "Hey.", name: "Codex", kind: "greeting" });
  assert.equal(room.messages[0].text, "Hey.");
  assert.equal(applyEvent(room, { type: "agent.audio", audio_id: "a" }), false);
});

test("The transcript keeps as many messages as the room", () => {
  const room = { messages: [] };
  for (let index = 0; index < 205; index++)
    applyEvent(room, { type: "user.utterance", text: String(index) });
  assert.equal(room.messages.length, 200);
  assert.equal(room.messages[0].text, "5");
});
