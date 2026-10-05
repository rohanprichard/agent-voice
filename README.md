# talktome

[![PyPI version](https://img.shields.io/pypi/v/talktome-server?label=PyPI%20server)](https://pypi.org/project/talktome-server/)
[![Server Python versions](https://img.shields.io/pypi/pyversions/talktome-server?label=server%20Python)](https://pypi.org/project/talktome-server/)
[![Tests](https://github.com/rohanprichard/talktome/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/rohanprichard/talktome/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/rohanprichard/talktome)](https://github.com/rohanprichard/talktome/releases/latest)
[![MIT license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/rohanprichard/talktome/blob/main/LICENSE)
[![macOS 14 or later, Apple silicon](https://img.shields.io/badge/macOS-14%2B%20%7C%20Apple%20silicon-lightgrey)](#install)

Voice calls with your coding agents, from the macOS menu bar.

Your agents call you when they need a decision or finish a task. You call them to ask how the work is going, or to join a session while it works. The agents run on your Mac or on your own servers, and talktome reaches servers over SSH.

**[Download the latest release](https://github.com/rohanprichard/talktome/releases/latest)** · macOS 14 or later, Apple silicon

## How it works

- **An agent calls you.** It uses its `call_user` tool. A ring appears at the top of your screen, you answer, and you talk.
- **You call an agent.** Pick a project from the menu bar. talktome continues the newest Claude Code or Codex session there, or starts a new one.
- **You join a session.** If a session is working now, you can join it. Your words reach the agent after its next step.
- **Permission in the call.** When the agent needs to run a tool, it asks you: "Claude wants to run the command: npm test. Should I allow it?"

The agent keeps its own model, tools, and files. talktome only carries the call.

## Install

1. Download `talktome-<version>-arm64.dmg` from [Releases](https://github.com/rohanprichard/talktome/releases), and drag talktome to Applications.
2. Open talktome. macOS says it cannot verify the app, because the app is not notarized yet.
3. Open **System Settings > Privacy & Security**, select **Open Anyway**, and open talktome again.

You do steps 2 and 3 once. Or run `xattr -dr com.apple.quarantine /Applications/talktome.app`.

You also need:

- An [ElevenLabs](https://elevenlabs.io) API key, on an account with credits. Calls are voice only. The first call downloads local speech detection models.
- At least one agent: Claude Code, Codex, Hermes Agent, or OpenClaw.

## Set up

The first time talktome opens, a short setup walks you through three steps:

1. **Your voice.** Paste your ElevenLabs key, and pick a voice.
2. **This Mac.** Install [uv](https://docs.astral.sh/uv/) and `talktome-server`, and add talktome to your agents, with one button each.
3. **A test call.** talktome rings you. Say anything, and hear it back.

After an install, each agent needs one more step:

| Agent | Then |
| --- | --- |
| Claude Code | Start a new session. |
| Codex | Start a new session, type `/hooks`, and trust the talktome hooks. |
| Hermes | Run `hermes gateway restart`. |
| OpenClaw | Run `openclaw gateway restart`. |

### Add a server

Open the window from the menu bar. Under **Machines**, type a host from your SSH config, or `user@host`, and select **Check**. talktome does the same setup on the server over SSH. Then select **Connect**.

talktome uses SSH keys only. If SSH asks for a password, run `ssh-copy-id user@host` first.

## Speech and pauses

The app uses Silero to detect speech and Smart Turn to detect when a thought ends.
A pause can remain part of the same thought.
After five seconds of silence, the app requests transcript completion even if the model remains uncertain.
Speak during a reply to pause its audio. The app resumes if detection produces no words or a brief “mm-hmm” or “uh-huh”.
A spoken request stops the reply. The agent receives the request when the thought ends.
Stopping speech does not cancel the agent's current tool or terminal task.
The **Stop reply** button remains available.

The first call downloads the detection models and their Python dependencies through `uv`.
The app keeps the models on the Mac for later calls. Calls still use ElevenLabs for transcription and speech output.

## Privacy

- Nothing listens on the network. The app runs `talktome-server` as a child process on your Mac, and through `ssh` on a server.
- Your voice goes from your Mac to ElevenLabs, and never to your servers. Your key stays in the macOS keychain.
- The connected agent receives what you say, and runs with its own permissions.

See [SECURITY.md](SECURITY.md) for details, and [server/README.md](server/README.md) for the server.

## Develop

You need Node.js 22 or later and uv.

```sh
git clone https://github.com/rohanprichard/talktome && cd talktome
npm install
(cd server && uv sync)
npm start             # run the app
npm test              # app tests, including one against the real talktome-server
npm run test:server   # server tests and lint
npm run build:app     # build the disk image
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for releases and style.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
