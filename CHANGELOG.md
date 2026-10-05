# Changelog

This file lists the changes that users see. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added

- Local Silero speech detection and Smart Turn detection for pauses within a thought.
- Voice interruption with reply recovery after a false interruption or brief acknowledgment.

### Changed

- Transcript segments stay in one user turn until the thought ends, with a five-second silence limit.
- The first call downloads speech detection models and Python dependencies. Later calls use the cached files.


- The app installs `talktome-server` from PyPI, at the same version as the app. The disk image no longer contains the server.

## 0.2.0 - 2026-10-01

### Changed

- talktome is now the app and `talktome-server`. The app runs `talktome-server` on this Mac and on your servers over SSH, and nothing listens on the network.
- Agents ring you with the `call_user` tool, over MCP, instead of the `talktome call` command.
- Calls are voice only. Speech runs on your own ElevenLabs account, and a key is required.
- The call surface grows out from under the menu bar, rings, and widens into the call pill when you answer. The transcript opens below it.

### Added

- A first-run setup: your ElevenLabs key and a voice, this Mac and its agents, and a test call.
- Call a project on any connected machine from the menu bar. talktome continues the newest Claude Code or Codex session there, or starts a new one.
- Join a Claude Code or Codex session while it works. Your words reach the agent after its next step.
- The agent asks you in the call before it runs a tool that needs permission.
- Choose any voice in your ElevenLabs account, with a sample to play.
- Add a server over SSH from the window: talktome checks SSH, installs uv and `talktome-server`, and adds the plugin for each agent.
- Plugins for Claude Code, Codex, Hermes, and OpenClaw. Installing one removes the earlier app's `talktome` skill.
- `talktome-server` on PyPI.
- When speech stops, the call says why, for example when the ElevenLabs account is out of credits.

### Removed

- The local Python server, the local speech models, Smart Turn, and the notch surface.
- Typing to an agent.
- The Calls window and call history. They come back in a later release.

## Not released: changes to the earlier app after 0.1.0

### Added

- Hermes and OpenClaw can call through cooperative commands or their host APIs.
- Smart Turn decides when the user stops speaking.
- The user can interrupt the voice by speaking.
- The notch call surface on Macs with a notch.
- A release workflow builds the disk image and a zip when a `v*` tag is pushed.
- A Homebrew cask for the future tap `rohanprichard/tap`.
- The Calls window lists recent calls. You can call back Codex, Claude Code, Hermes, and OpenClaw sessions with no ring.
- The menu bar shows a count of missed calls, and macOS shows a notification for each one.
- The **Recent** menu calls back one of the last five callers.
- Settings can keep call transcripts for 7 or 30 days. Transcripts are off by default.

### Changed

- Dark is the default theme. You can select System or Light in Settings.
- OpenClaw session keys with `+`, `@`, and `!` can ring. A Codex session ID keeps the strict pattern.
- The app asks the login shell for PATH again after 60 seconds, so a new PATH folder is found without a restart.
- The app has an ad-hoc signature and needs macOS 14 or later.
- The frozen server is 146 MB instead of 210 MB.
- The Python package installs without the speech stack. The desktop server needs the `speech` extra.

### Removed

- The Model Context Protocol (MCP) server, the `talktome-mcp` command, and the MCP registration for agent clients.
- The JSON Lines bridge, the Python agent client, and the `/v1/agent/connect`, `listen`, `heartbeat`, and `reply` routes.
- Managed sessions, where TalkToMe started Codex or Claude Code itself, and the `/v1/managed/start` route.
- The `/v1/agents`, `/v1/connection`, `/v1/call/start`, and `/v1/conversation/clear` routes.
- The browser-only pages of the main window: the conversation page, the browser setup flow, the sample call, and the pair screen.
- The experimental remote bridge, its commands, and its server components.

### Fixed

- The notch helper starts on macOS 14. The build targeted the macOS of the build Mac.
- A model download no longer starts a second frozen server for the multiprocessing resource tracker.
- Smart Turn now loads. The model has a variable batch size, and the check required a fixed one.
- Hermes turns now finish. The adapter now reads the event name from the event data.
- Hermes approvals now send the `choice` field that Hermes requires.
- OpenClaw now connects. The subscribe request now sends the `key` field.
- OpenClaw events from other runs in the session no longer fill the event queue.
- A cooperative turn ends with an error when the agent stops listening for 5 minutes.
- The app reads the `/tmp` request folder only if the user owns it, and replies do not follow symbolic links.
- Command lookups no longer block the server.
- Approval requests show in the call surface. Before, each request waited 180 seconds and was denied.

## 0.1.0

- First development version: menu-bar app, agent ring-in from Codex and Claude Code, local and ElevenLabs speech.
