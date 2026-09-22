# Agent Voice Server

> **Status:** planning / build-ready. Spec for Codex (or any agent) is in [`PLAN.md`](./PLAN.md) and [`CONTEXT.md`](./CONTEXT.md).

Local **speech-to-text + text-to-speech** for coding agents. Setup feels like [SpeakType](https://github.com/karansinghgit/speaktype) (pick a model → download bar → ready). Instead of a hotkey that types into apps, we expose a **localhost API** agents call.

## Not this repo

- ~~Join Google Meet / Teams / Zoom~~ (AgentCall already owns that skill)
- ~~Screenshare / headless browser capture~~
- ~~Global dictation hotkey~~

## Docs for builders

| Doc | What |
| --- | --- |
| [`CONTEXT.md`](./CONTEXT.md) | Why we pivoted; locked decisions; what to delete |
| [`PLAN.md`](./PLAN.md) | Setup UX, API surface, models, phases, success criteria |
| [`PRODUCT.md`](./PRODUCT.md) | Short product definition |

## Quick intent

```
Install app → pick STT model → download → Ready
     ↓
Agent: POST /v1/stt/transcribe  +  POST /v1/tts/speak
```

Default bind: `127.0.0.1:8765` (see PLAN).

## License

MIT. STT/UI spine inspired by SpeakType (MIT) — attribute upstream when code is vendored/forked.
