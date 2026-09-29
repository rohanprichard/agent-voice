# ElevenLabs latency options

This note describes the source before the September 28 implementation.
[Call latency](../../LATENCY.md) records the current behavior.

## Scope

This note reads `src/talktome/static/realtime-input.js` and
`src/talktome/streaming.py`. It uses ElevenLabs documentation only for provider facts.

## Current behavior

### Speech input

`RealtimeInput` gets one Scribe token and opens one Scribe Realtime WebSocket when the microphone starts.

It sends 160 ms PCM chunks while the user speaks. The client uses `commit_strategy=manual`.

At a speech-turn end, `commit()` sends the remaining audio with `commit: true`. It waits up to 2.5 seconds for `committed_transcript`.

The client does not close the socket after a successful commit. It can use the same socket for later turns while the microphone stays open.

### Speech output

`ElevenLabsStream.start()` opens a standard TTS `stream-input` WebSocket for one speech message. It uses `eleven_flash_v2_5` and a 50-character first chunk schedule.

`finish()` sends an empty `text` value. The provider treats this value as the end of the sequence and closes the socket. The next speech message opens a new socket.

## Confirmed provider features

### Scribe Realtime manual commit

Scribe Realtime sends partial transcripts during input. A chunk with `commit: true` gives a committed transcript. Manual commit is the default strategy. [Realtime API reference](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime)

Manual commit clears the accumulated segment and keeps its context. ElevenLabs recommends a commit every 20 to 30 seconds. The model starts transcript processing after the first two seconds of audio. Many commits in a short time can reduce model quality. [Transcript commit strategies](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies)

### Persistent Scribe input socket

Scribe Realtime accepts streaming audio and gives partial and committed transcripts through one WebSocket. The model guide states about 150 ms latency for partial transcripts. This figure excludes application and network delay. [ElevenLabs models](https://elevenlabs.io/docs/overview/models)

The code already uses a persistent Scribe socket during a microphone session. This option needs measurement and hardening, not a new provider design.

### TTS multi-context socket

The multi-context TTS endpoint is `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/multi-stream-input`. Each `context_id` has its own audio stream on one WebSocket. A connection can hold five contexts. [Multi-context TTS API reference](https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-multi-stream-input)

ElevenLabs recommends one WebSocket per end-user session. Its guide says this reduces connection overhead and latency. Send a new context for each reply. Use `flush: true` to generate buffered audio. Use `close_context: true` after the reply. [Multi-context TTS guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/multi-context-web-socket)

Contexts close after 20 seconds without input. Set `inactivity_timeout` up to 180 seconds. An empty text message resets the context timer. [Multi-context TTS guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/multi-context-web-socket)

### Standard TTS socket reuse

The standard TTS socket closes when the client sends an empty `text` value. A space keeps it open. The standard endpoint also accepts `inactivity_timeout` up to 180 seconds. [Keep a TTS WebSocket open](https://elevenlabs.io/docs/help-center/technical/how-can-i-keep-the-websocket-open)

The standard TTS guide describes an empty `text` value as the end of a text sequence. The current `finish()` uses this value. [Realtime TTS guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tts)

## Options and unmeasured gains

| Option | Required code change | Confirmed provider effect | Unmeasured gain |
| --- | --- | --- | --- |
| Keep the Scribe socket open during a call | Keep the present design. Add a reconnect rule if the provider closes an idle socket. | One socket can send audio and return partial and committed transcripts. | No handshake or token request at later turns. Measure turn-end to committed-transcript time. |
| Use Scribe commits only at a speech-turn end | Keep `commit_strategy=manual`. Do not commit partial text. | Manual commit finalizes a segment and keeps context. Frequent commits can reduce quality. | A commit at the local turn boundary can avoid a provider VAD wait. Measure transcript delay and errors. |
| Use one multi-context TTS socket for a call | Replace `ElevenLabsStream` with a call socket manager. Route audio and final frames by `context_id`. | One connection holds separate reply contexts. The provider says it reduces overhead and latency. | Remove a TTS handshake from each speech message. Measure first-audio time for the first and later messages. |
| Keep a standard TTS socket open | Do not send the empty end-of-sequence message. Send a space before the idle timeout. | A space keeps the standard socket open. | This can remove later handshakes. The documentation does not define a reply-completion protocol for this design. Test before use. |

## Measurement plan

During normal calls, record these marks: speech end, commit sent, committed transcript, first agent text, first TTS text sent, and first audio received.

Compare medians and p95 values. Split the first turn from later turns. Do not claim a latency value before this test.
