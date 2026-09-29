export function wavBlob(chunks, sampleRate) {
  const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) =>
    [...text].forEach((char, i) =>
      view.setUint8(offset + i, char.charCodeAt(0)),
    );
  write(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const chunk of chunks)
    for (const sample of chunk) {
      const value = Math.max(-1, Math.min(1, sample));
      view.setInt16(offset, value < 0 ? value * 32768 : value * 32767, true);
      offset += 2;
    }
  return new Blob([buffer], { type: "audio/wav" });
}

export const PAUSE_SECONDS = {
  quick: 0.7,
  balanced: 0.9,
  patient: 1.8,
};

const SMART_PAUSE_SECONDS = { quick: 0.3, balanced: 0.45, patient: 0.7 };
const SMART_MAX_SILENCE = 3;

function recentChunks(chunks, sampleCount) {
  const result = [];
  for (let i = chunks.length - 1; i >= 0 && sampleCount > 0; i--) {
    const chunk = chunks[i];
    const size = Math.min(sampleCount, chunk.length);
    result.push(chunk.subarray(chunk.length - size));
    sampleCount -= size;
  }
  return result.reverse();
}

export class Microphone {
  constructor({ onAudio, onChunk, onDiscard, onRecording, onError, checkTurn, onTurnCheck, onSpeechResume, pauseMode = "balanced" }) {
    Object.assign(this, { onAudio, onChunk, onDiscard, onRecording, onError, checkTurn, onTurnCheck, onSpeechResume });
    this.pauseMode = Object.hasOwn(PAUSE_SECONDS, pauseMode) ? pauseMode : "balanced";
    this.muted = false;
    this.paused = false;
    this.assistantSpeaking = false;
    this.clear();
  }
  clear({ discard = true } = {}) {
    this.cancelTurnCheck();
    this.turnDecision = null;
    if (discard && this.recording) this.onDiscard?.();
    this.chunks = [];
    this.preRoll = [];
    this.duration = 0;
    this.silence = 0;
    this.voiced = 0;
    this.assistantVoiced = 0;
    this.lastVoiceMs = null;
    this.recording = false;
    this.onRecording(false);
  }
  async start(deviceId = "default") {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          ...(deviceId !== "default" ? { deviceId: { exact: deviceId } } : {}),
        },
        video: false,
      });
      this.context = new AudioContext();
      await this.context.resume();
      await this.context.audioWorklet.addModule("/audio-worklet.js");
      this.source = this.context.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.context, "talktome-capture");
      this.gain = this.context.createGain();
      this.gain.gain.value = 0;
      this.source
        .connect(this.node)
        .connect(this.gain)
        .connect(this.context.destination);
      this.node.port.onmessage = (event) => this.consume(event.data);
      this.stream.getAudioTracks()[0].addEventListener("ended", () => {
        this.stop();
        this.onError(
          "The microphone disconnected. Select a microphone, then enable it again.",
        );
      });
    } catch (error) {
      this.stop();
      throw error;
    }
  }
  consume(chunk) {
    if (this.muted || this.paused) return;
    const rms = Math.sqrt(
      chunk.reduce((sum, value) => sum + value * value, 0) / chunk.length,
    );
    const seconds = chunk.length / this.context.sampleRate;
    if (!this.recording) {
      this.preRoll.push(chunk);
      const preRollSeconds = this.assistantSpeaking ? 0.4 : 0.35;
      while (this.preRoll.length * seconds > preRollSeconds) this.preRoll.shift();
      if (this.assistantSpeaking) {
        if (rms >= 0.03) this.assistantVoiced += seconds;
        else this.assistantVoiced = 0;
        if (this.assistantVoiced < 0.35) return;
      } else if (rms < 0.018) return;
      this.recording = true;
      this.chunks = [...this.preRoll];
      this.preRoll = [];
      this.duration = this.chunks.length * seconds;
      this.voiced = this.assistantSpeaking ? this.assistantVoiced : seconds;
      this.lastVoiceMs = performance.timeOrigin + performance.now();
      this.onRecording(true);
      for (const sampleChunk of this.chunks) this.onChunk?.(sampleChunk);
      return;
    }
    this.chunks.push(chunk);
    this.onChunk?.(chunk);
    this.duration += seconds;
    if (rms >= 0.012) {
      if (this.silence > 0) {
        this.cancelTurnCheck();
        this.onSpeechResume?.();
        if (this.turnDecision !== "fallback") this.turnDecision = null;
      }
      this.silence = 0;
      this.voiced += seconds;
      this.lastVoiceMs = performance.timeOrigin + performance.now();
    } else this.silence += seconds;
    if (this.duration >= 28) {
      this.finish("duration_limit");
    } else if (!this.checkTurn || this.turnDecision === "fallback") {
      if (this.silence > this.settled()) this.finish("pause");
    } else if (this.silence >= SMART_MAX_SILENCE) {
      this.finish("silence_limit");
    } else if (this.silence >= SMART_PAUSE_SECONDS[this.pauseMode]) {
      if (!this.turnCheck && !this.turnDecision) this.requestTurnCheck();
    }
  }
  cancelTurnCheck() {
    this.voiceRevision = (this.voiceRevision || 0) + 1;
    this.turnCheck?.controller.abort();
    this.turnCheck = null;
  }
  requestTurnCheck() {
    if (this.voiced <= 0.22) {
      this.turnDecision = "fallback";
      return;
    }
    const request = { revision: this.voiceRevision, controller: new AbortController() };
    this.turnCheck = request;
    this.onTurnCheck?.();
    const audio = wavBlob(
      recentChunks(this.chunks, this.context.sampleRate * 8),
      this.context.sampleRate,
    );
    Promise.resolve().then(() => this.checkTurn(audio, request.controller.signal)).then((result) => {
      if (this.turnCheck !== request || request.revision !== this.voiceRevision || !this.recording) return;
      this.turnCheck = null;
      if (!result || typeof result.complete !== "boolean") {
        this.turnDecision = "fallback";
        if (this.silence > this.settled()) this.finish("pause");
      } else if (result.complete) {
        this.finish("smart_turn", result);
      } else {
        this.turnDecision = "incomplete";
      }
    }).catch(() => {
      if (this.turnCheck !== request || request.revision !== this.voiceRevision) return;
      this.turnCheck = null;
      this.turnDecision = "fallback";
      if (this.recording && this.silence > this.settled()) this.finish("pause");
    });
  }
  finish(reason, decision = null) {
    if (!this.recording) return;
    const timing = {
      speechEndMs: this.lastVoiceMs,
      captureEndMs: performance.timeOrigin + performance.now(),
      turnReason: reason,
      turnProbability: decision?.probability,
      turnCheckMs: decision?.inference_ms,
    };
    const blob = this.voiced > 0.22 ? wavBlob(this.chunks, this.context.sampleRate) : null;
    this.clear({ discard: !blob });
    if (blob) this.onAudio(blob, timing);
  }
  settled() {
    return PAUSE_SECONDS[this.pauseMode];
  }
  setMuted(value) {
    this.muted = value;
    this.stream?.getTracks().forEach((track) => {
      track.enabled = !value;
    });
    this.clear();
  }
  setPaused(value) {
    if (this.paused === value) return;
    this.paused = value;
    this.clear();
  }
  setAssistantSpeaking(value) {
    const next = Boolean(value);
    if (this.assistantSpeaking === next) return;
    this.assistantSpeaking = next;
    this.assistantVoiced = 0;
  }
  stop() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.source?.disconnect();
    this.node?.disconnect();
    this.gain?.disconnect();
    this.context?.close().catch(() => {});
    this.stream = null;
    this.clear();
  }
}
