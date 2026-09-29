import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const source = readFileSync(
  fileURLToPath(new URL("../src/talktome/static/app.js", import.meta.url)),
  "utf8",
);

test("The interface never passes an already-prefixed path to the API helper", () => {
  // api() prepends "/v1". A call argument that already contains "/v1" produces
  // "/v1/v1/...", which misses every route and falls through to the static file
  // mount, so the server answers "405 Method Not Allowed" instead of running the
  // handler. That is a confusing failure, so reject the pattern outright.
  const offenders = [
    ...source.matchAll(/\b(?:api|post)\("(\/v1\/[^"]*)"/g),
  ].map((match) => match[1]);
  assert.deepEqual(offenders, [], `Remove the /v1 prefix from: ${offenders.join(", ")}`);
});

test("Only the interrupt control invalidates the current turn", () => {
  // The microphone reports speech onset for a single buffer of noise, and that
  // happens about a second after the user stops talking. Interrupting the turn
  // from that signal made the agent's reply come back as a stale-turn error for
  // a message the user never replaced, which reads as the app ignoring them.
  // A real new utterance replaces the turn on the server by itself.
  const interrupts = [...source.matchAll(/post\("\/call\/interrupt"/g)];
  assert.equal(
    interrupts.length,
    1,
    "Post /call/interrupt only from the interrupt control, never from microphone onset",
  );
});
