import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { ALL_STEPS, resumeStep, setupSteps } from "../src/talktome/static/onboarding-steps.js";

const read = (relative) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8");

test("Setup skips the glow color step without the native notch", () => {
  assert.deepEqual(setupSteps(false), ["welcome", "microphone", "voice", "agent", "ready"]);
});

test("Setup keeps the glow color step with the native notch", () => {
  assert.deepEqual(setupSteps(true), ALL_STEPS);
  assert.equal(setupSteps(true).length, 6);
});

test("A saved step that this Mac does not show continues at the next step", () => {
  const steps = setupSteps(false);
  assert.equal(resumeStep("color", steps), "ready");
  assert.equal(resumeStep("agent", steps), "agent");
  assert.equal(resumeStep("nonsense", steps), "welcome");
  assert.equal(resumeStep("color", setupSteps(true)), "color");
});

test("The step count and the progress dots come from the steps this Mac shows", () => {
  const onboarding = read("../src/talktome/static/onboarding.js");
  assert.match(onboarding, /\$\("step-count"\)\.textContent = `\$\{index \+ 1\} \/ \$\{steps\.length\}`/);
  assert.match(onboarding, /\$\("progress"\)\.replaceChildren\(\.\.\.steps\.map/);
  assert.match(onboarding, /steps = setupSteps\(nativeNotch\);/);
});

test("No window sends a glow color without the native notch", () => {
  const onboarding = read("../src/talktome/static/onboarding.js");
  const app = read("../src/talktome/static/app.js");
  assert.match(onboarding, /if \(nativeNotch\) window\.talktomeSetup\?\.setGlowColor/);
  assert.match(app, /if \(nativeNotch\) window\.talktomeDesktop\?\.setGlowColor/);
  assert.equal([...onboarding.matchAll(/setGlowColor/g)].length, 1);
  assert.equal([...app.matchAll(/setGlowColor/g)].length, 1);
  // Settings hides the glow color and shows the pill position instead.
  assert.match(app, /\$\("glow-setting"\)\.hidden = !nativeNotch;/);
  assert.match(app, /\$\("pill-placement-setting"\)\.hidden = nativeNotch;/);
  assert.match(read("../src/talktome/static/index.html"), /<div id="glow-setting" hidden>/);
  assert.match(read("../desktop/onboarding-preload.cjs"), /info: \(\) => ipcRenderer\.invoke\("talktome:desktop-info"\)/);
});

test("The notch helper stops when the native surface cannot show", () => {
  const main = read("../desktop/main.cjs");
  const unavailable = main.match(/if \(message\.event === "unavailable"\) \{([\s\S]*?)\n {6}\}/);
  assert.ok(unavailable);
  assert.match(unavailable[1], /child\.kill\(\);/);
  const ready = main.match(/if \(message\.event === "ready"\) \{([\s\S]*?)\n {6}\}/);
  assert.ok(ready);
  assert.match(ready[1], /if \(!\(nativeGeometry\.notchDepth > 0\)\) \{\s*child\.kill\(\);/);
  // No helper starts when the measured display has no notch.
  assert.match(main, /nativeGeometry\.notchDepth <= 0\)\s*return;/);
  assert.match(main, /if \(notchGlow === child && !nativeNotch\) child\.kill\(\);/);
});
