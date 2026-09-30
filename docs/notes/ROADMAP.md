# TalkToMe roadmap

Where the product stands today, how to build it, and what is known to be
limited: [CONTEXT.md](CONTEXT.md). This file is the decision record — what was
chosen, and what was rejected in favour of it.

Updated: September 28, 2026.

## Agent connections and speech control

The source now includes cooperative commands, experimental external adapters, and a persistent Codex queue.
The playback report helps an agent handle speech that the user interrupted.
[Agent support](../AGENT_SUPPORT.md) defines the supported modes and their limits.

Remaining work:

1. Check each external adapter with a configured host.
2. Measure committed text to queue acceptance and rollout acceptance in a real call.
3. Check interruption recovery with speakers and headphones.
4. Check the new Pipecat Smart Turn integration beside live transcription.
5. Check Smart Turn with published real recordings, then normal calls.

[Smart Turn](../SMART_TURN.md) now retains the recording when speech resumes.
It needs no new training dataset.
Do not send partial transcript text into a host queue that cannot replace that text.


## Call surface integration: September 26, 2026

This decision replaces the attached call panel in the earlier notch design.
Keep the current notch glow. Put the controls in a separate black pill below the glow.
The pill starts 64 pt below the measured camera depth. Its center follows the camera center.
It uses 96% opacity, with no glow around its border.
The connected pill measures 280 by 56 pt. Its buttons measure 30 by 30 pt.
The incoming pill measures 320 by 64 pt. AppKit points define the sizes, not screenshot pixels.

### Current source

The silent preview and production helper share `native/NotchGlow.swift`.
The helper now draws the glow and pill in separate native panels.
Electron already sends call state to the helper and receives button actions.
The build script already includes the helper in the app.
These connections still need examination in the built app.
The app sends the call identifier and start time to the helper for its timer.
The silent preview uses a local timer.
The pill supports dragging by its background or timer. The transcript supports dragging by its header.
Each surface keeps its own position. The notch glow stays fixed.

### Integration steps

1. Send the call identifier and accepted time from Electron to the helper.
2. Use the accepted time for the timer, including after a helper restart or display change.
3. Keep Electron as the source of call state and audio playback.
4. Connect Answer, Decline, Mute, End, and Transcript to the existing call commands.
5. Suppress the old Electron pill only after the native helper reports that its panels are ready.
6. Restore the fallback controls if the helper stops or cannot find a suitable display.
7. Keep one ringtone owner, with a timeout and immediate stop after answer, decline, or end.
8. Place the transcript below the pill with a clear gap.
9. Keep the transcript movable and resizable.
10. Clear the transcript when a new call starts.
11. Update both panel positions after display or resolution changes.
12. Build the full app after the user accepts the preview size and placement.

### Release checks

Examine the built app with the user. Do not start unsolicited calls.

- One visible set of controls for each call.
- Incoming, connected, speech, thinking, mute, and end states.
- Correct timer after repeated calls and helper restart.
- No keyboard focus change when a call arrives.
- Clicks pass through the empty space around both panels.
- Transcript controls work without the old Electron pill.
- Correct position on scaled displays, full-screen Spaces, and external displays.
- Fallback controls remain available on screens without a notch.

The integration steps are implemented. The release checks still need user examination.
The standalone glow source is in `../notch-glow`, with its own Git history and Finder app bundle.

## Notch design: September 25, 2026

The supplied design makes the top center of the screen the visual home for calls.
The setup panel starts below the menu bar. A soft glow fades into its dark top edge.
The menu bar item remains the way to open Settings.

Electron does not give the app the camera housing shape or size. The app will center
the setup surface on the display and place it at the top of the usable screen area.
The surface must fit screens with and without a camera housing. It must not cover
the camera area or assume a fixed notch width.

The setup panel does not draw a second notch. Settings uses the same dark surface
and selected glow color. Keep the Electron app for these windows and the call logic.
If a later design needs the camera housing outline, use a small AppKit bridge to
read the screen safe area. Do not rewrite the full app in Swift for this purpose.

### Setup order

1. Show a short welcome in the notch panel.
2. Ask for microphone access. Show the current permission state.
3. Ask for an ElevenLabs API key. Store it in the system keychain when the system permits it.
4. Install the TalkToMe skill and command for the agent.
5. Let the user choose a glow color.
6. Close setup with the instruction to ask the agent to call.

The user can set up speech later. Settings keeps local recognition and voice choices.
The setup panel links to Settings for those choices. A missing key must not appear as
ready speech in setup.

### Call surface plan

| State | Surface behavior |
| --- | --- |
| Idle | Keep only the menu bar item visible. |
| Hover | Show a thin glow at the top center. |
| Incoming call | Grow a small panel with the agent name and answer control. Stop the ring after its time limit. |
| Connected | Keep the transcript, microphone, and end controls in a compact panel. |
| User speech | Use a soft white pulse on the edge. |
| Agent speech | Use an amber pulse on the edge. |
| Agent work | Use a slow violet pulse on the edge. |
| Muted | Mark the microphone control as muted. |
| End | Contract the panel and stop its audio. |

Keep the transcript in a separate window that the user can move and resize.
The selected glow color is the neutral accent. State colors take priority while a
call changes state. The end control must stay small enough for the compact panel.
The setup work comes first. Inspect screenshots at each setup step before work on
the call surface.

This document is the current product roadmap and decision record.
Current source and observed behavior define what works today.
Concept images show proposals, not implemented features.
The project selected `canvas-first.png`, including its neon and blue visual direction.
The main interface will be its floating pill, not the large window shown around it.
The agent-interface review now takes priority over visual implementation.
The project selected **session attachment** first: TalkToMe joins a session the user already has.
Managed sessions remain available as a mode, not the primary path.

## Product direction

TalkToMe gives an existing agent a voice and a shared visual work area.
The agent keeps its reasoning model, tools, and project context.
The app handles speech, transcripts, and explicit access to screen content.
The user can speak or type in the same conversation.

The desktop app remains the main product.
After setup, a compact pill overlays the user's desktop, similar to HeyClicky.
The user's existing applications remain the work area. A large Canvas window is not the default interface.
Settings opens a larger window.

## Latest decisions: session attachment

September 24, 2026. These supersede the earlier managed-session-first order.

TalkToMe joins a session the user already has, rather than starting one of its own.
The user is often mid-conversation in a terminal. The app becomes a voice front-end to that session
and a tool the agent can use, and the session remains the state.

| Topic | Decision |
| --- | --- |
| Session ownership | TalkToMe joins the existing session. The app holds no conversation state |
| Identity | The app works against the host's own session identifier, so both sides see one thread |
| Initiation | Either side. The agent can call the user, and the user can call the agent |
| Trigger | A TalkToMe skill installed into the host. The agent runs a command that rings the app |
| Greeting | The agent supplies it. The call command carries the agent's first spoken message |
| Discovery | Recent sessions, grouped by project, chosen by the user |
| Divergence | Accepted. Two writers to one session may diverge, and nothing is reconciled |
| Host order | Codex first. Claude, DeepSeek Harness, and other clients follow |
| Call end state | The floating pill from `canvas-first.png`: mute, wave lines, agent state, end call |
| Managed sessions | Kept as a mode, no longer the primary path |

### Transport findings

MCP is pull-only. A tool server cannot push a user message into a running agent, so an MCP
conversation requires the agent to block inside a tool call. That is portable and it works, but it is
verbose, and the agent's turn never ends while a call is open.

Measured from [the Codex transcript](test_run/transcript_codex.md): four user utterances cost sixteen
tool calls, and seven of sixteen returns carried only the agent's reply echoed back to it.
Roughly 1,670 tokens of tool traffic for a four-line conversation.

The command's own way in is not a socket either. It was, and the result was a second copy of the app
started on a port the first one already held, because a sandboxed command cannot open a loopback
connection to an app that is plainly running. It is now a file the app watches in its own data folder,
and the app announces itself with a lock rather than an answer on `127.0.0.1`.

The same symptom had a second, larger cause: the frozen binary serves the app *and* is the `talktome`
command an agent runs, and the first bundle left the command out of the archive entirely, so every
call started a second server. `npm run build:app` now fails if the built binary cannot answer
`-m talktome connection`, and `TALKTOME_COMMAND` points the attach smoke test at a built bundle. See
[CONTEXT.md](CONTEXT.md) and the work log for September 25.

Two mechanisms replace it as the primary path:

- **Drive the host's own interface.** Codex exposes an app server whose thread can be resumed, so the
  app can start turns against the same thread without polling. The app pushes; nothing listens.
- **Start the call from a skill or plugin the app installs into the host.** Both hosts support these:
  Codex reads `~/.codex/skills` and has `codex plugin`, and Claude Code reads `~/.claude/skills`,
  plugins, and commands. The skill teaches the agent when to start a call and which command to run.
  Skills load when a session starts, so a skill installed mid-session applies to the next one.
Watching the session store for a trigger phrase was considered as the way to cover a session that
predates the install. It is not needed: setup says to restart the session once after installing the
skill, and the skill covers every session after that.

### Codex has one writer per thread

Measured with [`scripts/attach_smoke.py`](../../scripts/attach_smoke.py) against Codex CLI 0.156.1:

| Check | Result |
| --- | --- |
| `thread/list` filtered by project folder finds a thread | Pass |
| `thread/resume` while another process holds the thread | **Fail: "already has an active writer"** |
| `thread/resume` after the writer releases the thread | Pass |
| `codex queue --thread <id> --message <text>` into a held thread | Pass |
| The thread's rollout file records the turn | Pass |

A thread has exactly one writer, and `thread/resume` claims it. There is no subscribe method, so a
reader cannot attach without becoming the writer. This decides the design:

- **While a terminal session is live it stays the writer.** The app pushes speech with
  `codex queue` and reads replies from the thread's rollout file. The app never resumes a live thread.
- **Once the thread is released the app can resume it** and start turns itself.

Model-dependent checks were blocked during the run because the signed-in account had reached its
usage limit. Reply streaming, context recall, the agent's `CODEX_THREAD_ID` value, and whether a
non-writing connection can read a held thread's history still need a run with available quota.

Codex also exposes `codex queue --thread <id> --message <text>`, which delivers a message to an
existing session from a separate process. That is the push primitive: the app can send a transcript
without owning a turn and without polling.

MCP stays as the portable path for clients with no resumable session. It is worth fixing regardless:
stop echoing the agent's own events, return only the text and the turn, and combine listen and speak.

### Compliance

Subscription authentication decides what is permitted, and it changes the design.

Anthropic states that OAuth authentication is intended for ordinary use of Claude Code and other
native Anthropic applications, and that developers using the Agent SDK should authenticate with an
API key. Anthropic does not permit third-party applications to route requests through Free, Pro, or
Max credentials. The same page permits an end user to sign in to the unmodified Claude Code binary
with their own subscription.
[Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)

OpenAI documents two sign-in methods and directs programmatic Codex CLI workflows to API keys. No
explicit prohibition on a local client of the user's own CLI was found, and the terms page was not
reachable for confirmation.
[Codex authentication](https://learn.chatgpt.com/docs/auth)

Consequences:

- The managed Claude adapter must not use the Agent SDK with subscription credentials. It remains
  available for API keys only.
- Driving the vendor's own binary with the user's own credentials is the permitted path, and it is
  also the path this roadmap now prefers.
- TalkToMe must not collect, store, or intermediate a Claude account credential or session token.

### Speech streaming

Generating a reply takes time, and speaking it only once the whole reply exists adds that delay to
the first sound the user hears. Speech has to start on the first complete phrase.

What already exists: the managed path buffers agent text into sentences, queues each sentence for
synthesis, and the renderer plays the audio chunks in order with duplicate suppression and
cancellation. A later sentence is synthesized while the previous one plays.

What is missing: the ElevenLabs path synthesizes one whole sentence per blocking HTTP request, and
decodes the entire response before any audio exists.

Status: built. `src/talktome/streaming.py` holds `ElevenLabsStream`, `WordBuffer`, and `pcm_to_wav`.
`Speech.open_stream` returns a stream only when the provider is ElevenLabs and a key exists, so every
other engine keeps the sentence path. `ManagedSession` prefers the stream, and falls back to
sentences when `start()` fails. Interrupt-first already held for managed turns before this work:
`CodexAdapter.run` sends `turn/interrupt` when its consumer is cancelled, covered by
`test_codex_cancellation_interrupts_the_turn` and four sibling tests, and a cancellation now reaches
`ElevenLabsStream.abort`, which closes the socket so generation stops rather than only playback.

Two provider rules were measured, not assumed:

- **Text must end at a word boundary.** ElevenLabs reads the trailing space as the cue, so raw model
  deltas corrupt words (`"con"` + `"nect"` would be spoken as two words). `WordBuffer` holds text
  back to the last space. `SentenceBuffer` strips whitespace, so the managed path puts the boundary
  back before pushing.
- **A dead socket must not kill the turn.** The first audio probe against the real endpoint with a
  deliberately invalid key returned `1008 Invalid API key`, which confirmed the URL, the
  `xi-api-key` header, and `output_format=pcm_24000` are all accepted. The failure is recorded on the
  stream, logged, and reported on the turn as `The streaming voice stopped. <reason> The text is in
  the transcript.` An intentional abort is not treated as a failure.

Still deferred: gapless playback between chunks. The attach path (slice 1) must send `turn/interrupt`
for the running turn before it pushes with `codex queue`; the queue command does not interrupt on its
own.

Clause-level chunking for local engines now ships: `SentenceBuffer.feed(..., clauses=True)` cuts the
first chunk of a turn at a clause of at least 24 characters, then returns to sentence cuts so the
extra request is paid once. A streaming provider is never cut at clauses, since it chunks internally.

Connectors are removable. `agents.uninstall` mirrors `agents.install` through each client's own
command, `POST /v1/agents/{id}/uninstall` reports the new state, and removal is idempotent. This also
fixed a real survey defect: the stored interpreter path was compared as text, so `python` and
`python3` in one virtual environment were treated as different interpreters and an installed server
was reported as absent.

Decisions:

- **Interrupt, do not queue.** When the user speaks during a turn, the app requests cancellation of
  the agent's turn before it sends the new message. Queueing alone would leave the user talking into
  a waiting queue, which reads as the app being stuck.
- **ElevenLabs uses its WebSocket API.**
  `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input` accepts partial text and returns
  audio chunks as they are generated, which matches token streaming from an agent.
- **For that provider, ElevenLabs is the buffer.** Its `chunk_length_schedule` already decides when to
  generate audio from partial text, so the sentence buffer must not double-buffer. Its default is
  `[120, 160, 250, 290]`: the first audio waits for 120 characters. Lower it for conversational
  replies, trading a little quality for a much shorter first-audio delay.
- **Local providers stay sentence-chunked, and also split on clause boundaries.** Kokoro and system
  speech have no incremental interface, so chunk size is the only lever, and a shorter first chunk
  means a shorter wait.
- **No new WebSocket between the renderer and the local server.** That hop is loopback, where a chunk
  fetch costs about a millisecond. The latency worth removing is between the server and the provider.

### Floating call surface

Status: first milestone built. `desktop/geometry.cjs` computes the pill's bounds
from the display work area, `desktop/main.cjs` owns the frameless transparent
window, the menu bar item, and the show/hide handover, and `static/call.html`,
`call.css`, `call.js`, and `threads.js` are the surface itself. `npm run test:call`
verifies the window behaviour against the real application; `npm run test:desktop`
runs with `TALKTOME_FLOATING_CALL=0` because it drives the in-window controls.

Decisions taken with the user before building:

- **No React, no bundler.** The brief specifies React and Motion; this renderer is
  dependency-free ES modules with no build step, and the pill follows it. Canvas is
  the brief's own choice for the threads, and the handful of interface transitions
  it assigns to Motion are CSS. Two frontends and two toolchains were not worth
  six transitions.
- **The main window hides during a call, and a menu bar item brings it back.**
  Hiding is what makes the surface feel like part of the system rather than a
  window; the menu bar item is what keeps Settings reachable.
- **The hidden window keeps owning the call.** The pill is a view and a remote
  control, so the microphone, the agent session, and playback are untouched by it.
  This is why the main window needs `backgroundThrottling: false`.
- **Agent audio moves to Web Audio in the next pass**, which supplies the pink
  thread's real level and retires the deferred gapless playback item together.

The threads are two continuous lines, never a waveform, a row of bars, or a
spectrum. A speaking thread rises quickly and settles slowly; a silent thread
keeps a small breath, small enough that it can never read as speech. The
connecting state is carried by the lines rather than a label, and the only text
the pill shows during a normal call is the two button labels.

Real audio now drives both threads. `static/player.js` plays the agent's speech
through Web Audio so an `AnalyserNode` can measure it, the hidden window pushes both
levels to the surface about thirty times a second, and each thread recedes while the
other speaks. Scheduling every chunk at the previous chunk's end also answers the
deferred gapless playback item: the pieces of a streamed reply are continuous, where
before each one rebuilt a media pipeline. One rule about a level's range lives in
`normalizeLevel`, and the surface publishes `data-speaker` so the whole path can be
observed from outside.

Motion is part of the motif rather than decoration. Each thread's speed follows its
own level, so it hurries while its side is talking and drifts when it is not, and the
two travel in opposite directions. Amplitude alone was not enough: a line that swells
but keeps its pace reads as a display rather than a voice. The wrap point of the
phase is 200π, which is a whole number of periods for all three sine components in
`wave`, so the loop never produces a visible jump.

The pill is 340x56, and the window is the pill plus a 10px ring for its drop shadow
and nothing more: transparent pixels still take the mouse, so a window larger than
the pill swallows clicks meant for whatever is underneath. The material is opaque,
the controls are icon only with their names on `aria-label`, and the window is
movable with the position remembered, so opening the transcript grows upward from
where the user left it rather than resetting to the centre of the display.

Still to do on this surface: choosing which display it appears on, a way to send it
back to the bottom centre after dragging, and a Settings switch in place of the
`TALKTOME_FLOATING_CALL` environment variable.

## Decisions from the design review

| Topic | Decision or status |
| --- | --- |
| Main layout | Floating desktop pill from `canvas-first.png`, available after setup |
| Work area | The user's existing screen, not a required large app window |
| Palette | Neon accents and blue from the first Canvas concept |
| Visual character | Elegant, polished, restrained, and distinctive |
| Permanent sidebar | Remove from the proposed main layout |
| Transcript | Preserve access from the pill. Exact expanded behavior remains undecided |
| Voice controls | Keep together in one compact dock |
| Audio display | Two separate wave lines replace the icon and `Agent connected` label |
| Wave sources | One line follows user microphone audio. One follows agent reply audio |
| Empty state | Fit the content, without a large unused transcript area |
| Settings | Opens a larger window for speech providers, appearance, and advanced options |
| Agent connection | Keep accessible from the main view |
| Appearance | Keep System, Light, and Dark options |
| Screen features | Future work, not part of the current voice implementation |
| Code reuse | Examine source and licenses before copying code |
| Immediate priority | Review the agent-interface findings before visual implementation |
| Session ownership | Superseded September 24: join the user's existing session first, managed sessions as a mode |
| Implementation | Superseded September 24: managed adapters exist, but the Agent SDK path cannot use subscription credentials |

The user requested a premium appearance, not a generic chat interface.
Proposed details include fine borders, precise typography, blue surfaces, and controlled neon accents.
The serif type applies to selected titles, not every control.
Avoid large glowing orbs, heavy glass effects, promotional text, and decorative panels.
The earlier suggestion to avoid neon is superseded by the user's explicit preference for the first Canvas concept.

## Current implementation

The current app uses Electron with a local Python server.
It has a fixed sidebar, a conversation view, Settings, and an agent connection view.
The sidebar shows the current conversation. A persistent conversation library is not implemented.

Speech options include local Whisper recognition, system voices, downloadable Kokoro voices, and optional ElevenLabs recognition and voice output.
First-time setup covers speech and agent connection.
The app supports microphone permission, native clipboard controls, and three appearance options.

Agents connect through Model Context Protocol (MCP), HTTP, or a JSON Lines bridge.
The connection view can register the tools with supported agent clients.
External agents must still execute the listen-and-reply loop.
Tool registration alone does not prove that an agent will remain active.

Managed Codex and Claude sessions exist and work, but they are no longer the main connection path.
They remain a mode for users who want TalkToMe to own the session, and they are subject to the
compliance limits above.
The managed-session guide (since removed) records implementation details and test limits.
Session attachment is not implemented. The app cannot yet join a session that is already running.

Screen capture, browser control, screen annotations, and a cursor overlay are not implemented.
The current voice path does not require these features.
See [the work log](WORK_LOG.md) for earlier functional changes and tests.

## Review evidence

The September 23 review started the current Electron app and examined its main view, Settings, and agent connection.
A separate temporary instance showed first-time setup without resetting the user's saved settings or models.
Both instances showed content without browser errors during this review.
This was a visual review, not a new end-to-end voice test.

- [Current main view](design/review/current-room.png)
- [Current first-time setup](design/review/current-onboarding.png)
- [Current agent connection](design/review/current-connection.png)

The review found three design problems.
The sidebar reserves space for an unfinished library.
The empty conversation area gives little purpose to the available space.
Setup asks for technical choices before it demonstrates a spoken exchange.

## Concept record

The first concepts were Companion, Studio, and Canvas.
The project selected Canvas because it supports future screen guidance and control.
The user then selected the first Canvas image over the Ivory and Ink variations.
Its bottom pill becomes the entire everyday interface, not an optional compact mode.
The large surrounding window in the image does not define the main app layout.

| Concept | Purpose | Status |
| --- | --- | --- |
| [Canvas, first version](design/concepts/canvas-first.png) | Floating pill, blue surfaces, and neon accents | Selected reference, with two audio waves |
| [Canvas / Ivory](design/concepts/canvas-ivory.png) | Ivory, espresso, and muted oxblood | Historical alternative, not selected |
| [Canvas / Ink](design/concepts/canvas-ink.png) | Deep ink, ivory, and muted champagne | Historical alternative, not selected |

The earlier proposal to pair Ivory and Ink is superseded.
Light and dark appearance still need specifications based on the selected visual direction.
Generated images contain illustrative page text and icons. They are not exact implementation specifications.
The browser capture in each image is future content, not an implemented embedded browser.
Neon annotations need contrast tests on both light and dark screen content.

The built-in image generator created these previews.
The [saved prompts](design/CONCEPT_PROMPTS.md) record how to reproduce or refine them.

## Proposed interaction design

### Floating pill states

| State | Main content | Controls |
| --- | --- | --- |
| No agent | Pill with an accessible connection state | Connect, Settings |
| Agent ready | Pill with two quiet wave lines | Start, type, agent selector |
| Voice conversation | Pill with separate user and agent waves | Mute, interrupt, end, transcript, type |
| Screen shared | User's screen with a visible sharing state | Stop sharing plus call controls |
| Agent control active | User's screen with clear agent-action status | Stop control always visible |
| Call ended | Idle pill with access to the transcript | New conversation, history when implemented |
| Settings open | Larger configuration window | Close returns to the pill |

The pill remains available after onboarding and setup.
It must not create a large empty window during a voice-only conversation.
Transcript expansion must preserve access to the pill controls.
The transcript may use an attached panel. Its placement and default visibility remain undecided.
Long transcripts must scroll inside their own area.
Desktop placement, movement, focus behavior, and full-screen behavior need later specifications.

Two separate wave lines replace the original icon and `Agent connected` text in the pill.
The user line responds to captured microphone audio. The agent line responds to reply audio during playback.
Silence, mute, and agent processing must not appear as spoken audio.
Accessible names must identify each line and the connection state without relying on color or motion alone.
The exact labels, colors, and line arrangement remain design details.
Reduced-motion mode must preserve every control and status.

### First-time setup

The proposed setup introduces the product through one successful exchange.
It does not replace provider setup with a simulated agent reply.

1. Show a short welcome with one main action and a skip option.
2. Offer local speech and ElevenLabs with clear data-use information.
3. Show required downloads and an optional voice preview.
4. Request microphone permission before a user-initiated microphone test.
5. Connect a managed agent, or use the external tool installation flow.
6. Ask the user to try a short spoken exchange.
7. Show how to interrupt, mute, and end the call.
8. Show the floating desktop pill.

Advanced model choices remain available throughout setup and in Settings.
Permission denial, missing credentials, downloads, and agent connection failures need useful retry paths.
Screen and control permissions belong at first use, not in initial voice setup.

## Delivery phases

### Immediate priority: Join the user's session

Status: First slice built and proven on Codex. `src/talktome/attach.py` follows a
thread the terminal owns, `talktome call --thread "$CODEX_THREAD_ID" --greeting "…"`
is the whole agent-facing surface, and the skill that teaches an agent the command
installs from the connection screen. `npm run test:attach-call` proves the loop
against a real Codex session end to end.

**The skill and the command are one install step.** The skill's first instruction
is `talktome call`, so installing the instructions without a `talktome` on PATH
installs nothing: the command goes to the first of `~/.local/bin`,
`/opt/homebrew/bin`, or `/usr/local/bin` that is on PATH, as a shim running the same
interpreter the app runs. `skill_status` reports the two halves separately so a
missing one can be named.

**Ringing is a state of its own, not an immediate call.** `talktome call` asks the
user to stop what they are doing, so they get to decide: the pill shows a bell, who
is calling, and an answer and a decline, and the agent's greeting is heard only once
they answer. The name is passed with `--name` and falls back to the project folder.
An ignored ring stops on its own after 30 seconds rather than leaving the
session attached, and the surface sends the ring's identifier back when it answers,
so a reply that arrives after a ring ended cannot answer the next one.

**`talktome end` ends whatever call is live**, from the terminal, with no call
identifier to look up first. The skill tells an agent when to use it and when not
to, because an agent that can hang up on someone mid-thought is worse than one that
cannot hang up at all.

**The one thing attachment cannot do is interrupt.** Codex allows one writer per
thread, and the terminal holds it, so nothing this app does can stop the agent's
turn. `codex queue` delivers a message into a held thread but has no interrupt
option. So on this path the app stops speaking and the queued message is answered
when the agent reaches it, which is the opposite of the managed path's interrupt
rule. If a user talks over a long turn they will wait, and the interface should say
so rather than pretend.

The rest of the transport, all of it measured rather than assumed:

- `codex queue --thread <UUID|name> --message <TEXT>` reaches a held thread without
  becoming its writer.
- The rollout file under `~/.codex/sessions` is append-only JSON Lines and is the
  only public view of a thread another process owns. A byte offset reads only what
  is new, and only whole lines are parsed because the file grows while it is read.
- Agent replies are `event_msg`/`item_completed` records whose item type is
  `AgentMessage`, carrying `text` and a `phase` of `commentary` or `final_answer`.
  The same stream carries `Reasoning`, `CommandExecution`, and `FileChange`, and
  those contain private reasoning and full command output, so only agent messages
  are ever spoken.
- `task_complete` ends a turn and carries `last_agent_message`.

The two previous statements about this priority follow.

The user talks to a session that already exists rather than one TalkToMe starts.
A first slice proves the loop on Codex before discovery or other hosts are added.

The user considers the agent interface more important than further visual work.
The [agent connection research](research/AGENT_CONNECTION_OPTIONS.md) examines the supplied Codex transcript and current source.
The earlier tool path repeats reply text, misses public commentary, and permits only one reply per turn.
The project needs both managed sessions and connections to existing terminal sessions.
Start with managed sessions. Existing terminal attachment remains a separate, host-specific mode.
The project approved both adapters. Codex App Server and the Claude SDK now supply public output to an ordered speech queue.
The live Codex test passed two turns, context recall, a fixture read, and audio generation.
Claude passed mocked tests but reported an expired OAuth session during the live test.
Long conversations, live cancellation, crash recovery, and broader approval support need further tests.
Future screen commands remain outside this implementation.
The numbered phases below group later work. Their numbers do not override this priority.

### Phase 1: Approve the design

Status: Main reference selected. Further design work waits for the agent-interface discussion.

- Use the first Canvas concept, with neon accents and blue surfaces.
- Refine the floating pill and its two audio wave lines.
- Define transcript expansion and the larger Settings window.
- Create setup concepts that share the Canvas visual style.
- Define motion, type sizes, spacing, and accessible colors.
- Define suitable pill dimensions separately from setup and Settings window dimensions.

Completion requires user approval of the main view and setup direction.

### Phase 2: Implement the floating Canvas pill

Status: Planned after design approval.

- Replace the fixed sidebar and large default window with the approved desktop pill.
- Show the pill after setup and open Settings in a larger window.
- Connect each wave line to its own audio source.
- Preserve speech providers, setup progress, agent installation, and native clipboard behavior.
- Keep the transcript, typed input, and call controls easy to reach.
- Put history behind a compact control only when history has useful behavior.
- Remove placeholder feature copy and repeated status text.
- Add clear disconnected, download, permission, and playback error states.
- Test light and dark themes, keyboard access, reduced motion, and long transcripts.
- Test a real agent exchange through speech playback.

Use a smaller model for bounded test tasks, as the user requested.
Record the model, connection path, results, and limits of each test.
Do not report a scripted protocol test as a successful autonomous agent conversation.

### Phase 3: Improve agent and conversation continuity

Status: Planned functional work from the earlier work log.

- Define agent profiles and working folders.
- Test a managed host adapter that keeps one conversation thread across user turns.
- Test public progress, sentence-level speech, approvals, interruption, and reconnect behavior.
- Add existing terminal attachment through supported host interfaces after the managed path works.
- Measure token use and speech delay instead of estimating savings from tool counts.
- Preserve MCP and the bridge for existing integrations.
- Add persistent conversations with resume, export, and delete controls.
- Add explicit agent events for tool progress before showing tool-activity rows.
- Add an optional talk shortcut without replacing an operating-system shortcut by default.
- Validate ElevenLabs keys against the services the user selects.

The adapter proposal must not silently replace the user's agent or its reasoning provider.

### Phase 4: Add screen context

Status: Future implementation.

- Let the user select a display, window, browser tab, or region where the platform permits it.
- Request access explicitly and show when capture is active.
- Send only the selected content to the connected agent or selected interpreter.
- Include a snapshot identifier, capture time, display identifier, bounds, and scale factor.
- Distinguish a still capture from a live view.
- Define retention, redaction, and remote-provider disclosure before release.
- Test display changes, scaling, window movement, denied access, and stopped sharing.

Screen content is untrusted input, not a source of instructions for tool permissions.

### Phase 5: Add annotations and a cursor overlay

Status: Future implementation after screen context.

- Add arrows, circles, labels, and an agent pointer above other applications through a native desktop overlay.
- Use an in-app annotation prototype only if it helps test coordinates and rendering.
- Keep the agent pointer distinct from the user's actual cursor.
- Bind every annotation to a snapshot and coordinate system.
- Reject annotations when their snapshot or display no longer matches.
- Clear overlays when sharing or the call ends, or when the user dismisses them.
- Keep overlay windows out of normal input paths and screen captures where possible.
- Test multiple displays, full-screen apps, scaling, and overlay cleanup after a crash.

An in-app annotation is not the same feature as a system-wide overlay.
The intended product uses the desktop overlay. Test any optional in-app prototype separately.

### Phase 6: Add controlled actions

Status: Future implementation, separate from view and annotation permissions.

- Define separate access for viewing, drawing, browser control, and desktop control.
- Start with browser actions in a user-selected context.
- Add native desktop actions only after the browser path passes safety tests.
- Show planned actions and action results.
- Keep an immediate Stop control available.
- Require confirmation for destructive actions, external submissions, payments, and sensitive changes.
- Record action results without retaining unnecessary screen content or secrets.
- Stop safely when the screen changes or the target is ambiguous.

### Phase 7: Desktop distribution

Status: Requested future design and implementation work.

- Package the Python runtime for desktop installation.
- Test desktop behavior on Linux and Windows before claiming support.

### Optional research: faster screen decisions

Status: Research only.

Keep screen capture, interpretation, decisions, and rendering separate.
Evaluate Jev only after an interpreter supplies structured screen information.
Measure the complete capture-to-action delay, decision accuracy, memory, and power use.
Keep an unknown result and return control to the agent when a decision is uncertain.
The [existing research](research/WORLD_MODELS.md) does not establish Jev as an image-input model.
Recheck provider facts before implementation.

## Reference use

Arc supplies ideas for a deliberate welcome, personalization, and a clear transition into the product.
The review examined a [recorded onboarding flow](https://uifrommars.com/caso-estudio-arc-onboarding/), not a fresh Arc installation.
Its designers also discuss distinct interaction details in [this interview](https://www.dive.club/ideas/what-makes-design-at-arc-so-unique).

HeyClicky supplies a reference for practical voice tutorials and screen guidance.
Its [change history](https://www.heyclicky.com/changelog) describes a tutorial that asks users to try the controls.
The [reuse research](research/HEYCLICKY_REUSE.md) records public source, licenses, and gaps in available code.
Public release binaries do not establish that all current features have reusable source.

Raycast supplies a reference for compact controls and discoverable keyboard actions.
See its [quickstart](https://manual.raycast.com/quickstart).
These references inform the design. They do not define the TalkToMe architecture.

## Next decision

Approve the first slice for session attachment on Codex, including how the app reaches the session
and how a call is started from the terminal.

Renew Claude authentication and repeat its bounded managed live test if that mode is kept.
The floating pill, two audio wave lines, larger Settings window, and first Canvas palette are recorded decisions.
Managed sessions first is also a recorded decision. Both native host adapters now have an initial implementation.
Do not continue visual implementation before the agent-interface work receives direction.

## Maintenance

Update this roadmap when the user selects a design or changes a feature priority.
Record completed work with test evidence and remaining limits.
Keep proposed capabilities separate from implemented behavior.
Do not mark a phase complete because a concept image shows it.
