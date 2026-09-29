import assert from "node:assert/strict";
import test from "node:test";

import {
  ACTIVE_OPACITY,
  ATTACK,
  PHASE_SPAN,
  QUIET_OPACITY,
  RELEASE,
  RESTING_OPACITY,
  THREADS,
  advancePhase,
  amplitudeFor,
  approach,
  envelope,
  fade,
  phaseStep,
  swingPixels,
  threadFrame,
  threadGradient,
  threadY,
  wave,
  withAlpha,
} from "../src/talktome/static/threads.js";

const HEIGHT = 56;

test("A thread meets the centre line at both edges", () => {
  // The edges have to be calm, or the line looks cut off rather than placed.
  assert.equal(envelope(0), 0);
  assert.equal(envelope(1), 0);
  assert.equal(envelope(0.5), 1);
});

test("A thread is flat at its edges whatever its amplitude", () => {
  for (const amplitude of [0, 0.03, 1]) {
    assert.equal(threadY(0, 1.7, amplitude, HEIGHT), HEIGHT / 2);
    assert.equal(threadY(1, 1.7, amplitude, HEIGHT), HEIGHT / 2);
  }
});

test("The two threads use the two signature colours and no others", () => {
  assert.equal(THREADS.user.color, "#d7ff35");
  assert.equal(THREADS.agent.color, "#ff4fd8");
  assert.notEqual(THREADS.user.color, THREADS.agent.color);
});

test("The threads drift out of step so the motion never looks mechanical", () => {
  const user = wave(0.37, 1.2);
  const agent = wave(0.37, 1.2 * THREADS.agent.phaseRate);
  assert.notEqual(user, agent);
});

test("Speech rises faster than it falls", () => {
  // The asymmetry is the whole point: a fast attack reads as speech starting,
  // a slow release reads as it trailing off.
  assert.ok(ATTACK > RELEASE);
  const rising = approach(0, 1);
  const falling = 1 - approach(1, 0);
  assert.ok(rising > falling, `${rising} should exceed ${falling}`);
});

test("A level approaches its target without overshooting it", () => {
  let level = 0;
  for (let step = 0; step < 200; step++) level = approach(level, 0.8);
  assert.ok(level <= 0.8);
  assert.ok(level > 0.79);
});

test("A silent thread still breathes, but only a little", () => {
  // Measured in pixels, because that is what the user sees. Idle motion has to
  // be present enough to look alive and small enough never to read as speech.
  const still = amplitudeFor(0, 0, THREADS.user.resting);
  const pixels = swingPixels(still, HEIGHT);
  assert.ok(pixels > 0.3, `idle swing ${pixels}px is invisible`);
  assert.ok(pixels < 3, `idle swing ${pixels}px is large enough to suggest speech`);
});

test("A quiet thread recedes but never hides", () => {
  // While the other thread speaks, this one drops below its idle level so the
  // speaker reads as the one holding the conversation, but stays visible.
  assert.ok(QUIET_OPACITY < RESTING_OPACITY);
  assert.ok(QUIET_OPACITY > 0.15);
  assert.ok(RESTING_OPACITY < ACTIVE_OPACITY);
});

test("Opacity fades rather than switching", () => {
  const stepped = fade(RESTING_OPACITY, ACTIVE_OPACITY);
  assert.ok(stepped > RESTING_OPACITY && stepped < ACTIVE_OPACITY);
});

test("The two threads sit on opposite sides of the centre line", () => {
  const user = threadFrame({ kind: "user", level: 0, opacity: 1, phase: 0, width: 400, height: HEIGHT });
  const agent = threadFrame({ kind: "agent", level: 0, opacity: 1, phase: 0, width: 400, height: HEIGHT });
  assert.equal(user.offset, 0);
  assert.equal(agent.offset, 0);
  // Both know their own colour and rest independently.
  assert.equal(user.color, THREADS.user.color);
  assert.equal(agent.color, THREADS.agent.color);
});

test("A louder level makes a taller thread", () => {
  const quiet = threadFrame({ kind: "user", level: 0.05, opacity: 1, phase: 0, width: 400, height: HEIGHT });
  const loud = threadFrame({ kind: "user", level: 0.9, opacity: 1, phase: 0, width: 400, height: HEIGHT });
  assert.ok(loud.amplitude > quiet.amplitude);
});

test("A loud thread would actually move a visible distance", () => {
  // The first version of this drew two almost straight lines, because the
  // amplitude was applied as a pixel count rather than as a share of the canvas.
  const loud = swingPixels(1, HEIGHT);
  assert.ok(loud > 8, `full-speech swing ${loud}px is too flat to read as speech`);
  assert.ok(loud < HEIGHT / 2, `full-speech swing ${loud}px would leave the canvas`);
});

test("The thread and its glow stay inside the canvas at every phase", () => {
  // The sine components peak together near 1.52 and the glow pass is 5px wide,
  // so the worst case over a full cycle has to still fit.
  const half = swingPixels(1, HEIGHT) * 1.52;
  const glow = 2.5;
  assert.ok(HEIGHT / 2 - half - glow > 0, `the top of the thread is clipped`);
  for (let phase = 0; phase < Math.PI * 2; phase += 0.05) {
    for (let x = 0; x <= 1; x += 0.02) {
      const y = threadY(x, phase, 1, HEIGHT, 3);
      assert.ok(y - glow >= -0.5 && y + glow <= HEIGHT + 0.5, `y ${y} escaped at phase ${phase}`);
    }
  }
});

test("A thread keeps moving inside its range while it is active", () => {
  // A thread that simply sits at a larger size reads as a bigger static line
  // rather than as a voice, so the swell has to vary across the cycle.
  const samples = [];
  for (let phase = 0; phase < Math.PI * 4; phase += 0.1) {
    samples.push(amplitudeFor(1, phase, THREADS.user.resting));
  }
  const low = Math.min(...samples);
  const high = Math.max(...samples);
  assert.ok(low > 0.6, `the quietest part of a speaking thread was ${low}, too small to read`);
  assert.ok(high - low > 0.15, `the swell only varied by ${(high - low).toFixed(3)}`);
  assert.ok(high <= 1, `the swell reached ${high}, which would overflow the canvas`);
});

test("An idle thread is calm but not flat", () => {
  // It has to move, or the surface looks frozen; it must stay well under the size
  // it reaches while speaking, or the two states look alike.
  const idle = [];
  for (let phase = 0; phase < Math.PI * 4; phase += 0.1) {
    idle.push(amplitudeFor(0, phase, THREADS.user.resting));
  }
  const loudest = Math.max(...idle);
  const quietest = Math.min(...idle);
  const swing = swingPixels(loudest, HEIGHT);
  assert.ok(swing > 1.5, `an idle swing of ${swing}px is invisible`);
  assert.ok(loudest < 0.3, `an idle thread reached ${loudest}, which would suggest speech`);
  assert.ok(quietest < loudest, "an idle thread should swell and settle, not sit still");
});

test("Speaking is clearly larger than resting", () => {
  const resting = Math.max(
    ...Array.from({ length: 40 }, (_, i) => amplitudeFor(0, i * 0.3, THREADS.user.resting)),
  );
  const speaking = Math.max(
    ...Array.from({ length: 40 }, (_, i) => amplitudeFor(1, i * 0.3, THREADS.user.resting)),
  );
  assert.ok(speaking > resting * 2.5, `${resting.toFixed(2)} to ${speaking.toFixed(2)} is too close`);
});

test("A thread travels faster while its own side is speaking", () => {
  // Amplitude alone was not enough: a line that swells but keeps the same pace
  // still reads as a display rather than a voice.
  const idle = Math.abs(phaseStep("user", 0, 16));
  const mid = Math.abs(phaseStep("user", 0.5, 16));
  const loud = Math.abs(phaseStep("user", 1, 16));
  assert.ok(idle > 0, "a silent thread should still drift, not freeze");
  assert.ok(mid > idle && loud > mid, `${idle} -> ${mid} -> ${loud} should keep rising`);
  assert.ok(loud > idle * 2, "speaking should be clearly quicker, not marginally");
});

test("The two threads travel in opposite directions", () => {
  // Two threads running the same way at different speeds still read as one
  // animation; running against each other is what reads as two participants.
  assert.ok(phaseStep("user", 0.8, 16) > 0);
  assert.ok(phaseStep("agent", 0.8, 16) < 0);
  assert.equal(Math.sign(THREADS.user.direction), -Math.sign(THREADS.agent.direction));
});

test("A thread answers its own speaker, not the other one", () => {
  assert.notEqual(
    Math.abs(phaseStep("user", 0, 16)),
    Math.abs(phaseStep("user", 1, 16)),
  );
  // The agent's own level drives the agent's step; the user's level is not read.
  assert.equal(phaseStep("agent", 0.3, 16), phaseStep("agent", 0.3, 16));
});

test("A phase never grows without bound over a long call", () => {
  let phase = 0;
  for (let frame = 0; frame < 200000; frame++) {
    phase = advancePhase(phase, "user", 1, 16);
    assert.ok(phase >= 0 && phase < PHASE_SPAN, `phase ${phase} escaped the span`);
  }
});

test("Wrapping the phase does not make the thread jump", () => {
  // The wrap is only invisible because the span is a whole number of periods for
  // every sine component, so this pins that relationship rather than the number.
  for (const ratio of [1, 0.72, 0.3]) {
    const periods = (PHASE_SPAN * ratio) / (Math.PI * 2);
    assert.ok(
      Math.abs(periods - Math.round(periods)) < 1e-9,
      `the span is ${periods} periods at ${ratio}, which would jump on wrap`,
    );
  }
  for (const x of [0, 0.25, 0.5, 0.83, 1]) {
    assert.ok(Math.abs(wave(x, 0.7) - wave(x, 0.7 + PHASE_SPAN)) < 1e-9);
  }
});

test("A thread dissolves at both ends instead of stopping", () => {
  // The envelope brings both threads to the centre line at the edges, so they met
  // at the same point with rounded caps and a glow, which read as a deliberate end.
  const stops = [];
  const ctx = {
    createLinearGradient: () => ({ addColorStop: (at, color) => stops.push([at, color]) }),
  };
  threadGradient(ctx, "#d7ff35", 400);
  assert.equal(stops.length, 4);
  assert.equal(stops[0][0], 0);
  assert.equal(stops.at(-1)[0], 1);
  assert.ok(stops[0][1].endsWith(", 0)"), `the first stop is ${stops[0][1]}, not transparent`);
  assert.ok(stops.at(-1)[1].endsWith(", 0)"), `the last stop is ${stops.at(-1)[1]}, not transparent`);
  assert.ok(stops[1][1].endsWith(", 1)") && stops[2][1].endsWith(", 1)"));
});

test("A colour keeps its own channels when it is given an alpha", () => {
  assert.equal(withAlpha("#d7ff35", 0.5), "rgba(215, 255, 53, 0.5)");
  assert.equal(withAlpha("#ff4fd8", 0), "rgba(255, 79, 216, 0)");
  assert.equal(withAlpha("#000000", 1), "rgba(0, 0, 0, 1)");
});
