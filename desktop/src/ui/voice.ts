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
      this.onStatus("Connecting microphone…");
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (this.stopped) return;
      this.context = new AudioContext({ sampleRate: 48000 });
      await this.context.resume();
      await this.openInput();
      if (this.stopped) return;
      this.source = this.context.createMediaStreamSource(this.stream);
      this.processor = this.context.createScriptProcessor(4096, 1, 1);
      this.sink = this.context.createGain();
      this.sink.gain.value = 0;
      this.processor.onaudioprocess = (event) => {
        const samples = event.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let index = 0; index < samples.length; index++) sum += samples[index] * samples[index];
        this.level = this.muted ? 0 : Math.sqrt(sum / samples.length);
        const socket = this.input;
        if (this.stopped || !socket || socket.readyState !== WebSocket.OPEN) return;
        // While muted or while the agent speaks, send silence: the user is not
        // heard, and ElevenLabs keeps the session, which it closes when no audio comes.
        const heard = this.muted || this.speaking ? new Float32Array(samples.length) : samples;
        socket.send(JSON.stringify({
          message_type: "input_audio_chunk",
          audio_base_64: VoiceCall.pcmBase64(heard),
          sample_rate: this.context?.sampleRate,
        }));
      };
      this.source.connect(this.processor).connect(this.sink).connect(this.context.destination);
      this.onStatus("Listening…");
    } catch (error) {
      if (!this.stopped) this.fail(error instanceof Error ? error.message : "Speech input failed.");
    }
  }

  // openInput connects speech input with a new single-use token.
  private async openInput(): Promise<void> {
    const token = await window.talktome.speechToken(this.callId, "realtime_scribe");
    if (this.stopped || !this.context) return;
    const query = new URLSearchParams({
      model_id: "scribe_v2_realtime",
      audio_format: `pcm_${this.context.sampleRate}`,
      commit_strategy: "vad",
      vad_silence_threshold_secs: "0.8",
      token,
    });
    const socket = new WebSocket(`wss://api.elevenlabs.io/v1/speech-to-text/realtime?${query}`);
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Speech input took too long to connect.")), 10000);
      socket.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
      socket.addEventListener("error", () => { clearTimeout(timer); reject(new Error("Speech input could not connect.")); }, { once: true });
      socket.addEventListener("close", () => { clearTimeout(timer); reject(new Error("Speech input closed.")); }, { once: true });
    });
    this.input = socket;
    this.reconnects = 0;
    socket.addEventListener("message", (event) => this.receive(String(event.data)));
    socket.addEventListener("close", () => {
      if (this.input === socket) this.reconnect();
    });
  }

  // reconnect opens speech input again after it drops, up to three times.
  private reconnect(): void {
    this.input = null;
    if (this.stopped || !this.listening) return;
    this.reconnects += 1;
    if (this.reconnects > 3) {
      this.fail("Speech input closed.");
      return;
    }
    setTimeout(() => {
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

  private receive(raw: string): void {
    let event: { message_type?: string; text?: string; error?: string; message?: string };
    try { event = JSON.parse(raw); } catch { return; }
    if (event.message_type === "committed_transcript" && event.text?.trim()) {
      this.partial = "";
      this.onStatus("Thinking…");
      this.onText(event.text.trim());
    } else if (event.message_type === "partial_transcript" && event.text?.trim()) {
      this.partial = event.text.trim();
    } else if (event.message_type && /error|quota|limit/.test(event.message_type)) {
      this.fail(VoiceCall.explain(event.message_type, event.error ?? event.message));
    }
  }

  speak(text: string): void {
    if (!text.trim() || this.stopped) return;
    const place = ++this.queued;
    this.pendingSpeech = this.pendingSpeech.then(() => (place > this.skipTo ? this.playSpeech(text) : undefined)).catch((error) => {
      if (!this.stopped) this.onStatus(error instanceof Error ? error.message : "Speech output failed.", true);
    });
  }

  private async playSpeech(text: string): Promise<void> {
    if (this.stopped) return;
    this.speaking = true;
    this.onStatus("Speaking…");
    try {
      const token = await window.talktome.speechToken(this.callId, "tts_websocket");
      if (this.stopped) return;
      const voice = await window.talktome.speechVoice();
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
          if (parts.length) resolve(parts);
          else reject(new Error(event.reason ? VoiceCall.explain("", event.reason) : "Speech output closed."));
        }, { once: true });
      });
      socket.close();
      this.output = null;
      if (this.stopped || !chunks.length) return;
      this.audioURL = URL.createObjectURL(new Blob(chunks as BlobPart[], { type: "audio/mpeg" }));
      this.audio = new Audio(this.audioURL);
      await new Promise<void>((resolve, reject) => {
        const audio = this.audio!;
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error("Speech audio could not play."));
        audio.play().catch(reject);
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
    this.skipTo = this.queued;
    this.output?.close();
    if (this.audio) {
      this.audio.pause();
      this.audio.dispatchEvent(new Event("ended"));
    }
  }

  setMuted(value: boolean): void {
    this.muted = value;
    this.stream?.getAudioTracks().forEach((track) => { track.enabled = !value; });
    if (!this.speaking) this.onStatus(value ? "Microphone off" : "Listening…");
  }

  isMuted(): boolean { return this.muted; }

  // finish ends the call's listening, lets the replies that wait play out,
  // and then stops. A goodbye is the last thing the user hears.
  async finish(): Promise<void> {
    this.listening = false;
    this.muted = true;
    this.input?.close();
    this.stream?.getTracks().forEach((track) => track.stop());
    await this.pendingSpeech;
    this.stop();
  }

  stop(): void {
    this.stopped = true;
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
