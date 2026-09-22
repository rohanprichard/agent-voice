# Agent Voice Server

Local **speech-to-text + text-to-speech** for coding agents. Inspired by [SpeakType](https://github.com/karansinghgit/speaktype) (MIT).

## What this is

An on-device server that exposes a localhost API for STT/TTS. Agents call it; no hotkey dictation.

```
Agent: POST /v1/stt/transcribe  →  { "text": "..." }
Agent: POST /v1/tts/speak       →  audio/wav
```

Default bind: `127.0.0.1:8765`

## What this is NOT

This is **not** a meeting-join product. It does not join Google Meet, Teams, or Zoom. See [AgentCall](https://github.com/pattern-ai-labs/agentcall) if you need that.

## For builders

Read in order:

1. [docs/CONTEXT.md](docs/CONTEXT.md) — background, locked decisions, what was dropped
2. [docs/PLAN.md](docs/PLAN.md) — full build spec: setup UX, API surface, models, phases
3. [docs/PRODUCT.md](docs/PRODUCT.md) — short product definition

## License

MIT. STT/UI spine inspired by SpeakType (MIT) — see [NOTICE](NOTICE) for attribution.
