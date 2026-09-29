# AgentCall: latency and voice pipeline architecture

Research date: September 24, 2026.
Every source below was read on that date at branch `main`, commit `9b96f6739c3ea3384fbb8c904c63b885d6e455ff`, which is the tree returned by the [repository tree API](https://api.github.com/repos/pattern-ai-labs/agentcall/git/trees/main?recursive=1).
No live call was placed, no API key was used, and no audio was generated.
All findings come from the repository's own files and its issue tracker.

This note covers latency, turn-taking, chunking and transcription timing.
Its companion, [AgentCall: overall architecture and the join flow](AGENTCALL_ARCHITECTURE.md), covers what the system is made of, the end-to-end join sequence, the wire protocol, and what an integrator writes.

## What this repository actually is

This is the single most important finding for anyone trying to learn from the design, so it comes first.

The project is branded as an AgentCall skill, and the repository is the **client half of a hosted service**.
The README describes it as a skill that "runs on top of a coding agent" and requires "An AgentCall account" with a hosted API key ([README.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/README.md)).
The Python bridge says the same thing directly: "It is NOT a standalone agent. It has NO LLM. The agent framework that spawns this script IS the LLM. This script is a thin communication layer" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

So the repository contains a WebSocket bridge, four bridge variants, seven UI templates, an audio player, and about ninety kilobytes of Markdown documentation.
It does **not** contain the speech recogniser, the text-to-speech engine, the voice-intelligence service, or the meeting bot.
Those live behind `api.agentcall.dev` and are named in the docs as FirstCall (meeting infrastructure) and GetSun (collaborative voice intelligence) ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

A full-text search of everything downloaded from the repository found no speech-to-text provider name at all: no Deepgram, Whisper, AssemblyAI, Speechmatics, or Google.
The only text-to-speech engine named anywhere is Kokoro, and only in passing, in bridge comments that describe dispatching sentences "for pipelined Kokoro synthesis" and in a note that Kokoro mispronounces em dashes ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py), [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

Questions 2 and 4 below therefore have a firm answer that is not the one the question assumes: the provider and model are **not stated in the repository**, because the code is not in the repository.
Everything downstream of the WebSocket boundary is unverifiable from primary sources, and this note says so explicitly wherever it applies rather than filling the gap with a plausible guess.

## Turn-taking

Turn-taking is not one mechanism. The repository implements three separate ones, and which one applies depends on the mode and the voice strategy.

### The hosted recogniser decides the utterance is over

In every mode, the end-of-utterance signal itself comes from the service. The bridge comments state that `transcript.final` "is FirstCall STT's authoritative end-of-utterance signal (fires after ~600ms of detected silence)" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
That is the only end-of-turn timing constant the recogniser exposes, and the repository does not document how it is configured or whether it can be changed.
It is described as a property of the hosted service, not as a setting the caller controls.

### The bridge's VAD buffer, which is really a coalescing timer

Because that recogniser splits long utterances into several `transcript.final` events, the bridge adds its own buffer on top.
The comments give the motivating example: a speaker who pauses mid-sentence produces `"Can you check the"`, then `"health endpoint"`, then `"and also the database"` as three separate finals, which the agent would otherwise read as three separate instructions ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

The `VADBuffer` class is a three-state machine weighted on the final rather than the partial.
The cooldown starts when a `transcript.final` arrives and **restarts on each new final**, so a slow speaker does not lose their earlier words.
A `transcript.partial` cancels any running cooldown and returns the machine to waiting, on the reasoning that the user has resumed ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

The cooldown constant is `1.25` seconds in the constructor, in the Python argument parser default, and in the Node argument default, and it is exposed as the `--vad-timeout` flag ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py), [bridge.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/node/bridge.js)).
The coding-companion example documents the same feature as "2 seconds" and suggests raising it to 3.5 for slow speakers or lowering it to 1.0 for fast back-and-forth ([coding-companion README](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/examples/coding-companion/README.md)).
The example prose disagrees with the shipped default. The code is the authority, and the code says 1.25.

The genuine VAD model, Silero, is not in the default path at all. It is offered as an optional browser-side addition in the interruption guide, described as a "~1.5MB ONNX" model running "via ONNX Runtime Web" with "Sub-100ms detection latency", and the guide is explicit that it is for interruption detection rather than for deciding when a turn has ended ([interruption-handling.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/interruption-handling.md)).

### The collaborative service does the timing

When `voice_strategy` is `collaborative`, none of the above gates a response. The hosted voice-intelligence service listens for the bot's name, waits for silence, and speaks; the bridge is not in the loop.
The configuration defaults are `barge_in_prevention: true`, which the docs gloss as "Wait for silence before speaking", and `interruption_use_full_text: true` ([collaborative-mode.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/collaborative-mode.md)).
The state machine is published as seven states: `listening`, `actively_listening`, `thinking`, `waiting_to_speak`, `speaking`, `interrupted`, and `contextually_aware`, the last being a follow-up window that "Lasts ~20 seconds after speaking" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
Beyond that twenty-second window, and the two booleans, the repository states no collaborative-mode timing constants, because the timing lives in the service.

## Speech-to-text

The provider is not stated. As noted above, the repository names no recogniser, and no file in the tree configures one.

The interface does expose both a streaming and a batch surface, which is the useful part to copy.
`transcript.partial` carries in-progress text and is emitted only in `direct` strategy; `transcript.final` carries a completed utterance and is emitted in all strategies ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
The constraint table confirms the split: `transcript.partial` events require the direct strategy ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
So partial results are a direct-mode feature and are explicitly withheld from the agent in collaborative mode, where the docs say "Your agent receives `transcript.final` events only (not partials — GetSun handles those)" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

That is a deliberate design choice worth naming: the agent that cannot respond quickly is not given the fast, noisy signal.
The partials are instead routed to the component that must react within milliseconds.

One documented property removes a whole class of bugs.
FirstCall "does NOT transcribe bot audio", so every transcript event during bot speech is a genuine human interruption rather than an echo of the bot ([interruption-handling.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/interruption-handling.md)).
The bridge relies on this and deliberately does not filter transcripts by speaker name, on the reasoning that "a participant who happens to share the bot's display name is still a real human and the agent must hear them" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

Partial transcripts interact with turn-taking in two ways.
They cancel the bridge's VAD cooldown, as described above, and they lock the barge-in gate, so the agent cannot speak while a partial is pending ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
They also drive interruption detection in the browser, which the next section covers.

## The agent loop

There is no separate agent step inside the repository. There is a bridge process and an agent framework that spawns it, and the two are the same loop. The architecture is stated in the bridge docstring: "The agent framework processes transcripts as instructions (same as text input) using its existing session context — no separate context loading needed" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

The protocol is newline-delimited JSON in both directions.
The agent writes commands such as `{"command": "tts.speak", "text": "...", "voice": "af_heart"}` to stdin and reads events such as `{"event": "user.message", "speaker": "Alice", "text": "..."}` from stdout ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
The bridge does the blocking, and the agent is idle between events.

How long the agent step blocks the audio path is the crux of the latency question, and the repository answers it in two different ways depending on how the agent is wired to the bridge.

In the recommended configuration, the agent blocks on a stream and is woken by the kernel. The docs describe Method 1 as "kernel-driven, zero polling, zero idle tokens" and state that "polling (Method 3) burns 60,000-180,000 tokens per hour on idle polling" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
Method 2, an interactive subprocess, is called "the ideal method — zero polling delay" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
None of these methods is a timing budget, though. They describe how the agent learns about an event, not how long the model then takes to produce an answer, and the repository never states the latter for the bridge path.

In the fallback configuration, the agent polls a file and the delay is explicit. The documented poll intervals are 2-3 seconds in direct mode and 5-10 seconds in collaborative mode, with the direct-mode rationale given as "You ARE the voice — silence = broken bot" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
Claude Code is called out as adding "2-5 seconds of latency per event" when polling ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

Token streaming is the one place where the architecture deliberately does not exist in the bridge path. The bridge accepts complete text, not tokens. Nothing in the repository describes handing partial model output to the text-to-speech layer.

Speaking before the full answer is generated happens **inside the hosted service**, not at the agent boundary. The clearest statement is that "GetSun responds in <1 second — the agent will NEVER beat it to a response", and the recommended pattern is that the service speaks a holding line such as "Sure, let me check on that for you" while the agent works ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
That is a latency-hiding pattern rather than a streaming one, and it is worth being precise about the difference: the service does not stream a partially generated answer, it generates a short complete answer that is appropriate without the information the agent has not yet fetched.

## Text-to-speech

The engine is named once, as Kokoro, and never described. The bridge comments refer to "pipelined Kokoro synthesis" and the skill document notes that "Direct mode voices (Kokoro TTS) use `af_heart`, `am_adam` etc." ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py), [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The collaborative path uses a different system with different names, and the docs warn that the two are "different systems, names are NOT interchangeable" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
There are 54 voices across 9 languages ([README.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/README.md)).

Speech is streamed as generated, not buffered into a whole file, and the repository contains working code that consumes it. The standalone endpoint returns `audio.chunk` messages with `chunk_index` and `is_last` ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)), and the audio player's comments describe chunks arriving "in small chunks (each chunk is a fraction of a sentence)" with a worked example where four chunks carry 200, 300, 250 and 280 milliseconds of audio ([webpage-audio.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/webpage-audio.md)).

The chunking strategy is a two-level scheme, and this is the most directly transferable part of the design.

The **outer** level is sentence splitting, and it is done by the bridge rather than the service. When the agent sends one `tts.speak` containing several sentences, `_split_sentences` breaks it on `(?<=[.!?])\s+|\n+` and dispatches one backend `tts.speak` per sentence ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
The stated rationale is latency: "first audio reaches the meeting in <1s regardless of paragraph length, played/not_played boundaries stay exact, and the agent still receives one tts.done per tts.speak" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
A single queue with a `created_at`, an `expected` count and a `received` count aggregates the per-sentence `tts.done` events back into the one completion event the agent expects, with a 60-second timeout checked every 5 seconds as a safety net ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
The splitter is honestly documented as a heuristic that "over-splits on abbreviations ("Mr. Smith") and decimals ("3.14")", with the escape hatch that the per-sentence agent pattern "bypasses this path entirely" ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)).

The **inner** level is the service's own framing, and the only constant given is in the `meeting` destination description: "resample 24→16kHz, rechunk 20ms, inject into call" ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).

Gaps between chunks are avoided by scheduling rather than by hoping. The player does not call `start(0)` per chunk; it maintains a `nextTime` cursor, plays a chunk at `nextTime`, and advances the cursor by that buffer's duration, so "each chunk starts exactly when the previous one ends" ([webpage-audio.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/webpage-audio.md)).
The guide names the wrong implementation and the failure it causes: playing each chunk immediately either overlaps the previous chunk or leaves a gap ([webpage-audio.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/webpage-audio.md)).
The shipped implementation in `playChunk` is exactly the cursor scheme, and it also catches up when the cursor has fallen behind: `if (this.nextTime < now) { this.nextTime = now; }` ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)).

## Transport

The meeting-facing transport is hosted and unspecified. The documentation says only that FirstCall is "meeting infrastructure", that it "loads your webpage in the rendering environment" and captures "whatever the page plays (Web Audio API, `<audio>` tags, etc.)", and that in audio mode the server sends audio to FirstCall, which "plays it in the meeting" ([webpage-audio.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/webpage-audio.md), [SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The bot joins Google Meet, Zoom and Microsoft Teams as a participant ([README.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/README.md)).
There is no mention of WebRTC, LiveKit or Daily anywhere in the tree, and the page is a headless browser rather than a media client, so the most that can honestly be said is that the meeting leg is a cloud browser and not a media SDK. Whether FirstCall uses WebRTC internally is not stated.

The agent-facing transport is a raw WebSocket carrying JSON text, not binary media. The connection is `wss://api.agentcall.dev/v1/calls/{call_id}/ws?api_key=...`, and on connect it receives a `call.state` snapshot ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
Audio inside that JSON is base64.

Three audio formats appear, and they are worth keeping separate:

| Direction | Format | Source |
| --- | --- | --- |
| Service to page or agent | 24 kHz, 16-bit signed, mono, little-endian, raw PCM, base64 in JSON | [webpage-audio.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/webpage-audio.md) |
| Agent to meeting | 16 kHz, 16-bit, mono PCM | [api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md) |
| Meeting to agent | base64 PCM 16 kHz, only with `audio_streaming: true` | [api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md) |

The conversion chain is documented without ambiguity: 24 kHz PCM is generated, the server resamples to 16 kHz and rechunks to 20 milliseconds for the meeting, and the page-side route keeps 24 kHz and decodes it with `AudioContext` at a sample rate of 24000 ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md), [agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)).
Meeting audio reaches a custom page through `navigator.mediaDevices.getUserMedia({ audio: true })`, which the page must call on load because the rendering environment cannot click a button to grant permission ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).

## Measured latency

There are no measured end-to-end numbers in this repository. What exists is a set of target figures stated as design intent, plus one latency figure that appears inside a fictional support scenario.

The target figures, quoted exactly:

- "respond via text-to-speech (54 voices, 9 languages, <1s latency)" and it is listed as a feature of the hosted service rather than a benchmark ([README.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/README.md)).
- "First audio reaches the meeting in <1s automatically — send your response in one `tts.speak`" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
- "`tts.speak` — AgentCall TTS (54 voices, 9 languages, <1s latency)" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
- "first audio reaches the meeting in <1s regardless of paragraph length" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
- "GetSun responds in <1 second" and "GetSun is always faster (<1s)" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
- The sentence-by-sentence advice is given with the same number: "Send text sentence by sentence for lowest latency (<1s to first audio)" ([api.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/api.md)).
- Silero's browser detection is given as "Sub-100ms detection latency" ([interruption-handling.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/interruption-handling.md)).

The one figure that looks like a measurement is not one. "Monitoring shows latency back to normal (<200ms p95)" and "P95 latency at 450ms (normal: 120ms)" appear as sample values inside a customer-support `context` string that exists to demonstrate how to load a knowledge scratchpad ([collaborative-mode.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/collaborative-mode.md)).
It describes a fictional TTS incident at the vendor. It is not a measurement of anything.

What the repository does document honestly is where time goes that is not latency. The bot takes "30-90 seconds to join the meeting" after call creation, and agents are told explicitly not to treat that as failure ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The 60-second TTS batch timeout and the 1.5-second barge-in cooldown are also, in effect, latency budgets, but budgets for failure recovery rather than for speech.

## Other latency-relevant techniques

Beyond the turn-taking and chunking mechanics, five things in the repository are specifically about making the system feel faster than it is.

**Barge-in is a gate, not a check.** The bridge's TTS dispatcher waits on an `asyncio.Event` that is set only when the state machine returns to idle, so the wait is event-driven with no polling, and the gate is non-blocking for every other command: `send_chat`, `raise_hand`, `mic`, `screenshot` and `leave` are still processed inline while a `tts.speak` is held ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
The state machine is anchored to `transcript.final` rather than to partial cadence, with the reasoning that "partial events can fire mid-sentence; their cadence is noisy" and that "network jitter delays partials, making time-since-last-partial a poor proxy for 'is the human still speaking right now'" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
A 30-second speaking fallback was deliberately removed, on the argument that the machine is self-healing because "the human will inevitably speak again, producing a final that transitions COOLDOWN → IDLE" ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

**A raise-hand timer that converts waiting into a visible signal.** If the gate stays locked for more than ten seconds, `GateRaiseHand` raises the bot's hand in the meeting so participants can see it has something to say, and in the visual bridge it also sets the avatar to `waiting_to_speak` ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).

**Debounced interruption, which is a false-positive budget rather than a latency optimisation.** A single `transcript.partial` does not cut the bot off, because partials also fire for "fillers ("mhm", "uh"), background noise, mic bumps, and brief acknowledgments", and a naive rule "cuts the bot off constantly in noisy group meetings" ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)).
The player suspends the `AudioContext` on the first partial, which pauses audio mid-stream and stops `currentTime` advancing, then counts words across incremental partials within a window.
The constants are `wordThreshold = 2` and `partialWindowMs = 2000` ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)).
If the window expires below the threshold the context resumes and the bot continues from where it paused, and the suspension itself gives immediate visual feedback through `onSuspensionStart` ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)).
The collaborative path bypasses the debounce entirely, because "that signal comes from a sophisticated voice intelligence service and is treated as authoritative" ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)).

**A chunk gate that stops a cleared utterance from restarting.** After a confirmed interrupt the backend does not know yet, so "its TTS pipeline keeps streaming in-flight chunks for the original utterance for hundreds of ms".
The player therefore sets an `interrupted` flag that makes `playChunk` silently drop incoming chunks until the next `tts.started` event reopens the gate ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)).
This is a small piece of state that closes a real hole, and the failure it prevents is precisely the one described as the reason the event matters: without it the bot "keeps 'talking' through queued audio even though it was interrupted" ([webpage-audio.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/webpage-audio.md)).

**Filler speech and speculative context, both aimed at the same wait.** The documented pattern is to acknowledge first and work second: "If your agent needs time to process (LLM call, file search, running commands), the user hears silence while you work. Send a quick acknowledgment first ... then do your processing, then send the full response" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The collaborative variant is more interesting, because the holding line is generated by the hosted service from context rather than by the agent, so it costs the agent nothing and arrives in under a second while the agent fetches data ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
Prediction is then used to make the eventual answer instant: the agent is told to preload data into the service's context before anyone asks, so that "GetSun answers instantly (<1s) instead of deferring ("let me check")", on the argument that "`context_update` is silent — GetSun absorbs it without speaking. If nobody asks about the preloaded topic, no harm done" ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md), [collaborative-mode.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/collaborative-mode.md)).

There is no pre-warmed connection or speculative model call anywhere in the repository. The cold start is documented as a cost to be endured rather than hidden: 30-90 seconds to join, with the agent told to wait patiently ([SKILL.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/SKILL.md)).
The only recovery-oriented timing is WebSocket reconnection with backoff delays of 1, 5, 10 and 30 seconds after checking that the call is still active, and a `call.state` snapshot plus `events.replay` for crash recovery ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py), [crash-recovery.md](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/references/guides/crash-recovery.md)).

## What this means for TalkToMe

The comparison is sharper than expected, because TalkToMe and AgentCall make opposite bets about where the thinking happens.

AgentCall bets on a fast hosted voice layer in front of a slow agent. GetSun answers in under a second from context while the agent fetches data, and the agent's real answer follows as a second utterance. The architecture admits the agent is slow and inserts a component that is fast enough to cover it.
TalkToMe bets on the agent itself, reached through a terminal-held Codex session, with the app delivering speech through `codex queue` and reading the answer out of the thread's rollout file ([AGENT_API.md](../../AGENT_API.md)).
There is nothing in that path that can speak before the model has spoken, and no second voice layer to hide the wait.

That difference has four consequences worth acting on.

First, TalkToMe's biggest win is not a faster pipeline, it is an honest filler. AgentCall's holding line is not a hack around a slow model; it is the product decision that a heard acknowledgement beats silence. TalkToMe already queues sentences from a streaming reply, and `SentenceBuffer` in [managed.py](../../../src/talktome/managed.py) already cuts at clause boundaries for the first chunk. Sending a short acknowledgement as its own turn, before the work starts, would cover the pre-first-token gap that nothing else in the design can cover. The 35-second and 8 MB limits on `/v1/stt/transcribe` and the 1,000-character synthesis bound are the kind of constraints that make this a scheduling problem rather than a new subsystem ([AGENT_API.md](../../AGENT_API.md), MANAGED_AGENTS.md (since removed)).

Second, the turn-taking model is worth copying almost as-is, because it is pure state machine and a timing constant, with nothing to buy. TalkToMe currently ends a recording after a fixed silence timeout, which is the weak version of the problem: a slow speaker with a mid-sentence pause gets cut off. AgentCall's `VADBuffer` restarts its cooldown on every new final and cancels it on every new partial, which is a small amount of code that fixes exactly that failure ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)). The shipped cooldown of 1.25 seconds is a reasonable starting constant, and the documented tuning range of 1.0 to 3.5 seconds is a reasonable range to expose to the user ([coding-companion README](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/examples/coding-companion/README.md)).

Third, the sentence splitter is one place where TalkToMe is already ahead, and that should be protected rather than replaced. AgentCall splits on `(?<=[.!?])\s+|\n+` and documents the consequences: it over-splits abbreviations and decimals, and the recommended workaround is for the agent to send one sentence per call ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js), [bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)). TalkToMe's `SentenceBuffer` prefers a sentence end, falls back to a clause boundary only for the first chunk, and will additionally cut at a word boundary once a streaming reply passes a unit length, all while stripping code fences and Markdown ([managed.py](../../../src/talktome/managed.py)). That is a better splitter for a streaming source, and the change worth borrowing is not the splitter but the idea of dispatching each sentence as an independent synthesis request with an aggregate completion event, which is what keeps first-audio latency flat as the reply grows.

Fourth, the two pieces of interruption state are the highest-value borrow, and TalkToMe currently has neither. `PRODUCT.md` states plainly that "The microphone pauses during reply playback. Automatic voice interruption is not implemented" ([PRODUCT.md](../PRODUCT.md)). AgentCall's version decomposes into four separable behaviours: suspend playback on the first partial so the pause is immediate and visible, wait for a word threshold within a time window before committing, keep a chunk gate closed until the next utterance starts so stale audio cannot resume, and report which sentences were heard in full versus cut so the agent can decide whether to resume or re-answer ([agentcall-audio.js](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/ui-templates/agentcall-audio.js)). Each of those is independently useful, and the fourth is what makes resumption a real choice rather than a guess.

Where TalkToMe should not follow is the shape of the system. AgentCall's latency figures are targets from a vendor's documentation, not measurements, and the parts that produce them are the parts that are not in the repository: the recogniser, the synthesiser, and the voice-intelligence service. Its `transport` section is a hosted browser bot, which TalkToMe does not want and does not need. The reusable material is the client-side state: the cooldown that restarts, the gate that is event-driven, the cursor that schedules chunks gaplessly, the chunk gate that closes after a clear, and the sentence-level dispatch that keeps first audio independent of answer length. All of that is in the repository, is small, and can be read without a call ever being placed.

## Things this note could not verify

The following were searched for and not found in any repository file, so they are recorded as unknown rather than inferred.

- The speech-to-text provider and model. No recogniser is named anywhere in the tree.
- Whether recognition is streaming or batch as an implementation property. Only the event interface is documented, and it offers both.
- How the ~600 ms end-of-utterance silence is configured, or whether it can be changed ([bridge.py](https://raw.githubusercontent.com/pattern-ai-labs/agentcall/main/scripts/python/bridge.py)).
- Any measured end-to-end latency figure. Every number found is a stated target, a tuning default, or a value inside a fictional example.
- Whether FirstCall uses WebRTC, a media SDK, or a browser capture path internally. The docs describe only the browser and the injection API.
- The internal timing constants of GetSun: the barge-in silence threshold, the interruption decision threshold, and the response latency, all of which are properties of the hosted service rather than documented values.

One open issue is relevant context for anyone considering the hosted path. Issue #3 requests ElevenLabs and other realtime voice providers, and the maintainer replied on July 19, 2026 that "We are currently testing the realtime expressive voice along with a bit more integrations that just the ability to talk. Expecting to release in a week or two." The issue remains open with that single comment ([issue #3](https://github.com/pattern-ai-labs/agentcall/issues/3)). That is a statement of intent, not a shipped capability, and no repository file examined on this date documents a realtime provider integration.
