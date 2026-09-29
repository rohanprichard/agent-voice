# AgentCall: overall architecture and the join flow

Research date: September 24, 2026.
Sources read at branch `main`, commit `9b96f6739c3ea3384fbb8c904c63b885d6e455ff`.
No call was placed and no API key was used.

This is the companion to [AgentCall: latency and voice pipeline architecture](AGENTCALL.md), which covers turn-taking, chunking and transcription timing.
This note covers the parts that note deliberately left out: what the system is made of, what happens when an agent joins a meeting, what the wire protocol looks like, and what an integrator actually writes.

## The shape of the system

Five distinct processes are involved, and only one of them runs on the user's machine.

The **agent framework** is whatever the user already runs: Claude Code, Codex, Cursor, Gemini CLI and roughly thirty others ([README.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/README.md)).
It owns the model, the tools and the project context.

The **bridge** is a local script spawned by that agent. The Python bridge's docstring is explicit that it "is NOT a standalone agent. It has NO LLM" and that it is "a thin communication layer" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
There are four variants: `bridge.py` and `bridge.js` for audio mode, `bridge-visual.py` and `bridge-visual.js` for the webpage modes ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

The **AgentCall API** is hosted at `api.agentcall.dev` and is the default for every script, overridable through `AGENTCALL_API_URL` ([agentcall.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/agentcall.py), [bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

The **meeting bot**, called FirstCall in the documentation, runs in the cloud and is described as "meeting infrastructure" ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

The **voice-intelligence service**, called GetSun, also runs in the cloud and exists only for the `collaborative` voice strategy ([collaborative-mode.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/collaborative-mode.md)).

The useful way to hold the architecture in mind is that the bridge is a protocol adapter in both directions. Towards the agent it speaks newline-delimited JSON over stdin and stdout. Towards the service it speaks JSON over a WebSocket. It neither thinks nor synthesises anything.

There is one more local process in the webpage modes: a **tunnel client** that proxies HTTP and WebSocket requests from the cloud bot to a server on the user's machine, which is described next because it is part of the join flow.

## The join flow, end to end

### The entry point is a shell command, not a tool call

This is worth being precise about because the question lists four possibilities and the answer is the least exotic one.

There is **no MCP server in this repository**. A full-text search for MCP finds exactly one hit, and it is advice about a Claude Code feature the user could add on top, not an AgentCall component: "Channels MCP — push `transcript.final` events directly into a running Claude Code session via a custom MCP channel server", described as a research preview requiring Claude Code v2.1.80+ ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

There is **no published SDK package** either. `package.json` in the Node directory is `"private": true` and declares one dependency, `ws` ([package.json](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/node/package.json)). The Python requirements are two libraries, `websockets` and `aiohttp` ([requirements.txt](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/requirements.txt)).

The documented usage is a command line: `./scripts/run.sh <meet-url> [options]` ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
`run.sh` is a runtime selector rather than a program. It checks that Python can actually `import aiohttp, websockets` before trusting it, falls back to Node if `node_modules/ws` exists, and exits with a specific message if neither works, on the reasoning that "PATH presence alone isn't proof a runtime works" ([run.sh](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/run.sh)).

The agent-facing integration is therefore a spawn convention, and the repository documents it per framework in a table: Claude Code and the Agent SDK spawn it with `bash("python scripts/python/bridge.py 'https://meet.google.com/abc' --name Claude")`, Codex uses its `!` shell prefix, and Cursor is called out as needing `tmux` for a PTY because it cannot hold an interactive stdin without one ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

So the real entry point has three layers, and it is worth separating them because only the middle one is the API. The agent runs a command; the command starts a local process; that process makes one HTTPS request and then opens a WebSocket. Nothing flows over the agent's own protocol.

### The reproducible sequence

The join flow in `join.py` reduces to seven steps, and it is short enough to reproduce directly ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).

**Step 1 — read the API key.** From `AGENTCALL_API_KEY` first, then `~/.agentcall/config.json`, with the client raising the same lookup again internally ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py), [agentcall.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/agentcall.py)).
If there is no key, the process exits before any network call.

**Step 2 — check for a recoverable call.** `check_existing_state()` reads `.agentcall-state.json` from the current working directory, which holds `call_id`, `meet_url`, `mode` and `created_at`, and treats a record older than 24 hours as expired ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).
If a record exists, the script emits `{"event": "recovering", "call_id": ...}` and calls `GET /v1/calls/{call_id}`. A status of `ended` or `error`, or a failed request, clears the state file and falls through to creating a new call.

**Step 3 — create the call.** `POST /v1/calls` with `meet_url`, `bot_name`, `mode`, `voice_strategy` and `transcription`, plus mode-dependent fields: `ui_port` or `webpage_url`, `screenshare_port` or `screenshare_url`, and `ui_template` ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).
For `collaborative` strategy the request also carries a `collaborative` object with `trigger_words` and `context` ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).

This is the decisive call. The response is what everything else uses: `call_id`, `status`, `ws_url`, and for webpage modes `tunnel_url`, `tunnel_id` and `tunnel_access_key`. The published response body also includes `call_token` for UI-page WebSocket authentication ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
Note that the call is created *before* the local UI server matters and before the WebSocket is open, and the response returns immediately with status `bot_joining`.

**Step 4 — write the state file.** `save_state()` records the call id and a timestamp so a crash can be recovered ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).

**Step 5 — start the tunnel, in webpage modes only.** Skipped for `audio` mode, skipped when `--template` is used, and skipped when a public `--webpage-url` was supplied. Otherwise the script opens a second WebSocket to `{api_url}/internal/tunnel/connect`, then sends `tunnel.register` with the `tunnel_id` and `tunnel_access_key` from the create-call response, and starts a read loop and a heartbeat ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py), [tunnel.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/tunnel.py)).
The tunnel client's own module docstring is emphatic that `tunnel_access_key` is a per-call credential and that using the API key here is wrong ([tunnel.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/tunnel.py)).
Routing is path-based: `/screenshare/...` goes to the screenshare port, `/ui/...` to the UI port, and everything else to the UI port ([tunnel.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/tunnel.py)).

**Step 6 — wire up stdin and signals.** A daemon thread does blocking `sys.stdin.readline()` and pushes lines onto an `asyncio.Queue`, which a coroutine drains and forwards through `send_command`. `SIGINT` and `SIGTERM` are bound to a shutdown coroutine. The thread exists because "asyncio.connect_read_pipe is broken on Windows per CPython issue #71019" ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).

**Step 7 — open the event WebSocket and stream.** `connect_ws(call_id)` builds `wss://{host}/v1/calls/{call_id}/ws?api_key={key}` and yields decoded events until `call.ended` ([agentcall.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/agentcall.py), [join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).

Between steps 3 and 7 the agent is waiting, and the repository tells it what to expect: `call.created`, then `call.bot_joining`, then up to three `call.bot_joining_meeting` events with `detail` of `starting`, `joining` and `initializing`, then possibly `call.bot_waiting_room`, then `call.bot_ready` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
`call.bot_ready` means the bot is in the meeting. The documentation then imposes one more condition before the agent may speak: "Even after `call.bot_ready`, wait for at least one `participant.joined` event before sending any commands", because a bot alone in a meeting is talking to nobody ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

One detail worth recording because it contradicts nothing but surprises: `bridge.py` synthesises its own `greeting.prompt` event when the first non-bot participant joins, with a hint telling the agent to introduce itself ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

### A bug on the recovery path

Both orchestrators reference a variable that only exists on the create path. `result` is assigned inside `if call_id is None:` and then read later in the tunnel block, so a run that starts from a recovered state file reaches step 5 with `result` undefined ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py), [join.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/node/join.js)).
The consequence differs by language. In Python the `NameError` is caught by the surrounding `except Exception` and reported as a `tunnel.error` event ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).
In Node, `result` is a `const` in a block scope and the reference throws a `ReferenceError` inside the `try`, which is also caught and emitted as `tunnel.error` ([join.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/node/join.js)).
In both cases recovery leaves the tunnel unstarted and the webpage modes degraded, silently apart from one event. It is a small defect, but it is worth knowing before relying on the documented crash-recovery flow.

## Who is in the meeting on the agent's behalf

The agent is not in the meeting. A cloud bot is, and the documentation is consistent about this.

**Where it runs.** In the cloud, in what the documentation calls the rendering environment, and specifically in a browser. `SKILL.md` describes the bot's browser as "running in the cloud" and says it "loads your page via the tunnel URL" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The viewport is fixed: "FirstCall's headless browser renders at this" 1280x720, and the guidance is to design for that ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The crash-recovery guide adds the operationally important part: when the agent dies, "The meeting bot keeps running (FirstCall manages it independently)" ([crash-recovery.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/crash-recovery.md)).

**How it authenticates.** Not stated in the repository. There is no sign-in flow, no credential field on the create-call request, and no mention of OAuth, cookies or tokens for Google, Microsoft or Zoom anywhere in the tree. What the repository does state is the outcome: the bot appears in the participant list, and this is presented as unconditional — the safety table lists "Bot visible in participant list | Always" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
Whether that is anonymous guest joining, a service account, or something else is a property of the hosted service and is not documented here.

**How it is admitted.** The bot can land in a lobby. `call.bot_waiting_room` is a documented lifecycle event described as "if meeting has waiting room", and both bridges log "Bot is in the waiting room — waiting to be admitted" ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
The documentation then gives a rule that matters in practice: do not send commands while in the waiting room, because "no one will hear or see them and they are not queued" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The host can also refuse or remove the bot. The end-reason table includes `rejected` for "Host rejected the bot" and `blocked` for "Bot was kicked", and the safety table states "Meeting host can kick bot | Always" ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

**How audio gets from the bot to the agent.** Two paths, and the agent only ever sees text on one of them.

By default the agent receives **transcription**, not audio. The bot hears the meeting, transcribes it, and the service emits `transcript.partial` and `transcript.final` events over the WebSocket ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
The bridge forwards the finals as `user.message` and the partials only as gate signals ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

Raw audio is opt-in and is off by default, which is easy to miss because `audio_streaming` appears in the event table without a default. `SKILL.md` states that `audio.chunk` "requires `audio_streaming: true` in the call creation request (REST API only — not available as a CLI flag)", and the constraint table confirms it needs audio mode plus that flag ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md), [api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
Note also that `join.py` never sets it, so the CLI path cannot enable raw audio at all ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).

In the reverse direction, the bot's own speech is not sent through the agent either. In audio mode the service resamples and injects the audio straight into the meeting; in webpage modes the audio goes to the page, the page plays it, and the bot's browser captures its own audio output ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [webpage-audio.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/webpage-audio.md)).

The corollary is the strongest architectural statement in the whole repository, and it is made almost in passing: "FirstCall does NOT transcribe bot audio. All `transcript.partial` and `transcript.final` events are always from human participants" ([interruption-handling.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/interruption-handling.md)).
Everything the service knows about who is speaking comes from the meeting mix, and the bot's own voice never pollutes it.

## The protocol between agent and service

### There is no schema file

This is worth stating plainly because the question asks where the schema is defined. It is not defined in one place. There is no types file, no JSON Schema, no OpenAPI document and no generated client in the tree.

The schema exists in three forms, and the tension between them is a real integration hazard:

1. **Prose tables in the documentation.** The event tables in [references/api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md) are the closest thing to a specification, with a row per event and its fields. The command tables sit below them in the same file.
2. **Example JSON blocks.** [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md) carries fuller examples for every event and command, including fields the tables omit.
3. **Defensive code.** The shapes the bridges actually expect are legible in the parsers, and they do not always match the prose. The speaker field is the clearest case: the documents show `"speaker": {"id": "p-1", "name": "Alice"}`, and both bridges handle the possibility of a bare string with `if isinstance(speaker_obj, dict)` ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md), [bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

One further discrepancy deserves flagging because the question asks about `barge_in_prevention` specifically. It is **not a WebSocket message type at all**. It is a field inside the `collaborative` object on the create-call request, alongside `interruption_use_full_text` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [collaborative-mode.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/collaborative-mode.md)).
Note also that `join.py` builds that `collaborative` object with only `trigger_words` and `context`, so neither barge-in setting is reachable from the CLI ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).

### Events the agent receives

Lifecycle events, all in [api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md) and expanded in [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md): `call.created`, `call.tunnel_ready`, `call.bot_joining`, `call.bot_joining_meeting`, `call.bot_waiting_room`, `call.bot_ready`, `call.ended`, `call.state`, `call.transcript_ready`, `call.credits_low`, `call.max_duration_warning`, `call.degraded` and `call.recovered`.
The two unusual ones are `call.state`, sent on every WebSocket connect or reconnect as a snapshot, and the `call.degraded` / `call.recovered` pair, which report that an internal service such as voice intelligence dropped and returned ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

Transcription events: `transcript.final` in all strategies with `text`, `speaker.name`, `speaker.id` and `timestamp`, and `transcript.partial` in `direct` only ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

Meeting events, which are not mentioned in the brief but are a fifth of the surface: `participant.joined`, `participant.left`, `active_speaker` and `chat.message` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

Voice events, collaborative only: `voice.state` with one of seven values and `voice.text` carrying each sentence as it is spoken ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
`contextually_aware` belongs to this group as a state value, not an event type, and the templates guide gives typical durations for all seven states, with `thinking` at "1-5s typically" and `contextually_aware` at 20 seconds ([ui-templates.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/ui-templates.md)).

Speech events: `tts.started`, `tts.done`, `tts.audio`, `tts.webpage_audio`, `tts.error`, `tts.interrupted` and `tts.audio_clear` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

Media events: `audio.chunk` (gated by `audio_streaming`), `screenshot.result`, `capture.started`, `capture.frame`, `capture.stopped`, `screenshare.started`, `screenshare.stopped` and `screenshare.error` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

System events: `command.ack`, `command.error` and `events.replay` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

### Commands the agent sends

The command set mirrors the above and is listed in [api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md) with fuller examples in [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md).

Voice intelligence, collaborative only: `inject.natural` and `inject.verbatim` (both with a `priority` of `normal` or `high`), `trigger.speak`, `voice.contribute` and `voice.context_update` with a documented 4,000-character maximum.
`voice.context_update` is the one that carries data; the rest carry intent.

Speech: `tts.generate` with a `destination` of `meeting`, `agent` or `webpage`, and `tts.speak` as a shortcut that infers the destination from the mode.

Raw audio: `audio.inject` and `audio.clear`.

Meeting actions: `meeting.send_chat`, `meeting.raise_hand` and `meeting.leave`.

Media: `screenshot.take`, `capture.start` (minimum 500 ms, multiple of 250), `capture.stop`, `screenshare.start`, `screenshare.stop`.
The visual bridges add `screenshare.swap`, `webpage.open`, `webpage.close`, `set_state` and `tasks.set`, documented in [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md).

System: `events.replay`.

The documentation adds a restriction table stating which commands each mode and strategy accepts, and warns that a mismatched command is "silently ignored or returns `command.error`" ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
That table is the practical substitute for a schema, and it is the part an integrator should read first.

### Three incompatible naming conventions in one protocol

The most instructive thing about the protocol is how the same object is addressed differently at each layer, because the repository is candid about the resulting failures.

At the top the agent speaks **bridge shorthand**: `{"command": "tts.speak", ...}` ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
The published API uses **dotted type names**: `{"type": "tts.speak", ...}` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
And the bridge translates between them with an alias map for the cases where the short name is not the dotted name at all: `meeting.send_chat` becomes `send_chat`, `meeting.raise_hand` becomes `raise_hand`, `meeting.mic` becomes `mic`, `meeting.leave` becomes `leave`, and `screenshot.take` becomes `screenshot` ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

The comment explaining the alias map is the honest part: it exists because "The meeting-bot runbook mixed bridge shorthand (`command`) with raw API/WebSocket command names (`type`)", which meant raw type commands "were silently ignored on stdin, making unmute/speak attempts look like command-pipe drops" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py), [pull request #2](https://github.com/pattern-ai-labs/agentcall/pull/2)).
That fix, plus `command.ack` and `command.error` events for observability, went through all four bridges in a series of pull requests ([CHANGELOG.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/CHANGELOG.md), [pull request #8](https://github.com/pattern-ai-labs/agentcall/pull/8), [pull request #9](https://github.com/pattern-ai-labs/agentcall/pull/9)).

Event naming has the same split, and the documentation states the rule rather than hiding it: "Lifecycle events use the `\"event\"` field. Transcription, meeting, and media events use the `\"type\"` field. Always check both" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
`bridge.py` normalises everything to `"event"`, and the skill document warns that a direct `join.py` consumer must check both ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

The lesson is not that the protocol is bad. It is that a bridge which translates between two vocabulary conventions will eventually be shown both, and that the failure mode without an explicit acknowledgement event is a silent no-op that looks like a transport fault.

## How an agent author integrates

The smallest amount of integration work is not a library call. It is spawning a process.

The smallest complete example in the repository is the Claude Code row of the integration table, which is one line of shell inside a `bash` tool call: `bash("python scripts/python/bridge.py 'https://meet.google.com/abc' --name Claude")` ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The Codex equivalent is the same command behind its `!` prefix ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

A second complete example is the canonical event-loop setup, which shows the two-file convention that keeps the agent out of the polling business ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)):

```bash
EVENTS="$PWD/meeting-events.jsonl"
COMMANDS="$PWD/meeting-commands.jsonl"
: > "$COMMANDS"

python3 scripts/python/bridge.py "<meet-url>" \
  --name "Claude" \
  --output "$EVENTS" \
  < <(tail -f "$COMMANDS") &
BRIDGE_PID=$!

tail -f "$EVENTS" | grep --line-buffered -E \
  '"event": "(user\.message|greeting\.prompt|call\.(ended|bot_ready)|participant\.(joined|left)|chat\.received|command\.(ack|error)|tts\.(done|error|interrupted))"'

echo '{"type": "tts.speak", "text": "Hi", "request_id": "hello-1"}' >> "$COMMANDS"
```

The commands file is the bridge's stdin through bash process substitution, and the events file is a tee of its stdout, so the agent never holds a pipe. The document flags the one trap that matters: "`grep --line-buffered` is REQUIRED. Without it, the pipe buffers and your events can be delayed by **minutes**" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

For an author who wants code rather than a convention, `agentcall.py` is the whole client and is 150 lines: `create_call`, `get_call`, `end_call`, `list_calls`, `get_transcript`, `connect_ws`, `send_command`, `tts_generate` and `tts_voices`, each a thin wrapper over `aiohttp` or `websockets` ([agentcall.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/agentcall.py)).
The retry behaviour lives in `send_command`, which attempts three times with backoff and then logs the dropped command to stderr rather than raising ([agentcall.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/agentcall.py)).

The cleanest example of the whole pattern for a different project is not in `scripts/` at all. The coding-companion example ships its own 23-kilobyte `bridge.py` that reimplements the same protocol inlined, with its own `API_BASE`, its own `VADBuffer` and its own `BargeInState`, precisely so that a single self-contained file can be dropped into an agent's working directory ([coding-companion bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/examples/coding-companion/bridge.py)).
For anyone considering reuse, that file is the more useful artefact than the `scripts/` tree, because it shows the minimum viable surface with no shared imports.

## Deployment and cost shape

**The hosted service is mandatory.** Nothing in the repository suggests otherwise. Every client defaults to `https://api.agentcall.dev`, and the only supported variation is `AGENTCALL_API_URL`, described in the options table as "Override API URL for development" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
A full-text search found no Dockerfile, no compose file, no Helm chart, no Kubernetes manifest and no self-hosting instructions of any kind.

Two things complicate the picture slightly, and both should be read as hints rather than capabilities. The `AGENTCALL_API_URL` variable plus the client's config-file lookup means the clients can be pointed at any host that implements the API. And the tunnel connects to a path named `/internal/tunnel/connect`, which the word "internal" suggests is not a documented public surface ([join.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/join.py)).
There is no server implementation in the tree, so a replacement host would have to be written from the API reference alone.

**Keys.** Keys are prefixed `ak_ac_` and travel as `Authorization: Bearer` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
Two acquisition paths exist. The scripted one posts to `/v1/auth/email-otp/send` and `/v1/auth/email-otp/verify`, then `POST /v1/auth/api-keys` with the returned token, and saves the key to `~/.agentcall/config.json` under a name of the form "AgentCall Skill on \<hostname\>" ([register.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/register.py)).
The manual one is a key created at `app.agentcall.dev/api-keys` and pasted into the same config file ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
Registration uses only the standard library in both languages, deliberately, so that a key can be obtained before `pip install` or `npm install` has run ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

**Pricing.** The README states "Base plan: 6 hours of meeting time, 1 concurrent call. All features included" and "Paid: per-minute billing" ([README.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/README.md)).
`SKILL.md` is slightly more specific, splitting the base plan into "6 hours (audio mode)" and noting that the paid base rate "varies by mode (audio cheapest, screenshare most expensive)" with transcription, voice intelligence and TTS as add-ons, before deferring to the website for current rates ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The API reference carries a component table with free, pro and enterprise columns — base meeting bot, transcription, voice intelligence and TTS generation priced per hour — and a note that new accounts include trial credits ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

**Limits.** The documented rate limits are 100 API requests per second per key, 100 WebSocket commands per second per connection, 5 registrations per IP per hour and 10 logins per IP per minute ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
Operational limits run alongside them: `alone_timeout` defaults to 120 seconds, `silence_timeout` to 300 seconds, and `max_duration` to the plan limit ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
Two billing-related details are unusually candid. Error 402 means insufficient credits, and `call.credits_low` fires at call start when the balance is under a dollar but "Credits low does NOT terminate the call — the call continues and credits can go negative" ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
And the safety section warns that an orphaned bot "will run until `max_duration` (1 hour), accumulating charges the entire time" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

## What is genuinely reusable for a different project

The user's framing is that AgentCall already has a working version of joining a call, and the honest first answer is that most of what makes it work is the part that cannot be reused. The meeting bot, the browser fleet, the credentials, the recogniser, the synthesiser and the voice-intelligence service are all hosted, and none of them is in the repository.
What is in the repository is the client-side discipline of talking to a real-time agent that is not fast enough to hold a conversation by itself. That part transfers well, and it is more transferable than the latency note's findings because it is about shape rather than timing.

The five ideas worth taking, in rough order of value.

**A newline-delimited JSON bridge as the agent boundary, with the agent as a spawner rather than a callee.** This is the whole architecture in one sentence, and it is visible in the one-line integration. The agent writes `{"command": ...}` to a stream and reads `{"event": ...}` back. There is no agent-side SDK, no callbacks, and no session object to keep alive. The bridge has no LLM. For a project that reaches a terminal-held agent session, this is the same shape, and the companion note's [TalkToMe comparison](AGENTCALL.md) already argues that the two-file convention is the concrete version of it. The transferable detail is not "use stdin and stdout" but the decision to make the transport dumb and let the agent's own session be the intelligence.

**A two-file tail convention so the agent never holds the pipe.** The `< <(tail -f "$COMMANDS")` plus `--output "$EVENTS"` pair is a small thing that buys three large properties at once: the bridge survives an agent restart, the agent survives a bridge restart, and the agent is genuinely idle between events instead of polling. The `--output` flag exists solely for this, and the bridge writes to stdout and the file simultaneously ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
The accompanying warning about `grep --line-buffered` is the kind of detail that costs an afternoon to rediscover, and it is worth citing directly in any implementation notes.

**Named state snapshots plus an event replay request.** `call.state` on every connect and reconnect, followed by an explicit `events.replay` that returns the last 200 events or five minutes, is a recovery design that costs the server very little and makes crashes survivable. The distinction the guide draws between replaying state-changing events and omitting transient ones like `transcript.partial` and `audio.chunk` is the part worth copying ([crash-recovery.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/crash-recovery.md)).
An agent that reconnects and receives a snapshot can resume; an agent that reconnects into silence cannot.

**Explicit acknowledgement events on the inbound command path.** `command.ack` and `command.error` exist because a mistyped command was indistinguishable from a broken pipe ([pull request #2](https://github.com/pattern-ai-labs/agentcall/pull/2)).
This is a general lesson about agent-facing protocols rather than a voice one: when the caller is a language model writing JSON by hand into a shell, silent no-ops are expensive, because the model has no way to notice and will simply believe it unmuted itself.

**A turn-scoped identifier on every command.** `request_id` is echoed back on `command.ack` and `command.error` ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
TalkToMe has arrived at the same idea independently with its turn identifiers and its rule that stale turn audio is discarded ([AGENT_API.md](../../AGENT_API.md)). The convergence is worth noting: two systems built by different people for the same class of problem both found that correlating replies to requests is necessary once the agent can issue several commands while earlier ones are still in flight.

Two things that look reusable and are not.

**The meeting-bot layer.** Nothing about joining Meet, Teams or Zoom is transferable, because none of it is present. There is no bot code, no browser automation, no authentication handling, and no admission logic. The repository's contribution here is documentation of the bot's behaviour from the outside: that it appears in the participant list, that it can wait in a lobby, that the host can kick it, and that it keeps running when the agent dies. Those are integration constraints to design against, not components to lift.

**The voice-intelligence split.** The `collaborative` strategy's structure — a fast service that owns turn-taking and speaks from a swappable context scratchpad, while a slow agent feeds that scratchpad and supplies announcements — is an interesting design, and the `voice.context_update` plus `inject.natural` pair is a genuinely clever interface. But the premise is a hosted low-latency voice model that answers from context in under a second ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
A project reaching a terminal-held agent has no such component and cannot build one cheaply. The transferable fragment is only the interface idea: expose a bounded, silently replaceable context slot that the slow component writes and the fast component reads, so the slow component can be useful without being on the critical path. Whether that is worth building without a fast reader is a separate question.

Finally, one design constraint is worth carrying over even though it looks like a billing artefact. `max_duration` defaults to the plan limit and an orphaned bot runs until it, accumulating charges ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
A local TalkToMe session has no per-minute cost and no orphan risk in the same sense, but it has the same failure shape: a session that outlives its purpose and keeps a microphone open. A hard ceiling with a warning event five minutes before it, which is what `call.max_duration_warning` does, is cheap to add and cheap to reason about.

## Things this note could not verify

- How the bot authenticates to Google Meet, Microsoft Teams or Zoom. No credential flow, sign-in mechanism or account model is described anywhere in the repository.
- What the `rejected` end reason looks like from the outside, beyond the four-word description "Host rejected the bot" ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
- Whether `AGENTCALL_API_URL` points at a supported alternative deployment or exists only for the vendor's own development. The options table calls it a development override and no server is published ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
- Whether the `/internal/tunnel/connect` path is a stable interface. The `internal` prefix and the absence of any API-reference entry suggest not, but the repository does not say either way ([tunnel.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/tunnel.py)).
- The exact JSON Schema of any message. Three documentation forms disagree in places, and the bridges defend against shapes the prose does not mention.
