# Agent protocol

An agent reaches TalkToMe through the `talktome` command.
Each call starts with a ring. The user answers the ring or lets it stop.
The app permits one agent connection at a time.

## Commands

The commands do not use the network. Each command writes a private request file, and the app writes the answer beside it.
Thus the commands work when a sandbox blocks connections to `127.0.0.1`.
The app reads requests from its data folder and from `/tmp/talktome-<uid>/requests`.
If the app is closed, `talktome call` starts it.

| Command | Purpose |
| --- | --- |
| `talktome call --agent AGENT --thread ID` | Ring the user from a session |
| `talktome listen --thread ID --after SEQ --timeout 25` | Wait for the next user turn in cooperative mode |
| `talktome reply --thread ID --call-id CALL --turn-id TURN --item-id ITEM --text TEXT` | Speak a reply in cooperative mode |
| `talktome end` | End the live call, or decline a ring |
| `talktome providers` | Show the connection methods that are ready |
| `talktome configure-agent --agent hermes --host-url URL --token-stdin` | Save a Hermes or OpenClaw host |
| `talktome skill` | Print the bundled agent skill |

`--agent` is `codex`, `claude`, `hermes`, `openclaw`, or `generic`.
`--connection cooperative` makes a listed host use `listen` and `reply`.
Each command prints one JSON object. A refused request prints one sentence to standard error and exits with code 1.

## Ring and accept

1. The agent runs `talktome call` with its session ID, an optional `--greeting`, and an optional `--name`.
2. The call surface rings and shows the name. A macOS notification also shows the name. The ring stops after 30 seconds.
3. The user selects **Answer**. The call starts, and the app speaks the greeting. The app prepares the greeting audio while the call rings.
4. The command returns `answered: true`. If the user selects **Decline** or the ring stops, it returns `answered: false`.
5. Each user utterance goes to the agent. Each reply from the agent plays in the call.
6. The call ends when the user selects **End**, or when the agent runs `talktome end`.

Add `--no-wait` to return as soon as the ring starts.
A Codex session ID must match `[A-Za-z0-9][A-Za-z0-9._:-]*`, because it goes into a file search.
Other agents can use any printable ID with no spaces, up to 512 characters.
The app refuses a ring while another call or ring is live.
The app also refuses a ring when speech is not set up: no speech model, no key for ElevenLabs input, or no voice. The command then prints "TalkToMe speech is not set up. Ask the user to finish setup in TalkToMe."

## Connection methods

| Agent | Method | How replies reach the call |
| --- | --- | --- |
| Codex | Terminal session | The app sends user speech with `codex queue` and reads public replies from the session rollout file. |
| Claude Code, other hosts | Cooperative | The agent runs `listen` and `reply`. |
| Hermes Agent | Cooperative, or the Runs API for an API session | The adapter reads the run events. |
| OpenClaw | Cooperative, or the Gateway protocol for a session key | The adapter reads the Gateway events. |

A Codex call takes no writer. The terminal keeps the session, so the app cannot start or stop a turn.

## Cooperative mode

Cooperative mode works with any host that can run shell commands on the Mac that runs TalkToMe.
It does not start another model session.

1. Run `talktome listen --thread ID --after 0 --timeout 25`.
2. Keep the returned `seq` for the next `listen` command.
3. Read the `pending` turn. It has `call_id`, `turn_id`, and the user text.
4. Send a short progress reply with `--progress` and a new `--item-id` when the work takes time.
5. Send the final reply without `--progress`. This reply ends the voice turn.
6. Run `listen` again for the next turn.

An empty result means that no new turn is available.
A `turn.cancelled` event means that the voice turn ended. Do not send more replies for that turn.
A later `pending` turn replaces an earlier one.
An exact retry with the same item ID and text does not repeat the speech.
The adapter refuses replies for old calls and old turns.
If the host sends no `listen` and no `reply` for 5 minutes, the turn ends with an error.
Use `--text-file PATH` for text that contains quotes or shell syntax.

## Hermes and OpenClaw hosts

Give the host token through standard input, not a command argument:

```sh
talktome configure-agent --agent hermes --host-url http://127.0.0.1:8642 --token-stdin
talktome configure-agent --agent openclaw --host-url ws://127.0.0.1:18789 --token-stdin
```

The app saves these settings in `agent-hosts.json` in its data folder, with mode `0600`.
The file holds the token as plain text. The command output does not show the token.
The app accepts loopback host URLs by default.
A Hermes host on another computer needs HTTPS and `TALKTOME_ALLOW_REMOTE_AGENTS=1` in the app environment.
The OpenClaw adapter works only with a loopback Gateway.
You cannot change host settings during a call.

```sh
talktome call --agent hermes --thread API_SESSION_ID
talktome call --agent openclaw --thread GATEWAY_SESSION_KEY
```

Hermes must report `run_submission` and `run_events_sse`. Approval requests need `run_approval_response`.
OpenClaw must accept protocol version 4.
[Agent support](AGENT_SUPPORT.md) gives the limits and the interruption behavior of each host.

## Approvals

A Hermes run can ask for approval before a tool runs.
The call surface then shows the tool and the command, with **Allow once** and **Deny**.
The pill status reads "Needs approval".
If the user gives no answer in 180 seconds, the app denies the request.

## Events

The desktop windows read the call through `GET /v1/state` and the long poll `GET /v1/events`.
Each event has `seq`, `type`, `call_id`, and `time`.

| Type | Extra fields | Meaning |
| --- | --- | --- |
| `call.started` | None | The user answered a ring |
| `call.ended` | None | The call ended |
| `user.utterance` | `text`, `turn_id` | A new user message |
| `agent.connected` | `name` | An agent connected |
| `agent.disconnected` | None | The agent disconnected |
| `agent.greeting` | `text` | The app speaks the greeting |
| `agent.interrupted` | None | The current speech turn ended |
| `message.delta` | `turn_id`, `item_id` | Agent text changed in the room snapshot |
| `message.done` | `turn_id`, `item_id` | An agent message is complete |
| `agent.audio` | `turn_id`, `audio_id` | One speech chunk is ready |
| `turn.done` | `turn_id` | The agent finished its turn |
| `managed.state` | None | The session status, the ring, or the approvals changed |

Read message text from the room snapshot. Message events do not repeat the text.
The server keeps 512 events. If the cursor is too old, `reset` is true. Use the room snapshot to recover.
The room snapshot keeps the most recent 200 transcript messages.
The `managed` object in the state has the status, the error, the session ID, the ring, and the pending approvals.

## HTTP endpoints

The server listens on `http://127.0.0.1:8765` by default.
Each private endpoint needs `Authorization: Bearer TOKEN` or the desktop session cookie.
`talktome token` prints the token.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/v1/health` | Public service and speech status |
| GET | `/v1/state` | Call, speech, and session state |
| GET | `/v1/events` | Desktop event stream through long polling |
| POST | `/v1/attach/start` | Ring from a session, with `thread`, `cwd`, `agent`, `connection`, `greeting`, and `name` |
| POST | `/v1/attach/accept` | Answer the ring, with an optional `ring_id` |
| POST | `/v1/attach/decline` | Decline the ring, with an optional `ring_id` |
| POST | `/v1/hangup` | End the live call, or decline a ring |
| GET | `/v1/managed` | The session state |
| POST | `/v1/managed/approvals/{id}` | Answer one approval with `{"allow":true}` or `{"allow":false}` |
| POST | `/v1/agent/disconnect` | Release the connected agent |
| POST | `/v1/call/text` | Send typed or recognized text as a user turn |
| POST | `/v1/call/audio?call_id=ID` | Send recorded audio as a user turn |
| POST | `/v1/call/interrupt` | Stop the current reply |
| POST | `/v1/call/end` | End the call, with `call_id` |
| POST | `/v1/call/timing` | Record a playback time for a turn |
| GET | `/v1/call/timings` | Read the saved turn timings. See [call latency](LATENCY.md). |
| POST | `/v1/call/turn-check` | Check a pause with local Smart Turn |
| GET | `/v1/skill` | Whether the agent skill and the command are installed |
| POST | `/v1/skill/install` | Install the agent skill and the command |
| GET | `/v1/models` | Model catalog and download state |
| POST | `/v1/models/{id}/download` | Download and load a model |
| POST | `/v1/speech/turn-detection` | Turn Smart Turn on or off |
| POST | `/v1/stt/transcribe` | Transcribe an audio body without a turn |
| GET | `/v1/tts/voices` | List voices from the selected provider |
| POST | `/v1/tts/voice` | Save a selected voice |
| POST | `/v1/tts/speak` | Return WAV speech without a call |
| POST | `/v1/tts/kokoro/download` | Download and load Kokoro |
| POST | `/v1/speech/providers` | Save recognition and voice providers |
| POST | `/v1/speech/elevenlabs` | Examine and store an ElevenLabs key |
| DELETE | `/v1/speech/elevenlabs` | Remove the ElevenLabs key |

Speech-to-text (STT) input accepts encoded WAV, WebM, or MP4 audio.
The input limit is 8 MB and 35 seconds. Raw PCM needs a WAV header.
Text-to-speech (TTS) output is WAV audio.

Provider settings use `stt_provider` (`whisper` or `elevenlabs`) and `tts_provider` (`system`, `kokoro`, or `elevenlabs`).
Key setup accepts `api_key` and an optional `remember` boolean. The default is `false`.
The app returns the key status, never the key. Provider changes need an idle call.
An agent must not change providers or keys without a user request.
See [speech providers](SPEECH_PROVIDERS.md) for data use and test limits.
