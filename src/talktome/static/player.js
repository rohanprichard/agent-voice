// Play the agent's speech through Web Audio.
//
// This used to build an <audio> element per chunk. Two things were wrong with
// that. There was no way to measure the agent's level, which the call surface
// needs for its pink thread, and every chunk rebuilt a media pipeline, which left
// an audible seam between them.
//
// Scheduling decoded buffers on the audio clock fixes both. The analyser sits in
// the path so the surface sees exactly what is being heard, and each chunk is
// scheduled to start where the previous one ends instead of whenever the queue
// happened to get to it.

/**
 * How long before a chunk ends to hand control back to the queue.
 *
 * The queue awaits each chunk before it starts the next one. If a chunk resolved
 * only when it finished, the next one would be scheduled from "now" and always
 * land slightly late. Resolving a little early lets the next chunk be placed at
 * the exact end of this one, so the audio is continuous rather than merely close.
 */
const HANDOFF = 0.12;
const START_LEAD = 0.08;

/** Speech sits well below full scale, so the raw level needs lifting to be seen. */
const LEVEL_GAIN = 8;

const MAX_CACHED = 12;

export class WebAudioPlayer {
  constructor({ onError, onIdle } = {}) {
    this.onError = onError;
    this.onIdle = onIdle;
    this.context = null;
    this.buffers = new Map();
    this.sources = new Set();
    // Resolvers for chunks still waiting on their handoff, so cancelling lands
    // immediately instead of leaving a timer to fire into the next turn.
    this.pending = new Set();
    this.audibleWatches = new Set();
    this.resumeWaiters = new Set();
    this.nextStart = 0;
    this.generation = 0;
    this.deliberatelyPaused = false;
    this.playbackEvents = [];
    this.analyser = null;
    this.input = null;
    this.samples = null;
  }

  /**
   * Create the audio graph on first use.
   *
   * An AudioContext may only be resumed after the user has interacted with the
   * page, and playback only ever follows a call the user started, so this waits
   * until then rather than constructing one at load.
   */
  ensure() {
    if (this.context) return this.context;
    this.context = new AudioContext();
    this.input = this.context.createGain();
    this.analyser = this.context.createAnalyser();
    // A short window: the level drives a moving line and nothing else, so it
    // should follow speech rather than average it away.
    this.analyser.fftSize = 1024;
    this.samples = new Float32Array(this.analyser.fftSize);
    this.input.connect(this.analyser);
    this.analyser.connect(this.context.destination);
    return this.context;
  }

  async decode(url) {
    if (this.buffers.has(url)) return this.buffers.get(url);
    const response = await fetch(url);
    if (!response.ok) throw new Error("The reply audio could not be fetched.");
    const buffer = await this.ensure().decodeAudioData(await response.arrayBuffer());
    this.buffers.set(url, buffer);
    // Chunks are never replayed and each has a unique id, so this only exists to
    // stop the map growing without limit during a long call.
    while (this.buffers.size > MAX_CACHED) {
      const oldest = this.buffers.keys().next().value;
      this.buffers.delete(oldest);
    }
    return buffer;
  }

  /**
   * Play audio the caller already holds.
   *
   * Deliberately not routed through an object URL. The content security policy
   * allows `blob:` for media but not for `connect-src`, so fetching a blob URL
   * fails outright; handing the bytes straight to the decoder avoids weakening
   * the policy for the sake of a voice preview.
   */
  async playData(data, options = {}) {
    const generation = this.generation;
    const bytes = data instanceof Blob ? await data.arrayBuffer() : data;
    const buffer = await this.ensure().decodeAudioData(bytes);
    if (generation !== this.generation) return;
    return this.schedule(buffer, options, generation);
  }

  async play(url, options = {}) {
    const generation = this.generation;
    const buffer = await this.decode(url);
    if (generation !== this.generation) return;
    return this.schedule(buffer, options, generation);
  }

  async waitForOutput(generation) {
    while (generation === this.generation) {
      if (this.deliberatelyPaused) {
        await new Promise((resolve) => this.resumeWaiters.add(resolve));
        continue;
      }
      const context = this.ensure();
      if (context.state === "running") return true;
      await context.resume();
    }
    return false;
  }

  async schedule(buffer, { onAudible, onScheduled, event, audio_id: audioId, audioId: camelAudioId } = {}, generation = this.generation) {
    const context = this.ensure();
    do {
      if (!(await this.waitForOutput(generation))) return;
    } while (this.deliberatelyPaused && generation === this.generation);
    if (generation !== this.generation) return;

    const start = Math.max(
      context.currentTime + (this.sources.size ? 0 : START_LEAD),
      this.nextStart,
    );
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.input);
    source.start(start);
    onScheduled?.(performance.timeOrigin + performance.now());
    this.nextStart = start + buffer.duration;
    this.sources.add(source);
    const eventId = event?.audio_id ?? audioId ?? camelAudioId;
    if (eventId != null) {
      this.playbackEvents.push({
        audio_id: eventId,
        start,
        end: start + buffer.duration,
      });
      while (this.playbackEvents.length > 128) this.playbackEvents.shift();
    }

    let watch = null;
    const stopWatch = () => {
      if (watch) clearInterval(watch);
      watch = null;
      this.audibleWatches.delete(stopWatch);
    };
    if (onAudible) {
      watch = setInterval(() => {
        if (context.currentTime < start || this.level() < 0.04) return;
        stopWatch();
        onAudible(performance.timeOrigin + performance.now());
      }, 10);
      this.audibleWatches.add(stopWatch);
    }

    await new Promise((resolve) => {
      const done = () => {
        clearTimeout(timer);
        this.pending.delete(done);
        resolve();
      };
      // Hand back before the sound ends so the next chunk can be placed exactly
      // where this one stops.
      const timer = setTimeout(
        done,
        Math.max(0, start + buffer.duration - context.currentTime - HANDOFF) * 1000,
      );
      this.pending.add(done);
      source.onended = () => {
        stopWatch();
        this.sources.delete(source);
        done();
        if (!this.sources.size) this.onIdle?.();
      };
    });
  }

  /** The current output level, the same measurement the microphone reports. */
  level() {
    if (!this.analyser) return 0;
    this.analyser.getFloatTimeDomainData(this.samples);
    let sum = 0;
    for (const sample of this.samples) sum += sample * sample;
    const rms = Math.sqrt(sum / this.samples.length);
    return Math.min(rms * LEVEL_GAIN, 1);
  }

  outputTime() {
    if (!this.context) return 0;
    const latency = Number.isFinite(this.context.outputLatency)
      ? this.context.outputLatency
      : Number.isFinite(this.context.baseLatency)
        ? this.context.baseLatency
        : 0;
    return Math.max(0, this.context.currentTime - latency);
  }

  playbackSnapshot() {
    const heardAt = this.outputTime();
    return this.playbackEvents.slice(-128).map((event) => {
      const played = Math.max(0, Math.min(event.end - event.start, heardAt - event.start));
      return {
        audio_id: event.audio_id,
        played_ms: Math.floor(played * 1000),
        completed: heardAt >= event.end,
      };
    });
  }

  pause() {
    this.deliberatelyPaused = true;
    return this.context?.suspend() ?? Promise.resolve();
  }

  resume() {
    this.deliberatelyPaused = false;
    for (const resolve of this.resumeWaiters) resolve();
    this.resumeWaiters.clear();
    return this.context?.resume() ?? Promise.resolve();
  }

  /** Stop everything scheduled and drop the timeline. */
  cancel() {
    const snapshot = this.playbackSnapshot();
    this.generation++;
    this.deliberatelyPaused = false;
    for (const source of this.sources) {
      try {
        source.onended = null;
        source.stop();
      } catch {
        // Already stopped, or never started.
      }
    }
    this.sources.clear();
    // Release anyone waiting on a handoff. The queue checks its generation, so an
    // abandoned chunk resolving now is harmless and a dangling timer is not.
    for (const done of [...this.pending]) done();
    for (const stopWatch of [...this.audibleWatches]) stopWatch();
    for (const resolve of this.resumeWaiters) resolve();
    this.resumeWaiters.clear();
    this.nextStart = 0;
    this.playbackEvents = [];
    return snapshot;
  }

  /** Whether any audio is scheduled or sounding. */
  get playing() {
    return this.sources.size > 0;
  }
}
