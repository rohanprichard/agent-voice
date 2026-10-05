class VoiceCall {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private sink: GainNode | null = null;
  private input: WebSocket | null = null;
  private output: WebSocket | null = null;
  private audio: HTMLAudioElement | null = null;
  private audioURL = "";
  private stopped = false;
  private muted = false;
  private speaking = false;
  private pendingSpeech: Promise<void> = Promise.resolve();
  private listening = true; // false once the call ends and only the last replies play
  private reconnects = 0;
  private skipTo = 0; // replies queued before this count are not spoken
  private queued = 0;
  private turn = new UserTurn();
  private turnAudio: Float32Array[] = [];
  private audioSamples = 0;
  private segments: string[] = [];
  private analyzing = false;
  private analyzedRevision: number | null = null;
  private commitRevision: number | null = null;
  private deliveryRevision: number | null = null;
  private completionRevision: number | null = null;
  private inputGeneration = 0;
  private commitTimer: ReturnType<typeof setTimeout> | null = null;
  private candidate = false;
  private interrupted = false;
  private suppressReplies = false;
  private speechEpoch = 0;
  private detectorPending = 0;
  private detectionGeneration = 0;
  private captureReadyResolve!: () => void;
  private captureReady = new Promise<void>((resolve) => { this.captureReadyResolve = resolve; });
  private preparation: Promise<void> = Promise.resolve();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  ready = false;
  // What the pill draws: the microphone level, and the words heard so far.
  level = 0;
  partial = "";

  constructor(
    readonly callId: string,
    private readonly onText: (text: string) => void,
    private readonly onStatus: (text: string, failed?: boolean) => void,
  ) {}

  async start(): Promise<void> {
    try {
      this.onStatus("Preparing speech detection…");
      this.preparation = window.talktome.detectorStart(this.callId);
      await this.preparation;
      if (this.stopped || !this.listening) return;
      this.onStatus("Connecting microphone…");
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (this.stopped || !this.listening) { this.stream.getTracks().forEach((track) => track.stop()); return; }
      this.context = new AudioContext({ sampleRate: 16000 });
      await this.context.resume();
      await this.openInput();
      if (this.stopped || !this.listening) return;
      this.source = this.context.createMediaStreamSource(this.stream);
      this.processor = this.context.createScriptProcessor(1024, 1, 1);
      this.sink = this.context.createGain();
      this.sink.gain.value = 0;
      this.processor.onaudioprocess = (event) => this.capture(event.inputBuffer.getChannelData(0));
      this.source.connect(this.processor).connect(this.sink).connect(this.context.destination);
      this.ready = true;
      this.captureReadyResolve();
      this.onStatus("Listening…");
    } catch (error) {
      if (!this.stopped) this.fail(error instanceof Error ? error.message : "Speech input failed.");
    }
  }

  private capture(samples: Float32Array): void {
    let sum = 0;
    for (const sample of samples) sum += sample * sample;
    this.level = this.muted ? 0 : Math.sqrt(sum / samples.length);
    const socket = this.input;
    if (this.stopped || !this.listening || !socket || socket.readyState !== WebSocket.OPEN) return;
    const heard = this.muted ? new Float32Array(samples.length) : new Float32Array(samples);
    // Local detection continues during playback. The recognizer waits for a possible interruption.
    const recognized = this.speaking && !this.candidate ? new Float32Array(heard.length) : heard;
    socket.send(JSON.stringify({
      message_type: "input_audio_chunk",
      audio_base_64: VoiceCall.pcmBase64(recognized),
      sample_rate: this.context?.sampleRate,
    }));
    if (this.muted) return;
    this.turnAudio.push(heard);
    this.audioSamples += heard.length;
    while (this.audioSamples > (this.turn.active ? 128000 : 6400) && this.turnAudio.length > 1) this.audioSamples -= this.turnAudio.shift()!.length;
    if (++this.detectorPending > 8) { this.fail("Speech detection cannot keep pace with the microphone."); return; }
    const generation = this.detectionGeneration;
    void window.talktome.detectorAudio(this.callId, "vad", VoiceCall.pcmBase64(heard)).then((result) => {
      if (this.stopped || !this.listening || this.muted || generation !== this.detectionGeneration) return;
      for (const probability of result.probabilities ?? []) this.detectSpeech(probability);
    }).catch((error: Error) => { if (!this.stopped && this.listening) this.fail(error.message); })
      .finally(() => { this.detectorPending -= 1; this.deliverTurn(); });
  }

  // openInput connects speech input with a new single-use token.
  private async openInput(): Promise<void> {
    const generation = ++this.inputGeneration;
    const token = await window.talktome.speechToken(this.callId, "realtime_scribe");
    if (this.stopped || this.muted || generation !== this.inputGeneration || !this.context) return;
    const query = new URLSearchParams({
      model_id: "scribe_v2_realtime",
      audio_format: `pcm_${this.context.sampleRate}`,
      commit_strategy: "manual",
      token,
    });
    const socket = new WebSocket(`wss://api.elevenlabs.io/v1/speech-to-text/realtime?${query}`);
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Speech input took too long to connect.")), 10000);
      socket.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
      socket.addEventListener("error", () => { clearTimeout(timer); reject(new Error("Speech input could not connect.")); }, { once: true });
      socket.addEventListener("close", () => { clearTimeout(timer); reject(new Error("Speech input closed.")); }, { once: true });
    });
    if (this.stopped || this.muted || generation !== this.inputGeneration) { socket.close(); return; }
    this.input = socket;
    this.reconnects = 0;
    socket.addEventListener("message", (event) => { if (this.input === socket) this.receive(String(event.data)); });
    socket.addEventListener("close", () => {
      if (this.input === socket) this.reconnect();
    });
  }

  // reconnect opens speech input again after it drops, up to three times.
  private reconnect(): void {
    this.input = null;
    if (this.stopped || !this.listening || this.muted) return;
    this.reconnects += 1;
    if (this.reconnects > 3) {
      this.fail("Speech input closed.");
      return;
    }
    this.reconnectTimer = setTimeout(() => {
      if (this.stopped || !this.listening || this.muted) return;
      this.resetTurn();
      this.openInput().catch(() => this.reconnect());
    }, 500 * this.reconnects);
  }

  // explain turns an ElevenLabs error into words the user can act on.
  static explain(code: string, message = ""): string {
    if (code === "quota_exceeded" || /quota|credits/i.test(message)) {
      return "Your ElevenLabs account is out of credits. All keys on an account share its credits, so a new key does not help. Add credits at elevenlabs.io, then call again.";
    }
    if (code === "auth_error" || /unauthori[sz]ed|invalid api key/i.test(message)) return "ElevenLabs refused the key. Check it in talktome.";
    if (code === "rate_limited" || /rate limit/i.test(message)) return "ElevenLabs is busy right now. Try again in a moment.";
    return message || "Speech stopped.";
  }

  private detectSpeech(probability: number): void {
    const decision = this.turn.frame(probability);
    if (decision.started && this.speaking) {
      this.candidate = true;
      this.audio?.pause();
      // Retain the first words while local speech detection waits for sustained speech.
      const buffered = new Float32Array(this.audioSamples);
      let offset = 0;
      for (const chunk of this.turnAudio) { buffered.set(chunk, offset); offset += chunk.length; }
      if (this.input?.readyState === WebSocket.OPEN) this.input.send(JSON.stringify({
        message_type: "input_audio_chunk", audio_base_64: VoiceCall.pcmBase64(buffered.slice(-4096)), sample_rate: 16000,
      }));
    }
    // A noise event without words must not discard the agent's reply.
    if (this.candidate && !this.interrupted && this.turn.silenceMs >= 2000 && !this.partial && !this.segments.length) {
      this.resumeReply();
      this.resetTurn();
      return;
    }
    if (decision.fallback) this.commitTurn();
    else if (decision.analyze && !this.analyzing && this.commitRevision === null && this.analyzedRevision !== this.turn.revision) {
      this.analyzing = true;
      const revision = this.turn.revision;
      // Examine each pause once. Longer silence must not replace the speech context.
      this.analyzedRevision = revision;
      const audio = new Float32Array(this.audioSamples);
      let offset = 0;
      for (const chunk of this.turnAudio) { audio.set(chunk, offset); offset += chunk.length; }
      void window.talktome.detectorAudio(this.callId, "turn", VoiceCall.pcmBase64(audio)).then((result) => {
        if (!this.stopped && this.listening && !this.muted && this.turn.accepts(result.probability ?? 0, revision)) this.commitTurn();
      }).catch((error: Error) => { if (!this.stopped && this.listening) this.fail(error.message); })
        .finally(() => { this.analyzing = false; });
    }
  }

  private commitTurn(): void {
    if (this.commitRevision !== null || this.deliveryRevision !== null || !this.turn.active || this.input?.readyState !== WebSocket.OPEN) return;
    this.completionRevision = this.turn.revision;
    if (!this.partial && !this.segments.length) return;
    this.commitRevision = this.turn.revision;
    this.input.send(JSON.stringify({ message_type: "input_audio_chunk", audio_base_64: "", sample_rate: 16000, commit: true }));
    this.commitTimer = setTimeout(() => this.fail("The transcript took too long to complete. Start another call."), 8000);
  }

  private resetTurn(): void {
    this.detectionGeneration += 1;
    this.turn.reset();
    this.turnAudio = [];
    this.audioSamples = 0;
    this.segments = [];
    this.partial = "";
    this.commitRevision = null;
    this.deliveryRevision = null;
    this.completionRevision = null;
    this.analyzedRevision = null;
    if (this.commitTimer) clearTimeout(this.commitTimer);
    this.commitTimer = null;
  }

  private resumeReply(): void {
    this.candidate = false;
    this.interrupted = false;
    if (this.audio?.paused) void this.audio.play().catch(() => this.onStatus("The reply could not resume.", true));
  }

  private confirmInterruption(text: string): void {
    if (!this.candidate || this.interrupted || !text.trim()) return;
    // Brief acknowledgments do not replace a reply. Short commands still interrupt.
    if (/^(uh[ -]?huh|mm[ -]?hmm|mhm)[.!?]*$/i.test(text.trim()) && this.turn.speechMs < 500) return;
    this.interrupted = true;
    this.suppressReplies = true;
    this.stopSpeaking();
  }

  private receive(raw: string): void {
    if (this.stopped || !this.listening) return;
    let event: { message_type?: string; text?: string; error?: string; message?: string };
    try { event = JSON.parse(raw); } catch { return; }
    if (event.message_type === "committed_transcript") {
      const text = event.text?.trim() ?? "";
      if (this.turn.active && text) this.segments.push(text);
      this.partial = "";
      if (this.commitRevision === null) return;
      const revision = this.commitRevision;
      this.commitRevision = null;
      if (this.commitTimer) clearTimeout(this.commitTimer);
      this.commitTimer = null;
      this.deliveryRevision = revision;
      this.deliverTurn();
    } else if (event.message_type === "partial_transcript" && event.text?.trim() && this.turn.active) {
      this.partial = event.text.trim();
      this.confirmInterruption(this.partial);
      if (this.completionRevision === this.turn.revision && this.turn.silenceMs >= 320) this.commitTurn();
    } else if (event.message_type && /error|quota|limit/.test(event.message_type)) {
      this.fail(VoiceCall.explain(event.message_type, event.error ?? event.message));
    }
  }

  private deliverTurn(): void {
    if (this.deliveryRevision === null || this.detectorPending > 0 || this.stopped || !this.listening || this.muted) return;
    const revision = this.deliveryRevision;
    this.deliveryRevision = null;
    // All earlier microphone frames must reach VAD before delivery.
    if (revision !== this.turn.revision || this.turn.silenceMs < 320) return;
    const thought = this.segments.join(" ").trim();
    if (this.candidate && !this.interrupted && /^(uh[ -]?huh|mm[ -]?hmm|mhm)[.!?]*$/i.test(thought)) {
      this.resumeReply();
      this.resetTurn();
      return;
    }
    this.confirmInterruption(thought);
    if (!thought) this.resumeReply();
    this.resetTurn();
    this.candidate = false;
    this.interrupted = false;
    this.suppressReplies = false;
    if (thought) { this.onStatus("Thinking…"); this.onText(thought); }
  }

  speak(text: string): void {
    if (!text.trim() || this.stopped || this.suppressReplies) return;
    const place = ++this.queued;
    this.pendingSpeech = this.pendingSpeech.then(async () => {
      await this.preparation;
      await this.captureReady;
      if (place > this.skipTo && !this.suppressReplies) await this.playSpeech(text);
    }).catch((error) => {
      if (!this.stopped) this.onStatus(error instanceof Error ? error.message : "Speech output failed.", true);
    });
  }

  private async playSpeech(text: string): Promise<void> {
    if (this.stopped) return;
    const epoch = this.speechEpoch;
    this.speaking = true;
    this.onStatus("Speaking…");
    try {
      const token = await window.talktome.speechToken(this.callId, "tts_websocket");
      if (this.stopped || epoch !== this.speechEpoch) return;
      const voice = await window.talktome.speechVoice();
      if (this.stopped || epoch !== this.speechEpoch) return;
      const query = new URLSearchParams({
        model_id: "eleven_flash_v2_5", output_format: "mp3_44100_128", single_use_token: token,
      });
      const socket = new WebSocket(`wss://api.elevenlabs.io/v1/text-to-speech/${voice}/stream-input?${query}`);
      this.output = socket;
      const chunks = await new Promise<Uint8Array[]>((resolve, reject) => {
        const parts: Uint8Array[] = [];
        const timer = setTimeout(() => reject(new Error("Speech output took too long.")), 20000);
        socket.addEventListener("open", () => {
          socket.send(JSON.stringify({ text: " ", voice_settings: { stability: 0.5, similarity_boost: 0.75 } }));
          socket.send(JSON.stringify({ text: `${text.trim()} `, flush: true }));
          socket.send(JSON.stringify({ text: "" }));
        }, { once: true });
        socket.addEventListener("message", (message) => {
          let value: { audio?: string; isFinal?: boolean; is_final?: boolean; error?: string; message?: string };
          try { value = JSON.parse(String(message.data)); } catch { return; }
          if (value.error) { clearTimeout(timer); reject(new Error(VoiceCall.explain(value.error, value.message))); return; }
          if (value.audio) parts.push(Uint8Array.from(atob(value.audio), (char) => char.charCodeAt(0)));
          // ElevenLabs marks the last message with isFinal.
          if (value.isFinal || value.is_final) { clearTimeout(timer); resolve(parts); }
        });
        socket.addEventListener("error", () => { clearTimeout(timer); reject(new Error("Speech output could not connect.")); }, { once: true });
        socket.addEventListener("close", (event) => {
          clearTimeout(timer);
          if (epoch !== this.speechEpoch) resolve([]);
          else if (parts.length) resolve(parts);
          else reject(new Error(event.reason ? VoiceCall.explain("", event.reason) : "Speech output closed."));
        }, { once: true });
      });
      socket.close();
      this.output = null;
      if (this.stopped || epoch !== this.speechEpoch || !chunks.length) return;
      this.audioURL = URL.createObjectURL(new Blob(chunks as BlobPart[], { type: "audio/mpeg" }));
      this.audio = new Audio(this.audioURL);
      await new Promise<void>((resolve, reject) => {
        const audio = this.audio!;
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error("Speech audio could not play."));
        if (!this.candidate) audio.play().catch(reject);
      });
    } finally {
      this.output?.close();
      this.output = null;
      this.audio?.pause();
      this.audio = null;
      if (this.audioURL) URL.revokeObjectURL(this.audioURL);
      this.audioURL = "";
      this.speaking = false;
      if (!this.stopped) this.onStatus(this.muted ? "Microphone off" : "Listening…");
    }
  }

  // playing is true while a reply is heard, which is when the agent's thread moves.
  playing(): boolean {
    return Boolean(this.audio && !this.audio.paused);
  }

  // stopSpeaking stops the reply that plays, and drops the ones waiting.
  stopSpeaking(): void {
    this.speechEpoch += 1;
    this.skipTo = this.queued;
    this.output?.close();
    if (this.audio) {
      this.audio.pause();
      this.audio.dispatchEvent(new Event("ended"));
    }
  }

  setMuted(value: boolean): void {
    this.muted = value;
    if (value) {
      this.inputGeneration += 1;
      const input = this.input;
      this.input = null;
      input?.close();
      if (this.candidate && !this.interrupted) this.resumeReply();
      this.resetTurn();
      this.candidate = false;
      this.interrupted = false;
      this.suppressReplies = false;
      void window.talktome.detectorAudio(this.callId, "reset", "").catch(() => undefined);
    } else if (this.ready && !this.stopped && this.listening) {
      void this.openInput().catch((error: Error) => { if (!this.stopped) this.fail(error.message); });
    }
    this.stream?.getAudioTracks().forEach((track) => { track.enabled = !value; });
    if (!this.speaking) this.onStatus(value ? "Microphone off" : "Listening…");
  }

  isMuted(): boolean { return this.muted; }

  hasUserTurn(): boolean { return this.turn.active; }

  // finish ends the call's listening, lets the replies that wait play out,
  // and then stops. A goodbye is the last thing the user hears.
  async finish(): Promise<void> {
    this.listening = false;
    this.captureReadyResolve();
    this.resetTurn();
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.candidate && !this.interrupted) this.resumeReply();
    this.muted = true;
    this.input?.close();
    this.stream?.getTracks().forEach((track) => track.stop());
    await this.pendingSpeech;
    this.stop();
  }

  stop(): void {
    this.stopped = true;
    this.captureReadyResolve();
    this.inputGeneration += 1;
    this.resetTurn();
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    void window.talktome.detectorStop(this.callId).catch(() => undefined);
    this.stopSpeaking();
    this.input?.close();
    this.output?.close();
    this.processor?.disconnect();
    this.source?.disconnect();
    this.sink?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    void this.context?.close();
    this.audio?.pause();
    if (this.audioURL) URL.revokeObjectURL(this.audioURL);
  }

  private fail(message: string): void {
    this.stop();
    this.onStatus(`Speech unavailable: ${message}`, true);
  }

  private static pcmBase64(samples: Float32Array): string {
    const bytes = new Uint8Array(samples.length * 2);
    const view = new DataView(bytes.buffer);
    for (let index = 0; index < samples.length; index++) {
      const value = Math.max(-1, Math.min(1, samples[index]));
      view.setInt16(index * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  }
}
