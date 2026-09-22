# Discussion context (2026-09-22)

This file is for a coding agent (e.g. Codex) spinning up on this repo. Read it before building.

## Owner

Rohan Richard — GitHub `rohanprichard`. Hyderabad. Stack: Python, TypeScript, FastAPI, React. Has FastRTC demos historically; **FastRTC is explicitly dropped** for this product.

## How we got here (compressed)

1. Goal: GitHub stars + followers fast; viral "agent has a voice" demos.
2. Explored AgentCall / SKI ("Claude joins Meet/Teams/Zoom"). AgentCall = skill + cloud meeting bot (talk, screenshare, chat). Skill market already taken by `pattern-ai-labs/agentcall`.
3. Scaffolded an AgentCall-backed skill in this repo (`join-call`). **That direction is cancelled.** Delete any leftover AgentCall skill/bridge/plugin files; do not build on them.
4. User rejected competing with AgentCall's generic join skill.
5. User wants an **on-device server/app**: STT + TTS locally. Screenshare dropped for v1 (so no headless browser capture into meetings).
6. Reference product: **SpeakType** — `https://github.com/karansinghgit/speaktype` (MIT). Cross-platform Tauri + React + Rust. ~18MB macOS DMG; models 75MB–1.6GB downloaded after install. Engines: NVIDIA Parakeet TDT 0.6B v3 (ONNX) and Whisper (whisper.cpp). Model catalog with speed/accuracy bars and device-based recommendation.
7. Product lock: **Fork SpeakType's setup spine** (onboarding → pick model → download bar → ready). **Remove hotkey / paste-into-focused-app.** **Expose a local endpoint** so an agent connects and uses STT/TTS. Logging secondary.

## Locked decisions

- Fork / heavily reuse SpeakType (MIT) for setup + engines — attribute LICENSE.
- No global hotkey dictation in v1.
- No Google Meet / Teams / Zoom join in v1.
- No screenshare / no AgentCall dependency in v1.
- Good models only (Parakeet-class / solid Whisper) — not toy STT.
- Agent API is the product surface once setup is done.
- LiveKit "voice agent skills pack" is a **separate** future product — not this repo.

## Adjacent repos (do not mix)

- `rohanprichard/join-call` — this repo; repurposed for the SpeakType-fork agent voice server plan.
- Earlier AgentCall PR scaffold — obsolete; remove.
- LiveKit skill pack — not started; keep out of this tree.
