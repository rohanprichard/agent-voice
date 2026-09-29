import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

import {
  agentLabel,
  callMeta,
  formatDuration,
  outcomeLabel,
  relativeTime,
} from "../src/talktome/static/calls-view.js";

const require = createRequire(import.meta.url);
const { newMissed, recentCallers, trayBadge } = require("../desktop/calls.cjs");

const now = Date.parse("2026-09-29T12:00:00Z");
const ago = (seconds) => new Date(now - seconds * 1000).toISOString();

test("A duration reads as minutes and seconds", () => {
  assert.equal(formatDuration(0), "0:00");
  assert.equal(formatDuration(151), "2:31");
  assert.equal(formatDuration(3725), "1:02:05");
  assert.equal(formatDuration(null), "");
});

test("A time reads relative to now", () => {
  assert.equal(relativeTime(ago(10), now), "Just now");
  assert.equal(relativeTime(ago(300), now), "5 min ago");
  assert.equal(relativeTime(ago(7200), now), "2 hr ago");
  assert.equal(relativeTime(ago(90000), now), "Yesterday");
  assert.equal(relativeTime(ago(3 * 86400), now), "3 days ago");
  assert.equal(relativeTime(ago(40 * 86400), now), "Aug 20");
  assert.equal(relativeTime("not a date", now), "");
});

test("The meta line leaves out the duration of a call nobody answered", () => {
  const missed = { agent: "codex", started_at: ago(300), outcome: "missed", duration: null };
  assert.deepEqual(callMeta(missed, now), ["Codex", "5 min ago", "Missed"]);
  const answered = { agent: "claude", started_at: ago(300), outcome: "answered", duration: 65 };
  assert.deepEqual(callMeta(answered, now), ["Claude Code", "5 min ago", "1:05", "Answered"]);
});

test("A call the user placed says so", () => {
  assert.equal(outcomeLabel({ outcome: "answered", callback: true }), "You called");
  assert.equal(outcomeLabel({ outcome: null }), "Ringing");
  assert.equal(agentLabel("unknown"), "Agent");
});

test("The recent menu has one entry for each session", () => {
  const calls = [
    { id: "1", agent: "codex", session_id: "a" },
    { id: "2", agent: "codex", session_id: "a" },
    { id: "3", agent: "claude", session_id: "a" },
    { id: "4", agent: "codex", session_id: "b" },
  ];
  assert.deepEqual(recentCallers(calls).map((call) => call.id), ["1", "3", "4"]);
  assert.equal(recentCallers(calls, 2).length, 2);
});

test("Only missed calls not seen before count", () => {
  const calls = [
    { id: "1", outcome: "missed" },
    { id: "2", outcome: "answered" },
    { id: "3", outcome: "missed" },
    { id: "4", outcome: null },
  ];
  assert.deepEqual(newMissed(calls, new Set(["1"])).map((call) => call.id), ["3"]);
  assert.equal(trayBadge(0), "");
  assert.equal(trayBadge(2), " 2");
});
