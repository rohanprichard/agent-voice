// The call pill: a ring, then a voice call with text input if speech fails.

(() => {
  followTheme();
  const root = document.getElementById("pill")!;
  let drafts = new Map<string, string>();
  let shown = "";
  let voice: VoiceCall | null = null;
  let voiceStatus = "Connecting microphone…";
  let voiceFailed = false;
  let showText = false;
  let handledLines = 0;
  let lastState: Snapshot | null = null;

  function render(state: Snapshot): void {
    lastState = state;
    const call = state.calls.find((c) => c.state === "ringing") ?? state.calls[state.calls.length - 1];
    if (!call || call.state !== "live" || voice?.callId !== call.id) {
      voice?.stop();
      voice = null;
    }
    if (!call) {
      root.replaceChildren();
      shown = "";
      return;
    }
    if (call.state === "live" && !voice) {
      voiceStatus = "Connecting microphone…";
      voiceFailed = false;
      showText = false;
      handledLines = 0;
      voice = new VoiceCall(call.id, (text) => { void window.talktome.say(call.id, text); }, (status, failed) => {
        voiceStatus = status;
        if (failed) { voiceFailed = true; showText = true; }
        const label = root.querySelector(".voice-state");
        if (label) label.textContent = status;
        if (failed && lastState) render(lastState);
      });
      void voice.start();
    }
    if (voice && call.state === "live") {
      for (const line of call.lines.slice(handledLines)) {
        if (line.who === "agent" && line.final !== false) voice.speak(line.text);
      }
      handledLines = call.lines.length;
    }
    // Keep the text the user is typing when the state changes.
    const input = root.querySelector<HTMLInputElement>("input.say");
    if (input && shown) drafts.set(shown, input.value);
    const focused = document.activeElement === input;
    shown = call.id;
    root.replaceChildren(card(call));
    const next = root.querySelector<HTMLInputElement>("input.say");
    if (next) {
      next.value = drafts.get(call.id) ?? "";
      if (focused || call.state === "live") next.focus();
    }
    const log = root.querySelector(".lines");
    if (log) log.scrollTop = log.scrollHeight;
  }

  function card(call: Call): HTMLElement {
    const title = call.direction === "incoming" ? call.agent.name : `${call.agent.name} · ${call.target?.project ?? ""}`;
    const status = {
      ringing: call.urgency === "urgent" ? "Urgent call" : "Incoming call",
      calling: `Calling (${call.mode})…`,
      live: call.waiting ? "Thinking…" : "Live",
      ended: call.ended ?? "Call ended",
    }[call.state];
    const head = el("header", {}, el("div", { class: "who", text: title }), el("div", { class: `status ${call.state}`, text: status }));
    const body = el("div", { class: "body" });
    if (call.reason && call.direction === "incoming") body.append(el("div", { class: "reason", text: call.reason }));

    if (call.state === "ringing") {
      if (call.question) body.append(el("div", { class: "question", text: call.question }));
      body.append(
        el(
          "div",
          { class: "actions" },
          button("Decline", "secondary-button decline", () => window.talktome.decline(call.id)),
          button("Answer", "primary-button answer", () => window.talktome.answer(call.id)),
        ),
      );
      return el("section", { class: "card ringing" }, head, body);
    }

    const lines = el("div", { class: "lines" });
    for (const line of call.lines) lines.append(el("div", { class: `line ${line.who}${line.final === false ? " progress" : ""}`, text: line.text }));
    body.append(lines);

    if (call.state === "live") {
      body.append(el("div", { class: `voice-state${voiceFailed ? " voice-error" : ""}`, text: voiceStatus, role: "status" }));
      if (call.choices?.length && call.lines.filter((l) => l.who === "user").length === 0) {
        const choices = el("div", { class: "choices" });
        for (const choice of call.choices) choices.append(button(choice, "secondary-button", () => window.talktome.say(call.id, choice)));
        body.append(choices);
      }
      const controls = el("div", { class: "actions" });
      controls.append(button(voice?.isMuted() ? "Unmute" : "Mute", "secondary-button", () => {
        if (!voice) return;
        voice.setMuted(!voice.isMuted());
        if (lastState) render(lastState);
      }));
      controls.append(button(showText ? "Hide text" : "Type instead", "secondary-button", () => {
        showText = !showText;
        if (lastState) render(lastState);
      }));
      controls.append(button("End", "primary-button end", () => window.talktome.hangUp(call.id)));
      body.append(controls);
      if (showText) {
        const input = el("input", { class: "say", type: "text", placeholder: "Type a message, then press Return", "aria-label": "What you say" });
        input.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" || !input.value.trim()) return;
          const text = input.value;
          input.value = "";
          drafts.delete(call.id);
          void window.talktome.say(call.id, text);
        });
        body.append(el("div", { class: "compose" }, input));
      }
    } else if (call.state === "calling") {
      body.append(el("div", { class: "actions" }, button("Cancel", "primary-button end", () => window.talktome.hangUp(call.id))));
    }
    return el("section", { class: `card ${call.state}` }, head, body);
  }

  window.talktome.onState(render);
  window.talktome.state().then(render);
  drafts = new Map();
})();
