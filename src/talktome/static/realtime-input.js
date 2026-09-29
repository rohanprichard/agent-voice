// Send the current microphone stream to Scribe without sending the API key.
// The local server gives this window one token for each provider connection.

const RATES = new Set([8000, 16000, 22050, 24000, 44100, 48000]);
const CHUNK_SECONDS = 0.16;
const CONNECT_TIMEOUT_MS = 4000;
const COMMIT_CONNECT_WAIT_MS = 400;
const COMMIT_TIMEOUT_MS = 2500;
const HELD_AUDIO_SECONDS = 4;

export function supportsRealtimeRate(rate) {
  return RATES.has(rate);
}

function pcmBase64(samples) {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < samples.length; i++) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, value < 0 ? value * 32768 : value * 32767, true);
  }
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export class RealtimeInput {
  constructor({ callId, sampleRate, onPartial }) {
    this.callId = callId;
    this.sampleRate = sampleRate;
    this.onPartial = onPartial;
    this.abort = new AbortController();
    this.socket = null;
    this.connecting = null;
    this.pending = [];
    this.pendingOffset = 0;
    this.pendingSamples = 0;
    this.commitWait = null;
    this.heldAudio = [];
    this.heldSamples = 0;
    this.holdingAudio = false;
    this.resumedSpeech = false;
    this.earlyCommit = null;
    this.committedPrefix = "";
    this.partialText = "";
    this.failed = false;
    this.closed = false;
  }

  start() {
    if (this.failed || this.closed) return Promise.reject(new Error("Live input stopped."));
    if (this.socket?.readyState === WebSocket.OPEN) return Promise.resolve();
    if (!this.connecting) {
      this.connecting = this.connect().catch((error) => {
        this.fail(error);
        throw error;
      });
    }
    return this.connecting;
  }

  async connect() {
    const tokenTimer = setTimeout(() => this.abort.abort(), CONNECT_TIMEOUT_MS);
    let response;
    try {
      response = await fetch("/v1/stt/realtime-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ call_id: this.callId }),
        signal: this.abort.signal,
      });
    } finally {
      clearTimeout(tokenTimer);
    }
    if (!response.ok) throw new Error("Live speech input could not start.");
    const { token } = await response.json();
    if (typeof token !== "string" || !token) throw new Error("The speech token is invalid.");
    if (this.closed) throw new Error("Live speech input stopped.");

    const query = new URLSearchParams({
      model_id: "scribe_v2_realtime",
      audio_format: `pcm_${this.sampleRate}`,
      commit_strategy: "manual",
      token,
    });
    const socket = new WebSocket(
      `wss://api.elevenlabs.io/v1/speech-to-text/realtime?${query}`,
    );
    this.socket = socket;
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        socket.close();
        reject(new Error("Live speech input took too long to connect."));
      }, CONNECT_TIMEOUT_MS);
      socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("Live speech input could not connect."));
      }, { once: true });
      socket.addEventListener("close", () => {
        clearTimeout(timer);
        reject(new Error("Live speech input closed."));
      }, { once: true });
    });
    if (this.closed) {
      socket.close();
      throw new Error("Live speech input stopped.");
    }
    socket.addEventListener("message", (event) => this.receive(event.data));
    socket.addEventListener("close", () => {
      if (!this.closed) this.fail(new Error("Live speech input closed."));
    });
    socket.addEventListener("error", () => {
      if (!this.closed) this.fail(new Error("Live speech input failed."));
    });
    this.flush();
  }

  feed(chunk) {
    if (this.failed || this.closed) return;
    if (this.holdingAudio) {
      this.hold(chunk);
      return;
    }
    this.pending.push(chunk);
    this.pendingSamples += chunk.length;
    if (this.socket?.readyState === WebSocket.OPEN) this.flush();
    else void this.start().catch(() => {});
  }

  hold(chunk) {
    this.heldAudio.push(chunk);
    this.heldSamples += chunk.length;
    const limit = Math.round(this.sampleRate * HELD_AUDIO_SECONDS);
    if (this.heldSamples > limit)
      this.fail(new Error("The speech pause exceeded the live input buffer."));
  }

  releaseHeldAudio() {
    if (!this.heldSamples) return;
    this.pending.push(...this.heldAudio);
    this.pendingSamples += this.heldSamples;
    this.heldAudio = [];
    this.heldSamples = 0;
    if (this.socket?.readyState === WebSocket.OPEN) this.flush();
  }

  clearHeldAudio() {
    this.heldAudio = [];
    this.heldSamples = 0;
  }

  showPartial() {
    this.onPartial([this.committedPrefix, this.partialText].filter(Boolean).join(" "));
  }

  startUtterance() {
    this.holdingAudio = false;
    this.resumedSpeech = false;
    this.earlyCommit = null;
    this.committedPrefix = "";
    this.partialText = "";
    this.clearHeldAudio();
    this.showPartial();
  }

  resumeSpeech() {
    if (!this.earlyCommit || !this.holdingAudio) return;
    this.holdingAudio = false;
    this.resumedSpeech = true;
    this.releaseHeldAudio();
  }

  take(count) {
    const samples = new Float32Array(count);
    let offset = 0;
    while (offset < count) {
      const head = this.pending[0];
      const available = head.length - this.pendingOffset;
      const size = Math.min(available, count - offset);
      samples.set(head.subarray(this.pendingOffset, this.pendingOffset + size), offset);
      offset += size;
      this.pendingOffset += size;
      if (this.pendingOffset === head.length) {
        this.pending.shift();
        this.pendingOffset = 0;
      }
    }
    this.pendingSamples -= count;
    return samples;
  }

  send(samples, commit = false) {
    this.socket.send(JSON.stringify({
      message_type: "input_audio_chunk",
      audio_base_64: pcmBase64(samples),
      sample_rate: this.sampleRate,
      commit,
    }));
  }

  flush(commit = false) {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    const size = Math.round(this.sampleRate * CHUNK_SECONDS);
    try {
      while (this.pendingSamples >= size && (!commit || this.pendingSamples > size)) {
        this.send(this.take(size));
      }
      if (commit) {
        const count = this.pendingSamples;
        const samples = new Float32Array(Math.max(count, Math.round(this.sampleRate * 0.1)));
        if (count) samples.set(this.take(count));
        this.send(samples, true);
      }
    } catch (error) {
      this.fail(error);
    }
  }

  receive(raw) {
    let message;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }
    if (message.message_type === "partial_transcript") {
      this.partialText = typeof message.text === "string" ? message.text : "";
      this.showPartial();
    } else if (message.message_type === "committed_transcript") {
      if (!this.commitWait) {
        this.fail(new Error("Live input returned an unexpected transcript segment."));
        return;
      }
      this.partialText = "";
      this.commitWait?.resolve(typeof message.text === "string" ? message.text : "");
      this.commitWait = null;
    } else if (
      message.message_type === "error" ||
      message.message_type === "rate_limited" ||
      message.message_type === "auth_error"
    ) {
      this.fail(new Error("Live speech input failed."));
    }
  }

  async requestCommit() {
    let waitTimer;
    try {
      await Promise.race([
        this.start(),
        new Promise((_, reject) => {
          waitTimer = setTimeout(() => {
            const error = new Error("Live speech input took too long to connect.");
            this.fail(error);
            reject(error);
          }, COMMIT_CONNECT_WAIT_MS);
        }),
      ]);
    } finally {
      clearTimeout(waitTimer);
    }
    if (this.failed || this.closed) throw new Error("Live speech input stopped.");
    const result = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.fail(new Error("Live speech input took too long."));
      }, COMMIT_TIMEOUT_MS);
      this.commitWait = {
        resolve: (text) => { clearTimeout(timer); resolve(text); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      };
    });
    const commitSentMs = performance.timeOrigin + performance.now();
    this.flush(true);
    const text = await result;
    return {
      text,
      commitSentMs,
      committedMs: performance.timeOrigin + performance.now(),
    };
  }

  commitEarly() {
    if (this.earlyCommit) return this.earlyCommit;
    this.holdingAudio = true;
    this.earlyCommit = this.requestCommit().then((result) => {
      this.committedPrefix = result.text.trim();
      this.showPartial();
      return { ...result, text: this.committedPrefix };
    });
    return this.earlyCommit;
  }

  async commitFinal() {
    const early = this.earlyCommit;
    if (!early) {
      const result = await this.requestCommit();
      this.startUtterance();
      return { ...result, text: result.text.trim() };
    }
    if (!this.resumedSpeech) {
      this.clearHeldAudio();
      const result = await early;
      this.startUtterance();
      return result;
    }
    this.releaseHeldAudio();
    const prefix = await early;
    const result = await this.requestCommit();
    const text = [prefix.text, result.text.trim()].filter(Boolean).join(" ");
    this.startUtterance();
    return { ...result, text };
  }

  fail(error) {
    if (this.failed || this.closed) return;
    this.failed = true;
    this.abort.abort();
    this.commitWait?.reject(error);
    this.commitWait = null;
    this.pending = [];
    this.pendingSamples = 0;
    this.clearHeldAudio();
    this.committedPrefix = "";
    this.partialText = "";
    this.showPartial();
    this.socket?.close();
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.abort.abort();
    this.commitWait?.reject(new Error("Live speech input stopped."));
    this.commitWait = null;
    this.pending = [];
    this.pendingSamples = 0;
    this.clearHeldAudio();
    this.committedPrefix = "";
    this.partialText = "";
    this.showPartial();
    this.socket?.close();
  }
}
