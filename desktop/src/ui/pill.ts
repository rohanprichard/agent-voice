// The call surface: a capsule that grows out from under the menu bar, rings,
// becomes the call pill when answered, and goes back when the call ends. The
// transcript opens below it. With no speech, the user types in the transcript.

(() => {
  followTheme();
  const surface = document.getElementById("surface")!;
  const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
  const ringing = $("ringing");
  const pill = $("pill");
  const list = $("t-list");
  const empty = $("t-empty");
  const choices = $("choices");
  const say = $<HTMLInputElement>("say");
  const status = $("call-status");
  const mute = $("mute");
  const interrupt = $<HTMLButtonElement>("interrupt");
  const toggle = $("transcript-toggle");

  type Shape = "hidden" | "attached" | "settled";
  let shape: Shape = "hidden";
  let current: Call | null = null;
  let voice: VoiceCall | null = null;
  let speechFailed = false;
  let spokenLines = 0;
  let listKey = "";
  let agentPulseUntil = 0;
  let timers: number[] = [];
  let stopThreads: (() => void) | null = null;

  function later(ms: number, fn: () => void): void {
    timers.push(window.setTimeout(fn, ms));
  }

  function clearTimers(): void {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function setShape(next: Shape): void {
    shape = next;
    surface.dataset.shape = next;
  }

  // appear: attached first, still dark under the menu bar, then it lets go.
  function appear(): void {
    clearTimers();
    setShape("attached");
    later(300, () => setShape("settled"));
  }

  function withdraw(): void {
    clearTimers();
    ringing.classList.remove("shown");
    pill.classList.remove("shown");
    surface.dataset.transcript = "closed";
    later(120, () => setShape("attached"));
    later(420, () => setShape("hidden"));
  }

  function nameOf(call: Call): string {
    if (call.direction === "incoming") return call.reason || call.agent.name;
    return call.target?.project ?? call.agent.name;
  }

  function render(state: Snapshot): void {
    const call = state.calls.find((c) => c.state === "ringing") ?? state.calls[state.calls.length - 1] ?? null;
    if (!call) {
      if (current) withdraw();
      stopVoice();
      current = null;
      return;
    }
    const fresh = call.id !== current?.id;
    const was = current?.state;
    current = call;
    if (fresh) {
      stopVoice();
      speechFailed = false;
      $("t-note").hidden = true;
      spokenLines = 0;
      listKey = "";
      surface.dataset.transcript = "closed";
      if (shape === "hidden") appear();
    }
    surface.dataset.state = call.state;

    // The contents wait until the capsule has let go of the menu bar.
    const settleWait = shape === "settled" ? 0 : 520;
    if (call.state === "ringing") {
      $("ring-name").textContent = nameOf(call);
      $("ring-hint").textContent = call.reason ? `${call.agent.name} wants to talk` : "wants to talk";
      later(settleWait, () => ringing.classList.add("shown"));
      pill.classList.remove("shown");
    } else {
      ringing.classList.remove("shown");
      $("call-name").textContent = nameOf(call);
      later(was === "ringing" ? 180 : settleWait, () => pill.classList.add("shown"));
    }

    if (call.state === "live" && !voice && !speechFailed) startVoice(call);
    if (call.state === "ended" && was === "ringing") {
      // A declined or missed ring goes straight back.
      withdraw();
      return;
    }
    if (call.state === "ended") {
      stopVoice();
      later(1400, () => {
        if (current?.id === call.id && current.state === "ended") withdraw();
      });
    }
    if (voice && call.state === "live") {
      for (const line of call.lines.slice(spokenLines)) {
        if (line.who === "agent" && line.final !== false) voice.speak(line.text);
      }
    }
    if (call.lines.slice(spokenLines).some((line) => line.who === "agent")) agentPulseUntil = performance.now() + 1600;
    spokenLines = call.lines.length;
    if (call.choices?.length && call.state === "live" && !call.lines.some((l) => l.who === "user")) openTranscript(true);
    renderTranscript(call);
    renderStatus();
  }

  function startVoice(call: Call): void {
    voice = new VoiceCall(
      call.id,
      (text) => void window.talktome.say(call.id, text),
      (_text, failed) => {
        if (!failed) return;
        // Without speech the call goes on in text: the transcript opens with the cursor in its field.
        speechFailed = true;
        voice = null;
        openTranscript(true);
        const note = $("t-note");
        note.textContent = _text.replace(/^Speech unavailable: /, "");
        note.hidden = false;
        say.focus();
      },
    );
    void voice.start();
    stopThreads?.();
    stopThreads = Threads.start($<HTMLCanvasElement>("canvas"), () => ({
      user: Boolean(voice && !voice.isMuted() && (voice.level > 0.02 || voice.partial)),
      agent: Boolean(voice?.playing()) || performance.now() < agentPulseUntil,
    }));
  }

  function stopVoice(): void {
    voice?.stop();
    voice = null;
  }

  function openTranscript(open: boolean): void {
    surface.dataset.transcript = open ? "open" : "closed";
    toggle.setAttribute("aria-expanded", String(open));
  }

  function renderTranscript(call: Call): void {
    const partial = voice?.partial ?? "";
    const key = `${call.id}:${call.lines.length}:${partial}:${call.choices?.length ?? 0}`;
    if (key === listKey) return;
    listKey = key;
    const name = nameOf(call);
    const rows = call.lines.map((line) =>
      el(
        "li",
        { class: `${line.who}${line.final === false ? " progress" : ""}` },
        el("span", { class: "who", text: line.who === "user" ? "You" : line.who === "agent" ? name : "" }),
        el("span", { class: "said", text: line.text }),
      ),
    );
    if (partial) rows.push(el("li", { class: "user partial" }, el("span", { class: "who", text: "You · live" }), el("span", { class: "said", text: partial })));
    list.replaceChildren(...rows);
    empty.hidden = rows.length > 0;
    list.scrollTop = list.scrollHeight;

    const asked = call.choices?.length && !call.lines.some((l) => l.who === "user");
    choices.replaceChildren(...(asked ? call.choices!.map((choice) => button(choice, "", () => void window.talktome.say(call.id, choice))) : []));
  }

  function renderStatus(): void {
    const call = current;
    if (!call || call.state === "ringing") return;
    let text = "Listening";
    let kind = "";
    if (call.state === "calling") [text, kind] = ["Calling…", "waiting"];
    else if (call.state === "ended") text = call.ended ?? "Call ended";
    else if (voice?.playing()) [text, kind] = ["Agent speaking", "agent"];
    else if (call.waiting) [text, kind] = ["Thinking…", "waiting"];
    else if (speechFailed) [text, kind] = ["Type to talk", "agent"];
    else if (voice?.isMuted()) [text, kind] = ["Microphone off", "agent"];
    else if (voice?.partial) text = "Hearing you";
    if (status.textContent !== text) status.textContent = text;
    status.className = `status ${kind}`;
    interrupt.disabled = !voice?.playing();
    const muted = Boolean(voice?.isMuted());
    mute.setAttribute("aria-pressed", String(muted));
    $("mic-on").hidden = muted;
    $("mic-off").hidden = !muted;
    if (call.state === "live" && voice?.partial !== undefined) renderTranscript(call);
  }
  setInterval(renderStatus, 150);

  $("accept").addEventListener("click", () => current && void window.talktome.answer(current.id));
  $("decline").addEventListener("click", () => current && void window.talktome.decline(current.id));
  $("end").addEventListener("click", () => current && void window.talktome.hangUp(current.id));
  interrupt.addEventListener("click", () => voice?.stopSpeaking());
  mute.addEventListener("click", () => {
    if (!voice) return;
    voice.setMuted(!voice.isMuted());
    renderStatus();
  });
  toggle.addEventListener("click", () => openTranscript(surface.dataset.transcript !== "open"));
  $("transcript-close").addEventListener("click", () => openTranscript(false));
  say.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !say.value.trim() || !current) return;
    const text = say.value;
    say.value = "";
    void window.talktome.say(current.id, text);
  });

  // The window lets clicks through, except over the capsule and the transcript.
  let inside = false;
  document.addEventListener("mousemove", (event) => {
    const target = document.elementFromPoint(event.clientX, event.clientY);
    const over = Boolean(target?.closest(".layer.shown, #surface[data-transcript='open'] #transcript"));
    if (over !== inside) {
      inside = over;
      void window.talktome.pointer(over);
    }
  });

  window.talktome.onState(render);
  window.talktome.state().then(render);
})();
