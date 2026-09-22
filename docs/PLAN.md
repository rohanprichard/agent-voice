# Build plan — on-device agent voice server

For Codex / any implementer: this is the spec. Prefer forking SpeakType over rewriting STT from scratch.

## 0. Repo hygiene (do first)

1. Remove all AgentCall-era artifacts if still present:
   - Old `SKILL.md` join-meeting / AgentCall CALL_LOOP content
   - `.claude-plugin/` marketplace that installs "join Meet"
   - `scripts/join.py`, AgentCall bridge wrappers, `examples/coding-companion` Meet guides
   - README claiming Meet/Teams/Zoom join via AgentCall
2. Keep MIT LICENSE; add SpeakType attribution in README and NOTICE.
3. This repo's purpose is **local STT+TTS + agent API**, not meeting bots.

Suggested future rename: `agent-voice` / `speakagent` / `ondevice-voice` (owner can rename on GitHub). Working title in docs: **Agent Voice Server**.

---

## 1. Product flow (user-facing)

### First run (keep SpeakType's shape)

1. Install app (DMG / exe / AppImage or `cargo tauri` / equivalent).
2. Open app → short onboarding (permissions: **Microphone** required; Accessibility **not** required in v1 if we are not injecting keystrokes into other apps).
3. **AI Models** screen: catalog of STT models with size, speed, accuracy, language coverage, min RAM.
4. App **recommends** one model for this machine (chip / RAM), like SpeakType.
5. User clicks download → **progress bar** → model ready.
6. Optional: download a default **TTS voice pack** (separate download; same pattern).
7. Status becomes **Ready**. Local API listens on a fixed port (configurable).
8. Show: base URL, example `curl`, and a one-line "tell your agent…" snippet.

### Steady state

- App runs in tray / background.
- No hotkey for dictation.
- Agents call the local API.
- Settings: change STT model, TTS voice, port, log level, allowlist (later).

---

## 2. What to take from SpeakType

Upstream: https://github.com/karansinghgit/speaktype (MIT)

**Reuse**

- Tauri + React UI shell pattern (SpeakType 2 `desktop/`)
- Model catalog + download manager (`models.rs` concepts)
- Engine abstraction: Whisper (whisper.cpp) + Parakeet (ONNX) (`engine/`)
- Device capability → recommended model
- "Only one large model in RAM at a time"
- Tiny installer; weights **not** in the binary

**Remove / do not port**

- Global hotkey / push-to-talk
- Paste / type-into-focused-app (`paste`, accessibility typing)
- Dictation history-as-primary-UX (optional later for debugging)
- Any "works in every text field" marketing

**Add**

- Local HTTP + WebSocket **Agent API** (section 3)
- TTS pipeline (SpeakType is STT-first; we need speak-out for agents)
- Minimal Agent Skill doc: "how Claude Code connects to this server" (separate thin skill file is OK; not an AgentCall clone)

---

## 3. Agent API (v1)

Bind: `127.0.0.1` only by default. Port default `8765` (configurable).

Auth (v1 minimal): optional shared token in `Authorization: Bearer <token>` or `X-Agent-Voice-Token`, generated at first run and shown in UI. Empty token = open on localhost (dev mode).

### 3.1 Health & setup

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/health` | `{ "status": "starting"\|"needs_model"\|"ready", "stt_model": "...", "tts_voice": "...", "version": "..." }` |
| `GET` | `/v1/setup` | Setup state for UI/agents: permissions, downloaded models, recommended model id |
| `GET` | `/v1/models` | Catalog + download status (mirrors SpeakType model list) |
| `POST` | `/v1/models/{id}/download` | Start download; returns job id |
| `GET` | `/v1/models/downloads/{job_id}` | Progress `{ "pct": 0–100, "bytes": ..., "state": "..." }` |
| `POST` | `/v1/models/{id}/activate` | Load this STT model (unload previous) |

### 3.2 Speech-to-text

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/stt/transcribe` | Body: raw audio (`audio/wav` or `application/octet-stream` PCM 16 kHz mono) **or** multipart file. Query/header: `language=auto\|en\|...`. Response: `{ "text": "...", "language": "...", "duration_ms": N }` |
| `WS` | `/v1/stt/stream` | Client sends audio chunks (binary frames); server sends JSON events: `partial`, `final`, `error`, `ready`. |

### 3.3 Text-to-speech

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/tts/voices` | List installed voices |
| `POST` | `/v1/tts/speak` | JSON `{ "text": "...", "voice": "default" }`. Response: `audio/wav` **or** JSON with base64 (prefer raw wav for agents). |
| `WS` | `/v1/tts/stream` | Optional v1.1: streamed PCM/wav chunks + `tts.done` event |

### 3.4 Session helper (optional but useful for agents)

| Method | Path | Purpose |
| --- | --- | --- |
| `WS` | `/v1/session` | Duplex session: server can nudge `listen.start` / client sends audio; client sends `{ "type": "speak", "text": "..." }`; events for `user.utterance`, `agent.speaking`, `error`. Keeps one conversation-shaped channel for Claude Code skills. |

### 3.5 Logging (secondary — stub OK in v1)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/logs?tail=100` | Recent request metadata (no raw audio by default) |
| Setting | `store_audio=false` | Default off; privacy |

Example agent usage (document in README):

```bash
# health
curl -s http://127.0.0.1:8765/v1/health

# transcribe a wav
curl -s -X POST http://127.0.0.1:8765/v1/stt/transcribe \
  -H "Content-Type: audio/wav" \
  --data-binary @utterance.wav

# speak
curl -s -X POST http://127.0.0.1:8765/v1/tts/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"Build is green."}' \
  --output reply.wav
```

Claude Code skill (thin): "If the user wants voice I/O, call this local server; if `/v1/health` is `needs_model`, tell the user to finish setup in the app."

---

## 4. Models (v1 defaults)

### STT

| Id | Engine | Approx size | Role |
| --- | --- | --- | --- |
| `parakeet-tdt-v3` | ONNX Parakeet | ~640 MB | **Default recommend** on Apple Silicon / modern CPU (EN + EU langs) |
| `whisper-small` / `whisper-medium` / `whisper-turbo` | whisper.cpp | ladder | Multilingual fallback; show in catalog |

Rules from SpeakType: recommend by device; download on demand; never load two big models at once.

### TTS

Pick **one** good default for v1 (implementer choice, document it):

- Piper (very small, OK quality), or
- Kokoro-class / similarly high quality if packaging is sane on Mac/Win/Linux

Same pattern: small app, voice files downloaded on demand, progress bar.

---

## 5. Architecture

```
┌─────────────────────────────────────────┐
│  UI (React/Tauri)                        │
│  Onboarding · Models · Ready status ·    │
│  API token · Port                        │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│  Core (Rust preferred, SpeakType-based)  │
│  model download · STT engine · TTS       │
│  HTTP/WS server 127.0.0.1:8765           │
└─────────────────────────────────────────┘
                    │
         Claude Code / Cursor / Codex
```

- Prefer extending SpeakType's Rust core over a Python FastAPI reimplementation for STT performance — unless forking cost is too high; if so, Phase A = Python prototype API + whisper.cpp/parakeet bindings, Phase B = Tauri UI parity.
- **Recommendation for Codex:** start from SpeakType `desktop/` fork; delete dictation/hotkey/paste; add `axum`/`hyper` (or Tauri sidecar) API module.

---

## 6. Implementation phases

### Phase A — vertical slice (ship-worthy demo)

1. Fork SpeakType desktop app into this repo (or subtree) with attribution.
2. Strip hotkey + paste-into-app.
3. Keep model picker + download bar + mic permission.
4. Add `GET /v1/health`, `POST /v1/stt/transcribe`, `POST /v1/tts/speak`.
5. README: setup screenshots + curl examples + "point your agent here."
6. Success demo: agent curls STT on a wav and plays TTS reply locally.

### Phase B — agent ergonomics

1. WebSocket streaming STT (`/v1/stt/stream`) and optional `/v1/session`.
2. Thin `SKILL.md` for Claude Code: discover server, check health, transcribe, speak.
3. Token auth + tray "Ready / Needs model."

### Phase C — polish

1. Logging UI, dictionary/replacements (optional, SpeakType has dictionary).
2. Auto-update, signed builds.
3. Rename GitHub repo to match product.

**Out of scope until explicit reopen:** Meet/Teams/Zoom join, AgentCall, screenshare, LiveKit skill pack.

---

## 7. Success criteria (v1)

- Fresh machine: install → recommend model → download bar → Ready, without a developer terminal except optional curl.
- Agent can STT and TTS only via localhost API (no hotkey).
- Installer stays small; models fetched on demand.
- README explains relationship to SpeakType (fork/inspiration, MIT) and that this is **not** a meeting-join product.
- No AgentCall strings or Meet-join claims remain in the repo.

---

## 8. References

- SpeakType: https://github.com/karansinghgit/speaktype
- SpeakType site: https://tryspeaktype.com
- AgentCall (explicitly **not** what we build): https://github.com/pattern-ai-labs/agentcall
- Prior cancelled scaffold lived in this repo on branch `cursor/join-call-scaffold-a1e7` / PR #1 — do not revive.
