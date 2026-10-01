// The agents window. On the first run it is a short setup: the speech key and
// a voice, this Mac, and a test call. After that it shows the machines where
// agents run, their projects, speech, and notices.

(() => {
  followTheme();
  const root = document.getElementById("agents")!;
  const hostNames: Record<string, string> = { claude: "Claude Code", codex: "Codex", hermes: "Hermes", openclaw: "OpenClaw" };
  let last: Snapshot | null = null;
  let sshHosts: string[] = [];
  let keyError = "";
  let keySaved = false; // the key was saved just now, so say so where it was typed
  let speechKey = false;
  let voices: Voice[] | null = null;
  let voicesError = "";
  let loadingVoices = false;
  let sample: HTMLAudioElement | null = null;

  // The first-run setup.
  const steps = ["Welcome", "Speech", "This Mac", "Test call", "Done"];
  let stage = 0;
  let testError = "";
  let testAsked = false;
  let trustPoll: number | undefined;

  // The setup checklist that is open, if any.
  type Setup = { place: string; found: Inspection | null; busy: string; error: string };
  let setup: Setup | null = null;

  function render(state: Snapshot, force = false): void {
    last = state;
    speechKey = state.speechKey;
    if (!force && document.activeElement?.tagName === "INPUT") return; // do not wipe a form while the user types
    root.replaceChildren(...(state.onboarded ? localView(state) : onboarding(state)));
    watchCodexTrust(state);
  }

  function rerender(): void {
    if (last) render(last, true);
  }

  function header(state: Snapshot): HTMLElement {
    const up = state.servers.filter((s) => s.state === "connected").length;
    const status = state.servers.length ? `${up} of ${state.servers.length} connected` : "No machines yet";
    return el("header", { class: "top" }, el("h1", { text: "talktome" }), el("span", { class: `pill-status ${state.connected ? "on" : ""}`, text: status }));
  }

  function localView(state: Snapshot): HTMLElement[] {
    // Calls are voice only, so the key comes first until it is saved.
    const parts = state.speechKey ? [header(state), machines(state)] : [header(state), speech(state), machines(state)];
    if (setup) parts.push(setupPanel(state, setup));
    parts.push(projects(state));
    if (state.speechKey) parts.push(speech(state));
    if (state.notices.length) parts.push(notices(state));
    return parts;
  }

  function machines(state: Snapshot): HTMLElement {
    const panel = el("section", { class: "panel" }, el("h2", { text: "Machines" }));
    panel.append(el("p", { class: "muted", text: "talktome reaches your agents on this Mac, and on servers over SSH. Nothing listens on the network." }));
    const local = state.servers.find((s) => s.id === "local");
    panel.append(machineRow("This Mac", local, local ? "" : "talktome-server is not installed here.", "local", false));
    for (const server of state.servers.filter((s) => s.id !== "local")) {
      panel.append(machineRow(server.label, server, "", server.id.replace(/^ssh:/, ""), true));
    }

    const input = el("input", { type: "text", placeholder: "user@host, or a host from your SSH config", list: "ssh-hosts", "aria-label": "SSH host" });
    const hosts = el("datalist", { id: "ssh-hosts" });
    for (const host of sshHosts) hosts.append(el("option", { value: host }));
    const check = button("Check", "secondary-button", () => {
      const host = input.value.trim();
      if (!host) return;
      input.blur();
      void openSetup(host);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") check.click();
    });
    panel.append(el("div", { class: "add-server" }, input, hosts, check));
    return panel;
  }

  function machineRow(label: string, server: ServerState | undefined, missing: string, place: string, removable: boolean): HTMLElement {
    const state = server?.state ?? "missing";
    const words: Record<string, string> = { connected: "Connected", connecting: "Connecting…", failed: "Not connected", missing: "Not set up" };
    const info = el("div", {}, el("div", { class: "project" }, el("span", { class: `dot ${state}` }), label), el("div", { class: "muted small", text: words[state] }));
    const problem = server?.state === "failed" ? server.error : missing;
    if (problem) info.append(el("div", { class: "error small", text: problem }));
    const actions = el("div", { class: "target-actions" }, button("Set up…", "secondary-button", () => void openSetup(place)));
    if (server?.state === "failed") actions.prepend(button("Retry", "ghost-button", () => void window.talktome.reconnect()));
    if (removable) actions.append(button("Remove", "ghost-button", () => void window.talktome.removeServer(place)));
    return el("div", { class: "target" }, info, actions);
  }

  async function openSetup(place: string): Promise<void> {
    setup = { place, found: null, busy: "Checking…", error: "" };
    rerender();
    const found = await window.talktome.inspect(place);
    if (setup?.place !== place) return;
    setup = { place, found, busy: "", error: "" };
    rerender();
  }

  async function step(busy: string, action: () => Promise<string | void>): Promise<void> {
    if (!setup) return;
    const place = setup.place;
    setup = { ...setup, busy, error: "" };
    rerender();
    const failed = (await action()) || "";
    const found = await window.talktome.inspect(place);
    if (setup?.place !== place) return;
    setup = { place, found, busy: "", error: failed };
    rerender();
  }

  function setupPanel(state: Snapshot, s: Setup): HTMLElement {
    const local = s.place === "local";
    const panel = el("section", { class: "panel setup" }, el("h2", { text: local ? "Set up this Mac" : `Set up ${s.place}` }));
    const list = el("ol", { class: "checklist" });
    const item = (done: boolean | null, label: string, ...rest: Array<Node | string>) =>
      list.append(
        el(
          "li",
          { class: done === null ? "waiting" : done ? "done" : "todo" },
          el("span", { class: "mark", text: done ? "✓" : "•" }),
          el("div", {}, el("div", { text: label }), ...rest),
        ),
      );
    const f = s.found;
    const busy = Boolean(s.busy);

    if (!local) {
      const failed = f && !f.reachable ? [el("div", { class: "error small", text: f.error })] : [];
      item(f ? f.reachable : null, f?.reachable ? "Connected over SSH" : "Connect over SSH", ...failed);
    }
    if (f?.reachable) {
      const uvSteps = f.uv
        ? []
        : [
            el("div", { class: "muted small", text: "This runs the official installer: curl -LsSf https://astral.sh/uv/install.sh | sh" }),
            button("Install uv", "secondary-button", () => void step("Installing uv…", () => window.talktome.installUv(s.place))),
          ];
      item(Boolean(f.uv), f.uv ? "uv is installed" : "Install uv, the Python tool installer", ...uvSteps);

      const serverButton = button(f.server ? "Update" : "Install talktome-server", "secondary-button", () =>
        void step("Installing talktome-server…", () => window.talktome.installServer(s.place)),
      );
      serverButton.disabled = !f.uv || busy;
      item(Boolean(f.server), f.server ? `talktome-server ${f.server} is installed` : "Install talktome-server", serverButton);

      if (f.server) {
        const agents = el("div", { class: "hosts" });
        if (f.hosts.length === 0) agents.append(el("div", { class: "muted small", text: "No Claude Code, Codex, Hermes, or OpenClaw found here." }));
        for (const h of f.hosts) {
          const name = hostNames[h.host] ?? h.host;
          const row = el("div", { class: "host-row" }, el("span", { text: name }));
          if (h.current) row.append(el("span", { class: "muted small", text: "Plugin installed" }));
          else {
            row.append(
              button(h.installed ? "Update plugin" : "Install plugin", "secondary-button", () =>
                void step(`Installing the ${name} plugin…`, () => window.talktome.installPlugin(s.place, h.host)),
              ),
            );
          }
          agents.append(row);
          if (h.host === "codex" && h.current && h.hooks_trusted === false) {
            agents.append(el("div", { class: "hint small", text: "Codex needs one step from you: open a new Codex session, type /hooks, and trust the talktome hooks." }));
          }
          if (h.host === "hermes" && h.current) agents.append(el("div", { class: "muted small", text: "Restart the Hermes gateway after an install: hermes gateway restart" }));
        }
        item(f.hosts.length > 0 && f.hosts.every((h) => h.current), "Add talktome to your agents", agents);
      }
    }
    panel.append(list);
    if (s.busy) panel.append(el("p", { class: "muted", text: s.busy }));
    if (s.error) panel.append(el("p", { class: "error", text: s.error }));

    const known = local || state.servers.some((server) => server.id === `ssh:${s.place}`);
    const actions = el("div", { class: "target-actions" });
    if (!known && f?.server) {
      actions.append(
        button("Connect", "primary-button", async () => {
          await window.talktome.addServer(s.place);
          setup = null;
          rerender();
        }),
      );
    }
    actions.append(
      button("Check again", "ghost-button", () => void openSetup(s.place)),
      button("Close", "ghost-button", () => {
        setup = null;
        rerender();
      }),
    );
    for (const b of actions.querySelectorAll("button")) b.disabled = busy;
    panel.append(actions);
    return panel;
  }

  function projects(state: Snapshot): HTMLElement {
    const panel = el("section", { class: "panel" }, el("h2", { text: "Projects" }));
    const online = state.agents.filter((a) => a.online);
    if (online.length === 0) panel.append(el("p", { class: "muted", text: "Connect a machine to see its Claude Code and Codex projects." }));
    for (const agent of online) panel.append(agentCard(agent));
    return panel;
  }

  function speech(state: Snapshot): HTMLElement {
    const panel = el("section", { class: `panel${state.speechKey ? "" : " required"}` }, el("h2", { text: "Speech" }));
    if (!state.speechKey) panel.append(el("p", { class: "muted", text: "Calls are voice only. Speech runs on your own ElevenLabs account." }));
    panel.append(...speechBody(state));
    return panel;
  }

  // speechBody is the key and the voice, for the Speech section and for setup.
  function speechBody(state: Snapshot): HTMLElement[] {
    if (state.speechKey) {
      const parts: HTMLElement[] = [];
      parts.push(el("p", { class: keySaved ? "saved" : "muted small", text: keySaved ? "✓ Key saved" : "Key saved in your keychain" }));
      parts.push(voicePicker(state));
      parts.push(
        el(
          "div",
          { class: "target-actions" },
          button("Remove the key", "ghost-button", () => {
            keySaved = false;
            voices = null;
            void window.talktome.setSpeechKey("");
          }),
        ),
      );
      return parts;
    }
    const key = el("input", { type: "password", placeholder: "Paste your ElevenLabs API key", "aria-label": "ElevenLabs API key", id: "speech-key" });
    const save = button("Save", "primary-button", async () => {
      if (!key.value.trim()) {
        keyError = "Paste a key first.";
        rerender();
        return;
      }
      save.disabled = true;
      save.textContent = "Checking…";
      keyError = await window.talktome.setSpeechKey(key.value);
      keySaved = !keyError;
      key.blur();
      if (last) render(await window.talktome.state(), true);
    });
    key.addEventListener("keydown", (event) => {
      if (event.key === "Enter") save.click();
    });
    const parts = [el("div", { class: "add-server" }, key, save)];
    if (keyError) parts.push(el("p", { class: "error small", text: keyError }));
    parts.push(el("p", { class: "muted small", text: "elevenlabs.io › Developers › API keys" }));
    return parts;
  }

  function voicePicker(state: Snapshot): HTMLElement {
    const box = el("div", { class: "voices" }, el("div", { class: "voices-title", text: "Voice" }));
    if (!voices && !voicesError) {
      void loadVoices();
      box.append(el("p", { class: "muted small", text: "Loading your voices…" }));
      return box;
    }
    if (voicesError) {
      box.append(el("p", { class: "error small", text: voicesError }), button("Try again", "ghost-button", () => {
        voicesError = "";
        rerender();
      }));
      return box;
    }
    const list = el("div", { class: "voice-list", role: "radiogroup", "aria-label": "Voice" });
    for (const voice of voices!) {
      const chosen = voice.id === state.voice;
      const row = el(
        "div",
        { class: `voice${chosen ? " chosen" : ""}` },
        el("button", { class: "voice-pick", type: "button", role: "radio", "aria-checked": String(chosen) }, el("span", { class: "voice-name", text: voice.name }), el("span", { class: "muted small", text: voice.description })),
      );
      row.querySelector(".voice-pick")!.addEventListener("click", () => void window.talktome.setVoice(voice.id));
      if (voice.preview) row.append(button("Play", "ghost-button", () => void play(voice.preview)));
      list.append(row);
    }
    box.append(list);
    return box;
  }

  async function loadVoices(): Promise<void> {
    if (loadingVoices) return;
    loadingVoices = true;
    try {
      voices = (await window.talktome.voices()).slice(0, 40);
    } catch (error) {
      voicesError = error instanceof Error ? error.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, "") : "The voices did not load.";
    }
    loadingVoices = false;
    rerender();
  }

  async function play(url: string): Promise<void> {
    sample?.pause();
    const data = await window.talktome.voicePreview(url);
    const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
    sample = new Audio(URL.createObjectURL(new Blob([bytes], { type: "audio/mpeg" })));
    void sample.play();
  }

  // The first-run setup

  function onboarding(state: Snapshot): HTMLElement[] {
    const local = state.servers.find((s) => s.id === "local");
    const dots = el("ol", { class: "dots", "aria-label": `Step ${stage + 1} of ${steps.length}` });
    steps.forEach((name, i) => dots.append(el("li", { class: i === stage ? "now" : i < stage ? "done" : "", title: name })));
    const page = el("section", { class: "onboard" });
    const next = (label = "Continue", enabled = true) => {
      const b = button(label, "primary-button wide", () => {
        stage += 1;
        rerender();
      });
      b.disabled = !enabled;
      return b;
    };
    const title = (text: string, line?: string) => {
      page.append(el("h1", { text }));
      if (line) page.append(el("p", { class: "line", text: line }));
    };

    if (stage === 0) {
      const canvas = el("canvas", { class: "motif", "aria-hidden": "true" });
      page.append(canvas);
      startMotif(canvas);
      title("talktome", "Your agents call you. You call them.");
      page.append(next("Get started"));
    } else if (stage === 1) {
      title("Your voice", "Speech runs on your own ElevenLabs account.");
      page.append(el("div", { class: "onboard-form" }, ...speechBody(state)), next("Continue", state.speechKey));
    } else if (stage === 2) {
      if (setup?.place !== "local") void openSetup("local");
      title("This Mac");
      page.append(macCard(setup));
      page.append(next("Continue", local?.state === "connected"));
    } else if (stage === 3) {
      const test = state.calls.find((c) => c.reason === "talktome test call");
      const passed = Boolean(test?.lines.some((l) => l.who === "user") && test.lines.some((l) => l.who === "agent" && l.text.startsWith("I heard you say")));
      title("Try a call", "Answer, say anything, and hear it back.");
      const ring = el("button", { class: "ring-me", type: "button", "aria-label": "Ring me" });
      ring.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1c0 .39-.23.74-.56.9-.98.49-1.87 1.12-2.66 1.85a1 1 0 0 1-1.41 0L.29 13.09a1 1 0 0 1 0-1.41C3.34 8.78 7.46 7 12 7s8.66 1.78 11.71 4.68a1 1 0 0 1 0 1.41l-2.48 2.48a1 1 0 0 1-1.41 0 12.3 12.3 0 0 0-2.66-1.85c-.33-.16-.56-.51-.56-.9v-3.1C15.15 9.25 13.6 9 12 9Z"/></svg>';
      ring.addEventListener("click", async () => {
        testError = "";
        testAsked = true;
        try {
          await window.talktome.testCall();
        } catch (error) {
          testError = error instanceof Error ? error.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, "") : "The test call did not start.";
        }
        rerender();
      });
      page.append(ring, el("p", { class: "small muted", text: passed ? "" : testAsked ? "Ringing at the top of your screen" : "Ring me" }));
      if (testError) page.append(el("p", { class: "error small", text: testError }));
      if (passed) page.append(el("p", { class: "saved", text: "✓ It works" }), next());
      else {
        page.append(
          button("Skip the test", "link", () => {
            stage += 1;
            rerender();
          }),
        );
      }
    } else {
      title("You're set");
      page.append(
        el(
          "ul",
          { class: "tips" },
          el("li", {}, el("span", { class: "muted", text: "Ask an agent" }), el("span", { text: "“Call me when you're done.”" })),
          el("li", {}, el("span", { class: "muted", text: "Call an agent" }), el("span", { text: "Menu bar icon, then a project" })),
        ),
        button("Done", "primary-button wide", () => void window.talktome.finishOnboarding()),
      );
    }
    const foot = el("footer", { class: "onboard-foot" });
    if (stage > 0) {
      foot.append(
        button("Back", "link", () => {
          stage -= 1;
          rerender();
        }),
      );
    } else foot.append(el("span"));
    if (stage < steps.length - 1) foot.append(button("Skip setup", "link", () => void window.talktome.finishOnboarding()));
    return [el("div", { class: "onboard-shell" }, dots, page, foot)];
  }

  // macCard is setup's view of this Mac: one row for each part, with its state
  // or its one action on the right.
  function macCard(s: Setup | null): HTMLElement {
    const card = el("div", { class: "mac-card" });
    const f = s?.found;
    const busy = Boolean(s?.busy);
    const row = (name: string, right: HTMLElement, note?: HTMLElement) => {
      const r = el("div", { class: "mac-row" }, el("span", { class: "mac-name", text: name }), right);
      card.append(note ? el("div", { class: "mac-item" }, r, note) : r);
    };
    const ok = (text = "Ready") => el("span", { class: "mac-ok", text: `✓ ${text}` });
    const act = (label: string, run: () => void) => {
      const b = button(label, "mac-act", run);
      b.disabled = busy;
      return b;
    };
    if (!f) {
      card.append(el("div", { class: "mac-wait", text: "Checking this Mac…" }));
      return card;
    }
    row("uv", f.uv ? ok() : act("Install", () => void step("Installing uv…", () => window.talktome.installUv("local"))));
    const server = f.server ? ok(f.server) : act("Install", () => void step("Installing talktome-server…", () => window.talktome.installServer("local")));
    if (!f.server && !f.uv) (server as HTMLButtonElement).disabled = true;
    row("talktome-server", server);
    if (f.server && f.hosts.length) {
      card.append(el("div", { class: "mac-group", text: "Agents" }));
      for (const h of f.hosts) {
        const name = hostNames[h.host] ?? h.host;
        const right = h.current ? ok("Added") : act(h.installed ? "Update" : "Add", () => void step(`Adding talktome to ${name}…`, () => window.talktome.installPlugin("local", h.host)));
        const trust = h.host === "codex" && h.current && h.hooks_trusted === false;
        row(name, right, trust ? el("span", { class: "mac-note", text: "One step in Codex: open a new session, type /hooks, and trust talktome." }) : undefined);
      }
    }
    if (s?.busy) card.append(el("div", { class: "mac-wait", text: s.busy }));
    if (s?.error) card.append(el("div", { class: "mac-error", text: s.error }));
    return card;
  }

  // The welcome screen draws the two threads from the call pill, taking turns.
  let stopMotif: (() => void) | null = null;
  function startMotif(canvas: HTMLCanvasElement): void {
    stopMotif?.();
    const start = performance.now();
    stopMotif = Threads.start(canvas, () => {
      const t = ((performance.now() - start) / 1000) % 6;
      return { user: t > 0.6 && t < 2.4, agent: t > 3.2 && t < 5.2 };
    });
  }

  // watchCodexTrust checks again every few seconds while setup waits for the
  // user to trust the Codex hooks, so the stage turns green by itself.
  function watchCodexTrust(state: Snapshot): void {
    const waiting = !state.onboarded && stage === 2 && setup?.found?.hosts.some((h) => h.host === "codex" && h.current && h.hooks_trusted === false);
    if (waiting && trustPoll === undefined) {
      trustPoll = window.setInterval(async () => {
        if (!setup || setup.busy) return;
        const found = await window.talktome.inspect(setup.place);
        if (setup) setup = { ...setup, found };
        rerender();
      }, 4000);
    } else if (!waiting && trustPoll !== undefined) {
      clearInterval(trustPoll);
      trustPoll = undefined;
    }
  }

  function notices(state: Snapshot): HTMLElement {
    const panel = el("section", { class: "panel" }, el("h2", { text: "Notices" }));
    for (const n of state.notices) {
      panel.append(
        el(
          "div",
          { class: "notice" },
          el("div", {}, el("strong", { text: `${n.from}: ${n.reason}` }), el("p", { text: n.message })),
          button("Dismiss", "ghost-button", () => window.talktome.dismissNotice(n.id)),
        ),
      );
    }
    return panel;
  }

  function agentCard(agent: Agent): HTMLElement {
    const card = el(
      "div",
      { class: `agent ${agent.online ? "online" : "offline"}` },
      el("div", { class: "agent-head" }, el("strong", { text: agent.name }), el("span", { class: "muted", text: agent.online ? "Online" : "Offline" })),
    );
    if (agent.online && agent.targets.length === 0) card.append(el("p", { class: "muted", text: "No projects yet." }));
    for (const target of agent.targets.slice(0, 12)) card.append(targetRow(agent, target));
    return card;
  }

  function targetRow(agent: Agent, target: Target): HTMLElement {
    const call = (mode: "join" | "continue" | "new") => () => window.talktome.callAgent(agent.agent_id, target.target_id, mode);
    const actions = el("div", { class: "target-actions" });
    if (target.joinable) actions.append(button("Join", "primary-button", call("join")));
    actions.append(button("Continue", "secondary-button", call("continue")), button("New", "ghost-button", call("new")));
    for (const b of actions.querySelectorAll("button")) {
      b.disabled = !agent.online || !speechKey;
      if (!speechKey) b.title = "Add your ElevenLabs key to make calls";
    }
    return el(
      "div",
      { class: "target" },
      el("div", {}, el("div", { class: "project", text: target.project }), el("div", { class: "muted small", text: `${target.host}${target.last_active ? " · " + when(target.last_active) : ""}` })),
      actions,
    );
  }

  function when(iso: string): string {
    const minutes = Math.round((Date.now() - Date.parse(iso)) / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes} min ago`;
    if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
    return new Date(iso).toLocaleDateString();
  }

  window.talktome.onState((state) => render(state));
  window.talktome.state().then((state) => render(state));
  window.talktome.sshHosts().then((hosts) => {
    sshHosts = hosts;
    rerender();
  });
})();
