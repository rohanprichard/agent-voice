import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { SpeechDetector } from "./detector";

function fixture(body: string): string {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "talktome-detector-"));
  const script = path.join(folder, "detector.py");
  fs.writeFileSync(script, body);
  return script;
}

test("the detector matches concurrent requests and rejects requests after close", async () => {
  const script = fixture(`import json, sys
print('{"ready": true}', flush=True)
for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"id": request["id"], "probability": request["id"] / 10}), flush=True)
`);
  const detector = new SpeechDetector(script, "unused");
  try {
    const results = await Promise.all([detector.request("turn"), detector.request("turn")]);
    assert.deepEqual(results.map((value) => value.probability), [0.1, 0.2]);
    detector.close();
    await assert.rejects(detector.request("vad"), /stopped/);
  } finally { detector.close(); }
});

test("worker exit rejects requests instead of leaving the call waiting", async () => {
  const script = fixture(`import sys
print('{"ready": true}', flush=True)
sys.stdin.readline()
`);
  const detector = new SpeechDetector(script, "unused");
  try { await assert.rejects(detector.request("turn"), /stopped/); }
  finally { detector.close(); }
});
