# talktome

TalkToMe is a macOS menu-bar app for voice calls with a coding agent.
The agent rings you from the session that it already runs. You answer, and you talk.

The agent keeps its model, tools, files, and history. TalkToMe does not supply a language model.
The app records the microphone, turns speech into text, sends the text to the agent, and speaks the reply.

## How a call works

1. You ask the agent in its session to call you, for example "Call me with TalkToMe."
2. The agent runs `talktome call` with its session ID.
3. TalkToMe shows a ring on the screen. You select **Answer**.
4. The agent speaks a short greeting.
5. You speak. The agent receives your words as a message in its session and replies.
6. You select **End**, or the agent runs `talktome end`.

The app has no window that starts a conversation.
After setup, TalkToMe stays in the menu bar and waits for a call.
The menu-bar icon opens Settings and gives controls to answer, decline, mute, and end a call.

## Requirements

- A Mac with Apple silicon (arm64) and macOS 14 Sonoma or later.
- One agent host: Codex, Claude Code, Hermes Agent, OpenClaw, or another host that can run shell commands.

## Install

### Disk image

1. Download `TalkToMe-<version>-arm64.dmg` from [Releases](https://github.com/rohanprichard/talktome/releases).
2. Open the disk image and drag TalkToMe to Applications.
3. Open TalkToMe. macOS tells you that it cannot verify the app. Close the message.
4. Open **System Settings > Privacy & Security**. Below the message about TalkToMe, select **Open Anyway**.
5. Open TalkToMe again, then select **Open Anyway**. macOS can ask for your password.

You do steps 3 to 5 only once.
On macOS 15 Sequoia and later, Control-click and **Open** does not skip this check.
To skip the check from Terminal, run `xattr -dr com.apple.quarantine /Applications/TalkToMe.app`.

macOS asks for these steps because the app is not notarized.
Notarization needs a paid Apple Developer ID.
The app has an ad-hoc signature. The signature lets macOS find a change to the app files.

### Homebrew (coming soon)

This command works after the tap `rohanprichard/tap` exists:

```sh
brew install --cask rohanprichard/tap/talktome
```

The first start needs the same **Open Anyway** step as the disk image.

### Build from source

You need Node.js 22 or later, [uv](https://docs.astral.sh/uv/getting-started/installation/), and the Xcode command-line tools.
uv installs Python 3.11 to 3.13 when necessary.

```sh
git clone https://github.com/rohanprichard/talktome.git
cd talktome
npm ci
uv sync --frozen
npm start
```

`npm start` runs `uv sync --frozen` if the Python environment is missing. Then it starts Electron.
To build the disk image, see [Build the disk image](#build-the-disk-image).

### Server install for remote calls

An agent on another server can ring the app through the [remote bridge](#remote-bridge-experimental).
On that server, install only the command. It has no speech libraries:

```sh
uv tool install "talktome-local @ git+https://github.com/rohanprichard/talktome"
```

## First-run setup

The first start opens a setup window with five steps:

1. **Welcome.** The window explains the call flow.
2. **Microphone.** Select **Allow microphone**. macOS asks for permission.
3. **ElevenLabs.** Enter an ElevenLabs API key, or select **Later** to use local speech.
4. **Agent connection.** Select **Install**. This installs the agent skill and the `talktome` command.
5. **All set.** Ask your agent to call.

You can skip a step with **Later**. Settings contains the same options.
To run setup again, quit the app and run `npm run reset`.
This command clears the saved speech settings and the setup progress. It keeps the downloaded models and the local token.

## Connect an agent

**Install** writes the skill file to `~/.codex/skills/talktome/SKILL.md`.
It also writes the skill to `~/.hermes/skills/` and `~/.openclaw/skills/` if those directories exist.
It installs the `talktome` command in `~/.local/bin`, `/opt/homebrew/bin`, or `/usr/local/bin`.
The skill tells the agent which commands to run. See [the skill](skills/talktome/SKILL.md).

For Claude Code, or for another host, copy the skill into the host's skill directory:

```sh
mkdir -p ~/.claude/skills/talktome
talktome skill > ~/.claude/skills/talktome/SKILL.md
```

| Host | Command | How replies reach the call |
| --- | --- | --- |
| Codex | `talktome call --agent codex --thread "$CODEX_THREAD_ID"` | TalkToMe reads the session's public replies automatically. |
| Claude Code | `talktome call --agent claude --thread SESSION_ID` | The agent runs `talktome listen` and `talktome reply`. |
| Hermes Agent chat | `talktome call --agent hermes --connection cooperative --thread ID` | The agent runs `talktome listen` and `talktome reply`. |
| OpenClaw chat | `talktome call --agent openclaw --connection cooperative --thread ID` | The agent runs `talktome listen` and `talktome reply`. |
| Other hosts | `talktome call --agent generic --thread ID` | The agent runs `talktome listen` and `talktome reply`. |

The `listen` and `reply` commands are the "cooperative" connection.
They work with any host that can run shell commands on the Mac that runs TalkToMe.
The commands exchange private files with the app. Thus, they work when a sandbox blocks local network access.

For Hermes and OpenClaw, a host plugin is the better connection.
Install it with `talktome plugin install --agent hermes` or `--agent openclaw`.
The agent then rings with a `talktome_call` tool, and the plugin runs `listen` and `reply` itself.
See [host plugins](docs/HOST_PLUGINS.md).

Hermes and OpenClaw also have experimental adapters for an API session or a Gateway session.
Run `talktome providers` to see the connection methods that are ready.
[Agent support](docs/AGENT_SUPPORT.md) gives the setup and the limits.

[Agent protocol](docs/AGENT_API.md) gives the commands, the ring flow, and the local HTTP interface.

### Remote bridge (experimental)

The remote bridge lets an agent on another server ring the laptop.
Only text and call events cross the bridge. Microphone audio stays on the laptop.
The setup uses SSH:

1. Install talktome on the server: `uv tool install "talktome-local @ git+https://github.com/rohanprichard/talktome"`.
2. On the laptop, run `talktome remote-connect user@server --install-service`.
3. Restart TalkToMe.

The app opens an SSH tunnel to the server itself, so SSH must log in with a key and no password prompt.
This feature is experimental. See [remote bridge](docs/REMOTE_BRIDGE.md).

## During a call

After the agent finishes its reply, speak to start the next turn.

TalkToMe uses Smart Turn, a small local model, to decide when you finished speaking.
Settings can select a fixed pause instead. See [Smart Turn](docs/SMART_TURN.md).
[Call latency](docs/LATENCY.md) and [call timing](docs/CALL_TIMING.md) describe the delays in a call.

Settings also sets the position of the call surface: **Bottom** or **Top center**.

## Call history and call back

Open **Calls…** from the menu bar item or from Settings. The Calls window lists each call, newest first.
A missed call shows a count next to the menu bar icon and a macOS notification.
**Call back** starts a call to the same session at once, with no ring.
The **Recent** menu calls back one of the last five callers.

| Agent | Call back |
| --- | --- |
| Codex | Joins the thread again through its terminal. If no terminal holds the thread, **Open in Terminal** runs `codex resume`. |
| Claude Code | Runs `claude -p --resume` for each turn. Claude denies a tool that needs permission, unless your Claude settings allow it. |
| Hermes, OpenClaw | Uses the saved session. |
| Generic, remote | Not available. |

Transcripts are off by default. Settings can keep them for 7 or 30 days.
See [call history](docs/CALLS.md) for what the app stores and how to delete it.

## Speech providers

| Function | Local option | ElevenLabs option |
| --- | --- | --- |
| Speech recognition | Whisper Small (484 MB) or Whisper Base English (145 MB) | Scribe v2 |
| Agent voice | System voice or Kokoro | Flash v2.5 |

Whisper is the default for recognition. The system voice is the default voice.
Download a Whisper model in Settings before you use local recognition.
Kokoro downloads a 114 MB model and a 28 MB voice file. The app examines their SHA-256 hashes before use.
Local models run offline after the download.

The ElevenLabs key needs access to the voice list and to each selected speech service.
Select **Remember key** to keep the key in the macOS keychain. If you do not, the key stays in server memory until the app closes.
The app never returns the key to the interface or writes it to its settings file.
**Remove key** removes the key from the app session and from the keychain.
See [speech providers](docs/SPEECH_PROVIDERS.md) for the exact interfaces.

## Data and network access

The server listens only on `127.0.0.1:8765`. A generated local token protects its interface.
The desktop windows use an HTTP-only session cookie. Other web origins cannot use the interface.
The app keeps its token, settings, and models in `~/Library/Application Support/talktome`.
The app keeps up to 200 transcript messages and 512 events in memory. Closing the app clears them.
The call history keeps the last 500 calls in `calls/` in the data directory. See [call history](docs/CALLS.md).

The app connects to the network for these purposes only:

- Hugging Face, to download Whisper and the Smart Turn model.
- GitHub, to download the Kokoro model and voice file.
- ElevenLabs, only if you select an ElevenLabs service. ElevenLabs recognition sends microphone audio. ElevenLabs voice sends reply text. Service charges and the provider's retention rules apply.
- A Hermes or OpenClaw host, or a relay, only if you configure one.

The agent receives the text of what you say. The agent's provider and tools have their own data rules.
The cooperative command files contain conversation text.
Settings for Hermes and OpenClaw are in `agent-hosts.json` in the data directory. This file holds a plaintext token with mode `0600`.

Environment settings:

| Name | Purpose |
| --- | --- |
| `TALKTOME_DATA_DIR` | Change the local data directory |
| `TALKTOME_PORT` | Change the desktop server port |
| `TALKTOME_URL` | Set the server address for external clients |
| `TALKTOME_TOKEN` | Supply an existing shared token |
| `TALKTOME_RELOAD` | Restart the server when Python files change. Development only. |
| `TALKTOME_FLOATING_CALL` | Set to `0` to turn off the call window. The call then has no controls on screen. |
| `TALKTOME_ALLOW_REMOTE_AGENTS` | Set to `1` to permit a Hermes host that is not on this Mac. The URL must use HTTPS. |

## Build the disk image

```sh
npm run build:app
```

This command freezes the Python server into one binary, draws the icon, and runs electron-builder.
The native notch surface is off, so the build does not compile its helper. The call uses the pill.
The result is `dist/app/TalkToMe-<version>-arm64.dmg` and a zip of the app for the updater.
The script mounts the disk image after the build and examines its contents and its signature.
To reuse the last frozen server when only the desktop code changed, run `npm run build:dmg`.

To install the app, open the disk image and drag TalkToMe to Applications.
The build has an ad-hoc signature. It opens on the Mac that built it without a prompt.
On another Mac, it needs the **Open Anyway** step from [Disk image](#disk-image).
The bundle does not include the speech models. The app downloads them at first use.

## Development

```sh
uv sync --frozen        # install the Python environment
npm ci                  # install the Node packages
npm start               # start the app from source
uv run pytest -q        # Python tests
uv run ruff check       # Python lint
node --test tests/      # JavaScript tests
```

The `dev` group includes the `speech` extra, so `uv sync --frozen` installs the full voice server.
`npm test` runs the Python tests and the JavaScript tests together.
These commands start the real app for end-to-end checks:

| Command | What it examines |
| --- | --- |
| `npm run test:call` | The call window: position, stacking, and growth of the transcript |
| `npm run test:attach-call` | A full call against a real Codex session. It sends a few short model requests. |
| `npm run test:stream` | Time to first audio for ElevenLabs. It spends credits on two short replies. |

The call test turns off the Chromium sandbox.
A normal start keeps the sandbox on.

The [development notes](docs/notes/README.md) hold plans, research, and a work log. They can be out of date.

## Security

To report a security problem, read [SECURITY.md](SECURITY.md).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before you open a pull request.

## License

MIT. See [LICENSE](LICENSE).
TalkToMe uses Electron, FastAPI, faster-whisper, kokoro-onnx, Pipecat Smart Turn, and optional ElevenLabs services.
It does not contain copied SpeakType or AgentCall code. [NOTICE](NOTICE) lists the third-party references.
