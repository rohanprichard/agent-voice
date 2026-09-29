# Changelog

This file lists the changes that users see. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added

- Hermes and OpenClaw can call through cooperative commands or their host APIs.
- The remote bridge (experimental) connects an agent on a server to the app on a Mac.
- `talktome remote-connect user@server` pairs the laptop with a server over SSH in one step.
- The laptop connector opens and restarts its own SSH tunnel to the relay on the server.
- `talktome remote-service install` keeps `talktome remote-up` running on the server, with systemd or launchd.
- `talktome connector-status` shows the connector and tunnel state from the running app.
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
- The relay refuses a network bind address unless you give `--allow-network`.
- `remote-up` stops its relay when it gets `SIGTERM`, `SIGHUP`, or `SIGINT`, and starts the relay again when it stops.
- `remote-init --replace` and `remote-remove` revoke the old pair, so the old laptop credential stops working.
- `remote-init` puts the relay port in a relay URL that has none, and accepts only 127.0.0.1 for its own relay.
- A remote connection ID can contain any printable character, such as the `+`, `@`, and `!` in OpenClaw session keys.

## 0.1.0

- First development version: menu-bar app, agent ring-in from Codex and Claude Code, local and ElevenLabs speech.
