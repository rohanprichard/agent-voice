# talktome

talktome is a macOS menu-bar app for voice calls with your coding agents.
An agent rings you when it needs a decision. You call an agent to ask about its work, or you join a session while it works.
The agents run on your Mac or on your own servers. talktome reaches servers over SSH, so nothing listens on the network.

The agent keeps its model, tools, files, and history. talktome does not supply a language model.

## How a call works

**An agent calls you.**

1. The agent needs you, and uses its `call_user` tool.
2. talktome shows a ring at the top of the screen. You select **Answer**.
3. The agent asks its question, or starts a conversation. You answer, and the agent continues its work.

**You call an agent.**

1. Open the menu-bar icon, pick a machine, and pick a project.
2. talktome continues the newest Claude Code or Codex session in that project, or starts a new one.
3. If a session is working now, you can join it. Your words reach the agent after its next step, and you hear its answer when it stops.

When the agent needs permission for a tool during a call, it asks you in the call: "Claude wants to run the command: npm test. Should I allow it?"

## Requirements

- A Mac with Apple silicon (arm64) and macOS 14 Sonoma or later.
- One agent host: Claude Code, Codex, Hermes Agent, or OpenClaw.
- [uv](https://docs.astral.sh/uv/) on each machine where agents run. talktome can install it for you.
- For servers: an SSH login with a key. talktome never asks for a password.
- An [ElevenLabs](https://elevenlabs.io) API key, on an account with credits. Calls are voice only.

## Install

### Disk image

1. Download `talktome-<version>-arm64.dmg` from [Releases](https://github.com/rohanprichard/talktome/releases).
2. Open the disk image and drag talktome to Applications.
3. Open talktome. macOS tells you that it cannot verify the app. Close the message.
4. Open **System Settings > Privacy & Security**. Below the message about talktome, select **Open Anyway**.
5. Open talktome again, then select **Open Anyway**.

You do steps 3 to 5 only once. macOS asks for them because the app is not notarized.
To skip the check from Terminal, run `xattr -dr com.apple.quarantine /Applications/talktome.app`.

### Build from source

You need Node.js 22 or later and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/rohanprichard/talktome
cd talktome
npm install
npm start
```

## Set up

The first time talktome opens, a short setup walks you through it:

1. **Your voice.** Paste your ElevenLabs API key, and pick a voice. talktome checks the key with ElevenLabs before it saves it.
2. **This Mac.** One button each installs uv if it is missing, installs `talktome-server` with `uv tool install`, and adds the talktome plugin to each agent it finds: Claude Code, Codex, Hermes, and OpenClaw.
3. **A test call.** talktome rings you. Answer, say anything, and hear it back.

Later, open the window from the menu bar to add servers, change the voice or the key, and see your projects.

### A server

Type a host from your SSH config, or `user@host`, and select **Check**. The checklist does the same steps on the server, over SSH. Then **Connect** adds the server.

If SSH asks for a password, add your key first with `ssh-copy-id user@host`.
If SSH does not know the server, run `ssh user@host` once in Terminal to accept its key.

### What each agent needs

| Agent | After the plugin install |
| --- | --- |
| Claude Code | Start a new session. |
| Codex | Start a new session, type `/hooks`, and trust the talktome hooks. Codex runs a plugin's hooks only after you trust them. The call tools work without this step. |
| Hermes | Restart the gateway: `hermes gateway restart`. |
| OpenClaw | Restart the gateway: `openclaw gateway restart`. |

### Speech

Calls are voice only, and speech runs on your own ElevenLabs account. talktome keeps the key in the macOS keychain, and makes a single-use token for each call.
Your voice goes from the Mac to ElevenLabs, and never to your servers. Every key on an ElevenLabs account shares that account's credits.

## How it connects

```text
talktome app ── child process ───────── talktome-server on this Mac
             └─ ssh host talktome-server ─ talktome-server on a server
                                              │
                   Unix socket, mode 0600 ────┴── call tools (MCP), hooks, Hermes, OpenClaw
```

- The app starts `talktome-server` and exchanges JSON lines with it on stdin and stdout.
- On a server, the app runs it through `ssh` with `BatchMode=yes`. SSH does the encryption. The server opens no port.
- The server lives only as long as the app's connection. While the laptop sleeps, agents on a server cannot ring you.
- Agents, hooks, and plugins reach the server through a Unix socket that only your user can open.

See [server/README.md](server/README.md) for the server's commands.

## Development

```sh
npm install
(cd server && uv sync)
npm test              # the app, with a test against the real talktome-server
npm run test:server   # the server's tests and lint
npm start             # run the app
npm run build:app     # build the disk image
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
