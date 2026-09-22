# Product: on-device agent voice server (SpeakType spine)

**Working name:** Agent Voice Server (repo: `agent-voice`)

**One-liner:** A local app that sets up like SpeakType (pick a good STT model → download with a progress bar → ready), then exposes an HTTP/WebSocket API so coding agents (Claude Code, Cursor, Codex, …) can listen and speak on-device. No hotkey. No Meet/Teams join in v1. No screenshare.

## What this is / is not

| Is | Is not |
| --- | --- |
| On-device STT + TTS runtime for agents | A competitor to AgentCall's "join this Meet" skill |
| SpeakType-style setup + model catalog | Dictation into arbitrary apps via hotkey |
| Local API the agent connects to | Cloud meeting-bot / FirstCall / Recall |
| Tiny installer; models downloaded on demand | Shipping multi-GB weights inside the DMG |

## Why

AgentCall already owns "paste a Meet link, agent joins." Competing there is a dead end. SpeakType (MIT) already solved installer size, model picker, download UX, and solid local STT (Parakeet / Whisper). We reuse that spine, remove human hotkey dictation, and make **agents** the client.
