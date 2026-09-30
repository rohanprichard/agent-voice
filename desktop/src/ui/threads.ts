// The talktome motif: two threads that share one space, one for you and one
// for the agent. They are not a waveform. Two lines that drift apart and cross
// read as two people in a conversation. The speaker's thread swells and leads,
// and the other recedes. A plain script, loaded before pill.js.

const Threads = (() => {
  const motion = {
    user: { phaseRate: 1, direction: 1, resting: 0.24 },
    agent: { phaseRate: 0.9, direction: -1, resting: 0.24 },
  };
  const PHASE_BASE = 0.00075;
  const IDLE_SPEED = 0.4; // a silent thread slows down but does not stop
  const SPEECH_SPEED = 0.9;
  const PHASE_SPAN = Math.PI * 200;
  const SWING = 0.22;
  const RESTING_OPACITY = 0.35;
  const ACTIVE_OPACITY = 1;
  const QUIET_OPACITY = 0.25; // below resting, so the speaker reads as the one holding the call
  const ATTACK = 0.18; // speech starts quickly and fades gently
  const RELEASE = 0.06;
  const FADE = 0.16;

  type Kind = "user" | "agent";

  const clamp01 = (value: number) => Math.min(Math.max(value, 0), 1);
  const approach = (current: number, target: number, attack = ATTACK, release = RELEASE) =>
    current + (target - current) * (target > current ? attack : release);
  const envelope = (nx: number) => (nx <= 0 || nx >= 1 ? 0 : Math.sin(nx * Math.PI));
  const wave = (nx: number, phase: number) => Math.sin(nx * Math.PI * 3 + phase) + 0.14 * Math.sin(nx * Math.PI * 2 + phase * 0.5);
  const amplitudeFor = (activity: number, phase: number, resting: number) =>
    Math.max(clamp01(activity) * (0.8 + 0.2 * Math.sin(phase * 0.85 + 1.1)), resting * (0.6 + 0.4 * Math.sin(phase * 0.55)));

  function rgb(color: string): string {
    const probe = document.createElement("span");
    probe.style.color = color;
    document.body.append(probe);
    const value = getComputedStyle(probe).color.match(/\d+(\.\d+)?/g)?.slice(0, 3).join(",") ?? "128,128,128";
    probe.remove();
    return value;
  }

  // start draws on the canvas until stop(). active() says who speaks now.
  function start(canvas: HTMLCanvasElement, active: () => { user: boolean; agent: boolean }): () => void {
    const energy = { user: 0, agent: 0 };
    const opacity = { user: RESTING_OPACITY, agent: RESTING_OPACITY };
    const phase = { user: 0.4, agent: 2.1 };
    const styles = getComputedStyle(document.documentElement);
    const colors = { user: rgb(styles.getPropertyValue("--foreground")), agent: rgb(styles.getPropertyValue("--muted-foreground")) };
    let last = performance.now();
    let frame = 0;

    const draw = (now: number) => {
      const delta = Math.min(now - last, 64);
      last = now;
      const on = active();
      for (const kind of ["user", "agent"] as Kind[]) energy[kind] = approach(energy[kind], on[kind] ? 1 : 0);
      const user = energy.user > 0.5;
      const agent = energy.agent > 0.5;
      const speaker = user && agent ? "both" : user ? "user" : agent ? "agent" : "none";

      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;
      if (canvas.width !== Math.round(width * ratio)) canvas.width = Math.round(width * ratio);
      if (canvas.height !== Math.round(height * ratio)) canvas.height = Math.round(height * ratio);
      const ctx = canvas.getContext("2d")!;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);

      for (const kind of ["user", "agent"] as Kind[]) {
        const target = speaker === "both" || speaker === kind ? ACTIVE_OPACITY : speaker === "none" ? RESTING_OPACITY : QUIET_OPACITY;
        opacity[kind] = approach(opacity[kind], target, FADE, FADE);
        const m = motion[kind];
        const step = delta * PHASE_BASE * m.phaseRate * m.direction * (IDLE_SPEED + SPEECH_SPEED * clamp01(energy[kind]));
        phase[kind] = (((phase[kind] + step) % PHASE_SPAN) + PHASE_SPAN) % PHASE_SPAN;

        const amplitude = amplitudeFor(energy[kind], phase[kind], m.resting);
        const offset = kind === "user" ? -1.5 : 1.5;
        const gradient = ctx.createLinearGradient(0, 0, width, 0);
        gradient.addColorStop(0, `rgba(${colors[kind]},0)`);
        gradient.addColorStop(FADE, `rgba(${colors[kind]},1)`);
        gradient.addColorStop(1 - FADE, `rgba(${colors[kind]},1)`);
        gradient.addColorStop(1, `rgba(${colors[kind]},0)`);
        ctx.save();
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        // A wide soft pass for the glow, then a crisp line.
        for (const pass of [{ width: 4, alpha: 0.12, blur: 8 }, { width: 1.5, alpha: 1, blur: 5 }]) {
          ctx.beginPath();
          for (let x = 0; x <= width; x += 1) {
            const nx = x / width;
            const y = height / 2 + offset + wave(nx, phase[kind]) * amplitude * height * SWING * envelope(nx);
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          }
          ctx.globalAlpha = opacity[kind] * pass.alpha;
          ctx.lineWidth = pass.width;
          ctx.shadowColor = `rgb(${colors[kind]})`;
          ctx.shadowBlur = pass.blur;
          ctx.strokeStyle = gradient;
          ctx.stroke();
        }
        ctx.restore();
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }

  return { start };
})();
