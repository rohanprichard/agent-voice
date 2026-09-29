# Interruption playback and heard text

Research date: September 26, 2026. This note examines the TalkToMe source and primary provider documents. It does not report a live call.

## Decision

Record the reply prefix that the browser schedules before an interruption. Do not use the full agent reply as the heard prefix.

Use a conservative ledger. The ledger commits only contiguous text that the browser can map to completed audio. It leaves uncertain text out.

The browser cannot prove when sound reaches a user's ear. It can prove the AudioContext schedule position. The ledger must report this limit.

## Current behavior

`app.js` pauses the microphone while `speaking` is true. `audio.js` discards a recording when `setPaused(true)` runs. Thus, TalkToMe cannot detect a spoken interruption during playback.

`player.js` schedules each decoded buffer on the AudioContext clock. It records a first-audio time. It does not retain a text-to-audio map or an interruption position.

`streaming.py` receives ElevenLabs audio frames. It drops all response fields except `audio` and `isFinal`. It does not request `sync_alignment`.

`room.py` clears `turn_id` in `interrupt` before it emits `agent.interrupted`. The event has no reply identifier, playback epoch, or heard prefix.

`managed.py` cancels a managed task and aborts its active ElevenLabs stream. An attached terminal session can stop speech only. It cannot stop the terminal turn. See [attach.py](../../../src/talktome/attach.py).

## Provider evidence

ElevenLabs text-to-speech (TTS) WebSocket responses can include `alignment`. The response gives `chars`, `char_start_times_ms`, and `char_durations_ms`. The `sync_alignment` query option sends alignment with every response. ElevenLabs says the endpoint supports word-to-audio alignment. [ElevenLabs WebSocket API](https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-stream-input)

The existing ElevenLabs TTS socket can stop generation only by closing the socket. TalkToMe already closes the socket in `ElevenLabsStream.abort`. This stops future audio. It cannot remove audio that the browser already scheduled.

OpenAI Realtime accepts `conversation.item.truncate` with an assistant item and `audio_end_ms`. The server rejects an offset beyond the audio duration. A successful truncation removes unheard assistant transcript from context. [OpenAI Realtime client events](https://platform.openai.com/docs/api-reference/realtime-client-events)

Pipecat sends an interruption through all processors. It cancels work, clears TTS buffers, and drops audio that the output transport did not play. Its assistant context receives only text that synchronized with playback. [Pipecat interruptions](https://docs.pipecat.ai/pipecat/fundamentals/interruptions)

LiveKit starts an adaptive interruption decision after voice activity detection (VAD). Its model separates an intended barge-in from a backchannel. Its default minimum speech duration is `0.5` seconds. It can classify silence without a transcript after `2.0` seconds and resume speech. [LiveKit adaptive interruption handling](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/), [LiveKit turn options](https://docs.livekit.io/reference/agents/turn-handling-options/)

## Heard-prefix ledger

Create one ledger for each reply. Give each ledger a server `reply_id` and a server `playback_epoch`.

Store each playable audio frame as an ordered record.

| Field | Meaning |
| --- | --- |
| `call_id` | The call that owns the frame. |
| `reply_id` | The reply that owns the frame. |
| `playback_epoch` | The server epoch for this playback. |
| `frame_index` | The order inside the reply. |
| `audio_id` | The cached audio identifier. |
| `text_start` and `text_end` | Character limits in the reply text. |
| `alignment` | Character starts and durations for this audio frame. |
| `duration_ms` | Decoded audio duration. |
| `scheduled_start_s` | The AudioContext start time. |
| `scheduled_end_s` | The AudioContext end time. |
| `heard_end_ms` | The last committed audio position. |
| `confidence` | `complete`, `aligned-estimate`, or `unknown`. |

Keep a byte-level copy of each sent TTS text segment. Map the provider alignment characters to that segment before the server emits `agent.audio`.

Do not infer this map from a later full reply string. Text normalization, punctuation, and concurrent reply chunks can change the character positions.

Request ElevenLabs `sync_alignment=true`. Store the response alignment with its audio frame. Check each alignment against the sent segment and decoded duration.

If the provider returns normalized text, map normalized characters to source characters explicitly. If the map fails, mark the frame `unknown`.

The browser records `scheduled_start_s` only after `source.start(start)`. It sends an interruption snapshot before it calls `source.stop()`.

For every frame before the snapshot, apply these rules.

1. If `scheduled_end_s` is at or before the snapshot, commit the whole mapped frame as `complete`.
2. If the snapshot is inside an aligned frame, commit characters whose alignment end is at or before the snapshot offset.
3. Mark the partial-frame prefix `aligned-estimate`.
4. If a frame has no usable alignment, commit only earlier completed frames.
5. Stop at the first unknown or missing text span.

This gives a contiguous prefix. It does not join text after an uncertain frame.

## Exact and estimated playback

`complete` means the Web Audio schedule passed the decoded frame end. `aligned-estimate` means the AudioContext time crossed a provider alignment boundary. Neither value proves acoustic sound at the ear.

The browser and the operating system add output latency after `AudioContext.currentTime`. Browser APIs do not give a reliable per-user acoustic position. Store `presentation_clock: "AudioContext"` with each interruption.

The server must save these values with the interruption.

```json
{
  "type": "agent.interrupted",
  "call_id": "...",
  "reply_id": "...",
  "playback_epoch": 18,
  "heard_text": "The first part of the reply",
  "heard_char_end": 31,
  "heard_audio_ms": 2480,
  "heard_confidence": "aligned-estimate",
  "presentation_clock": "AudioContext"
}
```

Do not replace the displayed full agent message with `heard_text`. Keep the full message for the user. Give the next managed agent turn the heard prefix as the assistant context.

## Voice interruption flow

Use a separate capture path during playback. Do not send its audio to the normal turn path until the interruption gate accepts it.

1. Keep the microphone active while the agent speaks.
2. Keep `0.35` seconds of microphone pre-roll in the interruption buffer.
3. Start an interruption candidate after VAD detects user speech.
4. Continue playback while the candidate is pending.
5. Accept the candidate after `0.5` seconds of speech or an aligned speech-to-text (STT) word.
6. When the candidate is accepted, snapshot the ledger and stop browser playback.
7. Send the snapshot and buffered user audio in one interruption request.
8. Cancel speech generation only after the server accepts the request.
9. Start the normal user turn from the buffered audio.

The `0.5` second value is a first setting. It follows the LiveKit default. It needs recordings from TalkToMe microphones before it becomes a product setting.

If the candidate ends without an STT word, discard it after `2.0` seconds. Playback continues because the browser did not stop it. This is false-interruption recovery without a difficult resume operation.

Use a VAD or a learned acoustic gate for the candidate. Do not stop speech from one RMS buffer. The current source comment records this false-stop defect.

Use echo cancellation, noise suppression, and a microphone device test. Agent audio can reach the microphone through speakers. A user must use headphones when the device cannot separate echo from speech.

## Stale events and order

Use server epochs for state changes. Do not use a browser-only counter as the authority.

The server increments `playback_epoch` when it starts a reply, ends a reply, interrupts a reply, or ends a call. Every `agent.reply` and `agent.audio` event carries `reply_id` and `playback_epoch`.

The browser accepts audio only when `call_id`, `reply_id`, and `playback_epoch` equal the active values. It discards a late fetch, decode, timer, or event from an earlier epoch.

The interruption request includes the same three values and a client event identifier. The server accepts it only once for the active reply and epoch.

If the values are stale, the server returns the current reply state without another cancellation. It does not replace a newer user turn.

Capture the ledger before `Room.interrupt` clears `turn_id`. Make the capture and epoch change one server operation. This prevents a late `agent.audio` event from extending the heard prefix.

## Cancellation capability

Report the capability for each call. A stopped speaker and a cancelled agent are different results.

| Capability | Browser audio | TTS generation | Agent work | Current TalkToMe path |
| --- | --- | --- | --- | --- |
| `managed` | Stop | Abort | Cancel | `ManagedSession.interrupt` cancels the task. |
| `attached` | Stop | Abort | Cannot cancel | The terminal owns the active turn. |
| `realtime` | Stop | Provider action | Provider action | Use truncation when the provider supports it. |

For an OpenAI Realtime reply, send `conversation.item.truncate` with the ledger `heard_audio_ms`. Then cancel the active response. Send no truncation when the ledger has no safe offset.

For an attached call, emit `agent.interrupted` with `agent_cancelled: false`. Queue the new user message only after the user turn ends. The interface must say that the remote turn continues.

## Implementation order

1. Add `reply_id` and server `playback_epoch` to the room events.
2. Preserve TTS text segments and ElevenLabs alignment in `streaming.py`.
3. Add audio-frame text and alignment data to `agent.audio` events.
4. Add the browser ledger to `player.js` and `app.js`.
5. Add the playback capture path and the interruption gate.
6. Add the atomic interruption endpoint with the ledger snapshot.
7. Add managed context truncation and attached-call capability events.
8. Log candidate time, accepted time, heard confidence, false candidates, and cancellation result.

## Limits

ElevenLabs alignment can map generated audio to text. It does not give device speaker latency. Thus, partial-frame text stays an estimate.

The current local speech path has no word timing data. It can commit complete decoded frames only until it supplies alignment.

The present transcript stores the whole agent reply. It does not show where the user stopped the audio. The new ledger must control the next agent context.

## Implementation update: September 27, 2026

The microphone now remains active during assistant speech.
A 350 ms input gate pauses output. An empty transcription resumes output.
Confirmed text clears the old playback epoch and starts a new voice turn.
The player sends audio IDs and playback times before it clears output.
The server maps these times to complete chunks or aligned character estimates.
It adds a conservative playback report to the next agent input.
It does not remove generated text from host history.
No live call checked this behavior yet.
