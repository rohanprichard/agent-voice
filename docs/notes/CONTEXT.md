# Current context

## Source update: September 28, 2026

[Call latency](../LATENCY.md) describes early transcription commits, the separate speech worker, and output connection reuse.
The Codex reader now uses file notifications with polling as a fallback.
Private timing records remain available after calls through `/v1/call/timings`.
These changes need normal call measurements. No app build or calls ran for this change.

## Source update: September 27, 2026

[Agent support](../AGENT_SUPPORT.md) describes the new connections and interruption behavior.
The Codex queue now uses a persistent proxy. Claude and other hosts can use cooperative commands.
Hermes and OpenClaw have experimental adapters for existing API or Gateway sessions.
The new paths still need live checks. No real calls ran during this change.
The approved native notch surface remains unchanged.
[Smart Turn](../SMART_TURN.md) now checks pauses beside live transcription.
It defaults to on, downloads a pinned local model, and falls back to the pause rule if unavailable.


## Where it stands: September 25, 2026

**The product is a front end for a session that is already running.** You ask your
agent to talk to you, it rings, you answer, and the conversation happens out loud in
the session you were already in — same model, same tools, same history, same
terminal. TalkToMe does not start sessions for you.

After setup, TalkToMe waits in the menu bar. A small window below the menu bar
shows setup. The main window shows Settings. The agent starts each call.
The floating pill shows the active call and the transcript. Closing Settings hides
the window and keeps the app alive.

The setup window has six steps: welcome, microphone, ElevenLabs key, agent skill,
glow color, and final instructions. The user can set up speech later. The local
Customize opens Settings, and closing Settings returns to the same setup step.
The chosen color stays in local storage and colors the Settings glow.
The setup window does not draw a second notch.

Settings offers two call surface placements: Bottom and Top center. The default is
Bottom. Top center uses `display.workArea` and sits below the menu bar. Electron
reports no camera housing geometry, so the app does not infer a physical notch. At
Bottom the transcript opens above the pill. At Top center the transcript opens
below the pill.

The connection step shows a sample call. The sample call is a demo. It teaches
the Answer and End controls. It does not start a real call, and it sends nothing
to the server. The final setup button closes setup.

### The flow, end to end

1. The agent runs `talktome call --thread "$CODEX_THREAD_ID" --greeting "…"`.
   The skill it learned this from is installed from the connection screen, which also
   puts the `talktome` command on the agent's PATH. If the app is closed, the command
   starts it. The app uses the Codex session name for the call. The `--name` option is a fallback.
2. The request travels as a **file**, not a network call: the command writes it where
   the app is watching and the app writes its answer beside it. The app's own folder
   when a sandbox allows the write, and `/tmp/talktome-<uid>/requests` when it does
   not — Codex's sandbox permits its workspace and the temporary folder and nothing
   else. This is why the path works at all: the sandbox blocks connections to
   `127.0.0.1` *and* writes outside those two places.
3. The pill appears at the bottom of the screen showing a bell, the name, and two
   buttons: Decline and Answer. A macOS notification also shows the name. It rings
   for 30 seconds and then stops on its own. The greeting audio is made while it
   rings, and it plays once you answer.
4. You speak. The app delivers it into the thread with `codex queue` and reads the
   agent's reply out of the thread's rollout file. Both threads in the pill follow
   who is talking.
5. `talktome end` hangs up from the terminal, with no call identifier to look up.
   The pill's red button does the same.

Codex allows **one writer per thread**, and the terminal keeps it. That is why the
app queues rather than starting turns, and why it cannot interrupt the agent's work —
the one place attachment differs from a managed call, which does interrupt.

With ElevenLabs speech input, the app sends audio to Scribe Realtime during speech.
The call transcript shows partial text. The app sends only the committed text to
Codex after the pause rule ends the turn. If live speech input fails, the app uses
the saved audio with the batch path. Whisper still uses the batch path.

### How to build and install it

```sh
npm run build:app     # freeze the server, draw the icon, bundle, verify, make a DMG
npm run build:dmg     # same, reusing the last frozen server (about a minute faster)
```

The result is `dist/app/TalkToMe-<version>-arm64.dmg`: open it, drag TalkToMe to
Applications. The build mounts its own image and reports what is inside, because an
image that builds and will not open is invisible in a filename.

The frozen binary can be asked what it can do:

```sh
"/Applications/TalkToMe.app/Contents/Resources/talktome-server/talktome-server" --selftest
```

It reports the keychain, the inbox, the presence lock, and whether the `talktome` command
is in the bundle at all — the things that only exist at runtime, and that no test in the
checkout can prove.

That binary is **two programs in one file**. It is the server the app runs, and it is the
`talktome` command an agent runs; a bundle has no interpreter inside it, so `-m talktome`
is honoured by the binary itself. `npm run build:app` fails the build unless the frozen
binary can answer as the command, and the attach smoke test can be pointed at a built
bundle rather than a checkout:

```sh
TALKTOME_COMMAND="dist/app/mac-arm64/TalkToMe.app/Contents/Resources/talktome-server/talktome-server -m talktome" \
  npm run test:attach-call
```

### Known limitations, all of them deliberate or understood

- **Unsigned.** It opens on the machine that built it, because a locally built image
  is never quarantined, and will not open on anyone else's. Notarizing needs a paid
  Developer ID certificate. The machine has an Apple Development certificate, which
  cannot notarize.
- **Unsigned has a second cost: the keychain.** Every rebuild is a different
  application to the keychain, so an item an earlier build stored reads as somebody
  else's and is refused with `-25244`. `configure` clears the item before writing so
  it self-heals, but the underlying cause goes away only with a stable signature.
- **A ring cannot be dismissed.** Ten seconds is the whole window to notice it; if it
  arrives while you are busy, you wait it out.
- **Codex only.** Claude Code has the same one-writer constraint and its own
  transcript format, and has not been done.
- **The MCP tools are not in the frozen build.** `talktome.mcp_server` imports `mcp`,
  which PyInstaller will not freeze cleanly here, so it is deliberately left out. The
  connection screen still offers it, and in a bundled install it will not work. Nothing
  in the current flow uses it.
- **Some packaging defects are still invisible to the suite.** The build now refuses a
  bundle whose command cannot run, and the smoke test can drive a built binary, but
  anything that only appears from a window, a permission prompt, or an install has to
  be found by installing the image and using it. Every such defect so far — a missing
  skill file, a PATH that belonged to the launcher rather than the user, a keychain item
  owned by a previous build, a command that was not a command — was invisible to a suite
  of 223 tests, because the tests run where everything the code needs is present.

### Ways in that still exist but are not the product

The MCP tool servers (`talktome_connect`, `talktome_listen`, and the rest) are the
older design, where an agent connects to the app and waits. Nothing in the current
flow uses them: `managed.py` and `attach.py` contain no reference to MCP at all. They
are installed from a disclosure on the connection screen. Managed sessions — the app
starting Codex or Claude itself — still work and are still tested, but their card is
hidden, because the product is joining a session rather than starting one.

## Latest decision: September 24, 2026 — join the user's session

TalkToMe joins a session the user already has, rather than starting one of its own.
The session is the state. The app holds no conversation state, and divergence between two writers is accepted.
Either side can start a call: the agent can call the user, and the user can call the agent.
Recent sessions, grouped by project, are the discovery surface, and the user chooses one.
Codex is the first host. Every agent harness is a target.
A call ends in the floating pill from `canvas-first.png`.
See [the roadmap](ROADMAP.md) for the transport findings and the compliance limits.

MCP is pull-only, so it cannot push a user message into a running agent.
It stays as the portable path for clients with no resumable session.
Codex exposes an app server with `thread/list`, `thread/resume`, `turn/start`, and `turn/interrupt`,
so the app can drive the same thread without polling.

## Earlier decision: September 24, 2026 — managed sessions

Superseded as the primary path and kept as a mode.
Subscription credentials must not be routed through the Claude Agent SDK; see the roadmap.
The user requested research on connection overhead and missing spoken progress, using `test_run/transcript_codex.md`.

The [agent connection research](research/AGENT_CONNECTION_OPTIONS.md) records the findings and proposed tests.
The project approved implementation for Codex and Claude after that research.
The managed adapters (since removed) now receive public host output and send it to the transcript and speech queue.
Codex keeps one App Server thread. Claude resumes one host session through a new SDK transport per turn.
Managed progress does not consume the final reply slot. The earlier external tool path still permits one reply per turn.
The live Codex test passed context recall, a fixture read, and audio generation with `gpt-6-luna`.
Claude passed mocked tests, but its live test stopped because its OAuth session expired.
Run `claude auth login` before another live Claude test.
Native attachment to an existing terminal and connection restoration after application restart remain future work.

## Visual decision: September 23, 2026

The project selected `design/concepts/canvas-first.png`, including its neon accents and blue surfaces.
After setup, the main app is a floating pill over the user's screen, similar to HeyClicky.
It is not the large Canvas window shown in the concept image.
Settings opens a larger window. The transcript remains accessible, but its expanded layout is undecided.
Two audio wave lines replace the icon and `Agent connected` label in the pill.
One line follows user microphone audio. The other follows agent reply audio.
Ivory and Ink remain historical alternatives, not the selected palette.

The agent interface is the next and most important priority.
The user requested that these decisions be stored before a discussion of that interface.
Visual implementation waits for the agent-interface work.
The current app still has a fixed sidebar from the later functional work.
This design review did not change interface code or saved user settings.

The [roadmap](ROADMAP.md) records the decisions, concept images, review evidence, future features, and next steps.
Read it before new interface work.
Screen capture, annotations, cursor overlays, and controlled actions remain future work.
The headless service remains a requested future direction.

## Earlier requirements

The user changed the product direction on September 22, 2026.
The active goal is a local desktop app where an existing agent can listen and speak.
The project selected a desktop app instead of a browser product.
The implementation uses Electron with a local Python server.

The user requested a single conversation view with a visible transcript and no sidebar.
Speech and voice selection belong in Settings. The conversation links to the agent connection view.
The user requested downloadable Kokoro voices and ElevenLabs key entry.
The final choice includes ElevenLabs for both recognition and voice output. Whisper remains the default for recognition.
The user requested microphone permission during setup, compact clipboard controls, a connection page without scrolling, and dark mode.
The earlier external connection requires a listen-and-reply tool loop. Managed Codex and Claude sessions no longer require that loop.

Different agents must connect through a shared interface.
Model Context Protocol (MCP), HTTP, and a JSON Lines bridge serve that requirement.
The app does not contain a separate reasoning agent or require a language-model provider.

The user named AgentCall and SKI as references. The user named HeyClicky as the longer-term direction for screen guidance and drawing.
The user also requested research on Jev for fast screen decisions.
The research is in [research/WORLD_MODELS.md](research/WORLD_MODELS.md).

Current source and behavior take precedence over the historical briefs in `archive/`.
The old instruction to fork SpeakType is no longer the active implementation plan.
No source code from SpeakType, AgentCall, SKI, or HeyClicky is included in this build.
