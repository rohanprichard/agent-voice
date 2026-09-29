// The signature TalkToMe motif: two threads sharing one conversational space.
//
// These are deliberately not a waveform. A waveform is a row of spikes, which is
// what every voice interface already looks like. Two continuous lines that drift
// apart and cross read as two participants in a conversation instead.
//
// Everything here is pure so the motion can be tested without a canvas.

export const THREADS = {
  user: { color: "#d7ff35", phaseRate: 1, direction: 1, resting: 0.24 },
  agent: { color: "#ff4fd8", phaseRate: 0.9, direction: -1, resting: 0.24 },
};

// The phase changes slowly, even when a person speaks.
export const PHASE_BASE = 0.00075;

/**
 * How much of full speed a silent thread keeps.
 *
 * A thread that stops dead when someone stops talking looks like a frozen
 * display. It should slow down and carry on, not halt.
 */
export const IDLE_SPEED = 0.4;

/** How much faster a thread travels while its own side is speaking. */
export const SPEECH_SPEED = 0.9;

/**
 * The range the phase is kept in.
 *
 * The phase stays small during a long call. The curve repeats at this value.
 */
export const PHASE_SPAN = Math.PI * 200;

// The curve has room to move inside the canvas.
export const SWING = 0.22;

// A quiet thread still breathes, so the interface never looks dead or frozen.
export const RESTING_OPACITY = 0.35;
export const ACTIVE_OPACITY = 1;
// Deliberately below the resting value: the thread that is not speaking recedes
// past where it sits when nobody is, which is what makes the speaker read as
// the one holding the conversation. It stays clearly visible either way.
export const QUIET_OPACITY = 0.25;

// Speech starts quickly and fades gently. Reversing these makes the line feel
// twitchy on onset and abrupt on release.
export const ATTACK = 0.18;
export const RELEASE = 0.06;

/**
 * Edges return to the centre line so the thread looks placed rather than cut off.
 * Without this the wave starts mid-swing at both ends and looks unfinished.
 *
 * The endpoints are exact. `Math.sin(Math.PI)` is 1.2e-16 rather than 0, which
 * would leave the first and last pixel a hair off the centre line.
 */
export function envelope(normalizedX) {
  const nx = clamp01(normalizedX);
  if (nx === 0 || nx === 1) return 0;
  return Math.sin(nx * Math.PI);
}

function clamp01(value) {
  return Math.min(Math.max(value, 0), 1);
}

/** Draw three smooth bends with a small change in their spacing. */
export function wave(normalizedX, phase) {
  return (
    Math.sin(normalizedX * Math.PI * 3 + phase) +
    0.14 * Math.sin(normalizedX * Math.PI * 2 + phase * 0.5)
  );
}

/**
 * How far, in pixels, a thread moves from the centre line at full amplitude.
 *
 * Amplitude is a fraction rather than a pixel count so the same numbers hold on
 * the call surface and in a test, and so a taller canvas scales the motion with
 * it instead of flattening it. Getting this wrong is what left the first version
 * of the threads looking like two straight lines.
 */
export function swingPixels(amplitude, height) {
  return Math.max(0, amplitude) * height * SWING;
}

/**
 * How far a thread's phase advances this frame.
 *
 * Speed follows activity, so a thread moves quickly while its side is talking and
 * drifts when it is not. Amplitude alone was not enough: a line that swells but
 * keeps the same pace still looks like a display rather than a voice.
 */
export function phaseStep(kind, activity, delta) {
  const thread = THREADS[kind];
  const speed = IDLE_SPEED + SPEECH_SPEED * clamp01(activity);
  return delta * PHASE_BASE * thread.phaseRate * thread.direction * speed;
}

/**
 * Advance a phase, wrapping it to keep precision over a long call.
 *
 * The wrap is seamless: the sine components repeat over this span, and they are
 * what the phase is used for, so nothing jumps when it happens.
 */
export function advancePhase(phase, kind, activity, delta) {
  const next = (phase + phaseStep(kind, activity, delta)) % PHASE_SPAN;
  return next < 0 ? next + PHASE_SPAN : next;
}

/** The vertical position of a thread at a point across the canvas. */
export function threadY(normalizedX, phase, amplitude, height, offset = 0) {
  return (
    height / 2 +
    offset +
    wave(normalizedX, phase) * swingPixels(amplitude, height) * envelope(normalizedX)
  );
}

/**
 * Move a level toward its target, faster to rise than to fall.
 *
 * Raw audio levels move far too quickly to draw: the line would flicker. This is
 * what makes speech arriving look like a breath rather than a jolt.
 */
export function approach(current, target, attack = ATTACK, release = RELEASE) {
  const speed = target > current ? attack : release;
  return current + (target - current) * speed;
}

/** Fade a thread's opacity between prominent and secondary without a jump. */
export function fade(current, target, step = 0.16) {
  return approach(current, target, step, step);
}

/**
 * The amplitude to draw from how active a side of the conversation is.
 *
 * A thread at full activity must not simply sit at a larger size, which reads as a
 * bigger static line rather than as a voice. It keeps moving inside its range, so
 * the swell is what carries the energy and the variation keeps it alive.
 *
 * The resting motion stays small enough that it never suggests speech.
 */
export function amplitudeFor(activity, phase, resting) {
  const breath = resting * (0.6 + 0.4 * Math.sin(phase * 0.55));
  const swell = 0.8 + 0.2 * Math.sin(phase * 0.85 + 1.1);
  return Math.max(clamp01(activity) * swell, breath);
}

/** One thread's drawing parameters for this frame. */
export function threadFrame({ kind, level, opacity, phase, width, height, offset = 0 }) {
  const thread = THREADS[kind];
  return {
    color: thread.color,
    amplitude: amplitudeFor(level, phase, thread.resting),
    opacity,
    phase,
    width,
    height,
    offset,
  };
}

/** How much of each end of a thread dissolves. */
export const FADE = 0.16;

/** A colour with its own alpha, for the gradient stops. */
export function withAlpha(hex, alpha) {
  const value = Number.parseInt(hex.replace("#", ""), 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Fade a thread out at both ends.
 *
 * The envelope already draws the threads to the centre line at the edges, but
 * they still stopped there, and two rounded caps meeting at the same point with a
 * glow on them read as a deliberate end to the line. Dissolving removes the
 * terminus entirely, so the thread looks like it passes through.
 */
export function threadGradient(ctx, color, width) {
  const gradient = ctx.createLinearGradient(0, 0, width, 0);
  gradient.addColorStop(0, withAlpha(color, 0));
  gradient.addColorStop(FADE, withAlpha(color, 1));
  gradient.addColorStop(1 - FADE, withAlpha(color, 1));
  gradient.addColorStop(1, withAlpha(color, 0));
  return gradient;
}

/**
 * Stroke a thread twice: a wide soft pass for the glow, then a crisp line.
 *
 * A single pass with a large shadow blur reads as neon haze, which is the look
 * this is deliberately avoiding. Coordinates are logical pixels, which is what
 * the context was scaled to, so the loop runs to the logical width rather than
 * the device width of the backing store.
 */
export function drawThread(ctx, { color, amplitude, opacity, phase, width, height, offset }) {
  ctx.save();
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const pass of [
    { width: 4, alpha: 0.12, blur: 8 },
    { width: 1.5, alpha: 1, blur: 5 },
  ]) {
    ctx.beginPath();
    for (let x = 0; x <= width; x += 1) {
      const y = threadY(x / width, phase, amplitude, height, offset);
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.globalAlpha = opacity * pass.alpha;
    ctx.lineWidth = pass.width;
    ctx.shadowColor = color;
    ctx.shadowBlur = pass.blur;
    ctx.strokeStyle = threadGradient(ctx, color, width);
    ctx.stroke();
  }
  ctx.restore();
}

/**
 * Size the canvas for the display and return a context scaled to CSS pixels.
 *
 * Without this the threads render at half resolution on a Retina display and the
 * thin lines look soft.
 */
export function fitCanvas(canvas, ratio) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width: rect.width, height: rect.height };
}
