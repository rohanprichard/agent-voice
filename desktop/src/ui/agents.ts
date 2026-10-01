// The agents window: the machines where agents run, setting them up, their
// projects, the speech key, and notices.

(() => {
  followTheme();
  const root = document.getElementById("agents")!;
  const hostNames: Record<string, string> = { claude: "Claude Code", codex: "Codex", hermes: "Hermes", openclaw: "OpenClaw" };
  let last: Snapshot | null = null;
  let sshHosts: string[] = [];
  let keyError = "";
  let speechKey = false;

  // The setup checklist that is open, if any.
  type Setup = { place: string; found: Inspection | null; busy: string; error: string };
  let setup: Setup | null = null;

  function render(state: Snapshot, force = false): void {
    last = state;
    speechKey = state.speechKey;
    if (!force && document.activeElement?.tagName === "INPUT") return; // do not wipe a form while the user types
    root.replaceChildren(...localView(state));
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
    if (state.speechKey) {
      panel.append(el("p", { class: "muted", text: "Your ElevenLabs key is saved in the keychain." }));
      panel.append(button("Remove the key", "ghost-button", () => void window.talktome.setSpeechKey("")));
      return panel;
    }
    panel.append(
      el("p", { class: "muted", text: "Calls are voice only. talktome uses your own ElevenLabs account to hear you and to speak the agent's replies. Add a key to make and answer calls." }),
    );
    const key = el("input", { type: "password", placeholder: "ElevenLabs API key", "aria-label": "ElevenLabs API key" });
    const save = button("Save", "primary-button", async () => {
      if (!key.value.trim()) return;
      save.disabled = true;
      save.textContent = "Checking…";
      keyError = await window.talktome.setSpeechKey(key.value);
      key.blur();
      rerender();
    });
    key.addEventListener("keydown", (event) => {
      if (event.key === "Enter") save.click();
    });
    panel.append(el("div", { class: "add-server" }, key, save));
    if (keyError) panel.append(el("p", { class: "error small", text: keyError }));
    panel.append(el("p", { class: "muted small", text: "Make a key at elevenlabs.io, in Developers > API keys. It needs speech to text and text to speech." }));
    return panel;
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
