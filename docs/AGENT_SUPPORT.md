# Agent connections and interruptions

## Current source

TalkToMe adds voice to an existing session. The connection method depends on the host.
The new adapters need a live check before release. No real calls ran during this change.

| Host | Connection | Status |
| --- | --- | --- |
| Codex | Terminal queue and rollout file | Existing path, with a new persistent queue connection |
| Claude Code | Explicit `listen` and `reply` commands | New cooperative adapter |
| Hermes Agent | Runs API for an existing API session | Experimental, requires server capabilities |
| OpenClaw | Gateway protocol for an existing session key | Experimental, requires server capabilities |
| Other hosts | Explicit `listen` and `reply` commands | Requires shell commands in the host |
| Any supported host, remote server | Remote bridge daemon | Live check passed with Hermes; see [remote bridge](REMOTE_BRIDGE.md) |
| Hermes Agent, OpenClaw | Host plugin with a `talktome_call` tool | Hermes passed live calls; see [host plugins](HOST_PLUGINS.md) |

A host plugin is the preferred connection for Hermes and OpenClaw.
The plugin runs `listen` and `reply` inside the host, so the model does not spend a model call on each command.

The remote bridge runs the same cooperative commands through an agent-side
daemon and a self-hosted relay. The laptop keeps the microphone and speech, and
only text and call events cross the relay. Use `talktome --remote` in place of
the local commands when the server has a saved bridge configuration.

The Hermes API server and the Hermes CLI use one state database.
A `/v1/runs` request with the ID of a terminal session loads and writes that same session.
Hermes runs only one turn at a time for each session. The session lock waits up to 30 minutes.
An open terminal keeps its old history in memory.
It does not show the voice turns until the user resumes the session.

## Give the host its instructions

Run `talktome skill` to print the bundled skill.
The host can read this output without a new call or a network connection.
Settings installs the skill for Codex and existing Hermes and OpenClaw profiles.
The default Hermes path is `~/.hermes/skills/talktome/SKILL.md`.
If the app environment sets `HERMES_HOME`, the installer uses that profile instead.
The app does not find custom profiles from another process's environment.
The shared OpenClaw path is `~/.openclaw/skills/talktome/SKILL.md`.
If the app environment sets `OPENCLAW_STATE_DIR`, the installer uses that state directory instead.
[OpenClaw skill paths](https://docs.openclaw.ai/tools/skills).

TalkToMe uses shell commands. It does not need a tool named `talk_to_me`.
If Hermes searches only its tool catalog, ask it to load the `talktome` skill with `skill_view`.
It can also read the skill file directly with its terminal tool.
The skill index can require a new chat before it shows a newly installed skill.
[Hermes skill guide](https://hermes-agent.nousresearch.com/docs/guides/work-with-skills).

For an existing Hermes chat, use `--agent hermes --connection cooperative`.
This path needs no Hermes server token. Hermes must run `listen` and `reply` throughout the call.
Use the external Hermes adapter only for an existing API session.
For an existing OpenClaw chat with local shell access, use `--agent openclaw --connection cooperative`.
The shell must run on the Mac that runs TalkToMe.
Installing the skill on this Mac does not install it on a remote Gateway.

The skill requires subagents for extended work during calls unless the user requests direct work.
The main agent handles conversation and call commands.
If the host has no subagents, the main agent states that limit.
This instruction does not change how a host schedules incoming messages.

## Use cooperative commands

Use `--agent claude` for Claude Code. Use `--agent generic` for other hosts.
Hermes, OpenClaw, and Codex also accept `--connection cooperative`.
Use the host session ID, or one unique identifier that the host retains for the call.

```sh
talktome call --agent claude --thread SESSION_ID --greeting "What would you like to discuss?"
talktome listen --thread SESSION_ID --after 0 --timeout 25
```

A pending request supplies the call ID and turn ID. Reply with those identifiers.
Use a unique item ID for each message. Add `--progress` if more replies will follow.

```sh
talktome reply --thread SESSION_ID --call-id CALL_ID --turn-id TURN_ID --item-id ITEM_ID --text-file /tmp/reply.txt
```

Retain the returned event sequence for the next `listen` command.
Do not repeat work for a pending request that the host already handled.
An interruption cancels the voice request. It does not stop the host or its subagents.
The adapter rejects replies for old calls and turns.
An exact retry with the same item ID does not repeat the speech.

## Configure external hosts

Run `talktome providers` to see the local configuration status.
This command does not prove that a remote host accepts connections.
The external adapters require host servers that the user already configured.

Give a token through standard input, not a command argument:

```sh
talktome configure-agent --agent hermes --host-url http://127.0.0.1:8642 --token-stdin
talktome configure-agent --agent openclaw --host-url ws://127.0.0.1:18789 --token-stdin
```

The app stores these settings in `agent-hosts.json` in its data directory.
The file has mode `0600`. It contains a plaintext token and only the current user can read it by default.
The commands return the host URL without the token.
Saved settings work when Finder starts the app without shell environment variables.

The default accepts loopback hosts. A remote host requires HTTPS or WSS and `TALKTOME_ALLOW_REMOTE_AGENTS=1` in the app environment.
The OpenClaw adapter works only with a loopback Gateway, such as `ws://127.0.0.1:18789`.
A remote `wss://` Gateway requires device pairing, and TalkToMe does not do device pairing.
Thus, `TALKTOME_ALLOW_REMOTE_AGENTS=1` does not make a remote OpenClaw Gateway work.
A host URL cannot contain credentials, query parameters, or a fragment.

```sh
talktome call --agent hermes --thread API_SESSION_ID --greeting "What would you like to discuss?"
talktome call --agent openclaw --thread GATEWAY_SESSION_KEY --greeting "What would you like to discuss?"
```

Hermes must report `run_submission` and `run_events_sse`.
The adapter requests a stop only when the host reports `run_stop`.
Hermes approval requests need the `run_approval_response` feature.
OpenClaw must accept protocol version 4 and the required session methods.
OpenClaw input uses `followup` queue mode. A stop request names the returned run ID.
An incompatible host returns an error. The app does not change host permissions.

TalkToMe stops a Hermes or OpenClaw voice turn after 10 minutes.
If a cooperative host runs neither `listen` nor `reply` for 5 minutes, the turn ends with an error.

## Interrupt spoken output

The microphone remains active during assistant speech.
A sustained input signal pauses output before transcription completes.
If the recording has no text, output resumes.
If the recording has text, the app clears old audio and starts the new voice turn.
The signal gate reduces short noise triggers. It does not classify intent or short acknowledgments.

The player sends audio IDs and playback times before it clears output.
The server compares these with audio frames for the same call and playback epoch.
For ElevenLabs, character alignment permits an estimate within a partial audio frame.
For speech without alignment, the report includes only complete audio frames with known text.
The report stops at an unknown frame. It does not assume that generated text reached the user.

The next input contains a short playback report for the agent.
This report does not remove old text from host history.
Audio timing estimates device output. It cannot prove what the user heard.
Codex terminal attachment stops speech but cannot stop terminal-owned work.
Cooperative hosts receive cancellation events. They decide what to do with their work.

## Input latency

ElevenLabs transcription already runs while the user speaks.
The Codex adapter now starts one queue proxy at connection time.
Each turn uses `thread/queue/add` through that proxy.
Initialization failure uses the existing CLI path before any user input exists.
An explicit unsupported-method response also permits the CLI path.
A timeout or lost connection after submission does not trigger a resend.

The code still waits for a matching user message in the rollout file.
Queue acceptance, rollout acceptance, and terminal drawing are separate events.
No new timing measurement supports a numeric latency claim yet.

## Smart Turn

Pipecat Smart Turn is already trained. TalkToMe does not need a new training dataset.
It can run beside live transcription and decide when the app commits the text.
[Smart Turn](SMART_TURN.md) now controls live turn decisions when its model is ready.
Settings can select the fixed-pause rule instead.

Pipecat supplies recorded test speech. Use this dataset for the first model checks.
Then use normal calls to check the microphone path and the pause settings.
The earlier synthetic speech results do not establish failure on real speech.
They also do not establish correct turn decisions in TalkToMe.

See [agent research](notes/research/MULTI_AGENT_SUPPORT.md), [interruption research](notes/research/INTERRUPTION_PLAYBACK.md), and [input research](notes/research/PARALLEL_INPUT_AND_DELIVERY.md).
