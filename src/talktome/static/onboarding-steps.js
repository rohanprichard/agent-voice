export const ALL_STEPS = ["welcome", "microphone", "voice", "agent", "color", "ready"];

// The glow color is for the native notch surface. A Mac without it uses the
// normal pill, so setup skips that step.
export function setupSteps(nativeNotch) {
  return nativeNotch ? ALL_STEPS : ALL_STEPS.filter((step) => step !== "color");
}

// A saved step can be one that this Mac does not show. Continue at the step that
// comes after it.
export function resumeStep(saved, steps) {
  if (steps.includes(saved)) return saved;
  const index = ALL_STEPS.indexOf(saved);
  if (index < 0) return steps[0];
  return ALL_STEPS.slice(index + 1).find((step) => steps.includes(step)) || steps[0];
}
