# Latency priorities after Smart Turn

Date: September 27, 2026.

This note describes the source before implementation.
[Call latency](../../LATENCY.md) records the September 28 changes and remaining limits.

## Current path

The app already transcribes audio during speech and keeps the Scribe input socket open.
It also keeps a Codex queue proxy for each call.
Smart Turn checks a balanced pause after 450 ms.
These changes exist in source. No new call measurements establish their effect yet.

The remaining path is:

```text
Speech ends
  -> Smart Turn accepts the pause
  -> Scribe commits the transcript
  -> TalkToMe cancels the previous task and queues the text
  -> Codex accepts the text
  -> A public agent message completes
  -> The voice socket opens and receives text
  -> Audio arrives, loads, and plays
```

[Input](../../../src/talktome/static/realtime-input.js), [microphone](../../../src/talktome/static/audio.js),
[Codex adapter](../../../src/talktome/attach.py), [speech control](../../../src/talktome/managed.py),
[voice connection](../../../src/talktome/streaming.py), [player](../../../src/talktome/static/player.js).

## First changes

### 1. Remove speech generation from the agent reader

`emit(message.done)` waits for `finish_stream()` to drain the voice provider.
The attached adapter awaits this callback before it reads the next rollout record.
A slow speech response can therefore delay later message and tool events.
This delays TalkToMe observation. It does not stop Codex work itself.

Use a bounded speech queue with one ordered worker.
Let the agent reader return after it enqueues clean text.
Keep message order, cancellation epochs, audio alignment, and terminal error reporting.
This change can reduce delay after progress messages and improve interruption response.
It does not remove the first message's generation time.

### 2. Reuse the output connection

The current code opens a new ElevenLabs socket for each public message.
Use one socket per call with a separate context for each message or interrupted reply.
Open the connection when the call connects, before the first reply needs it.
Close old contexts on interruption. Preserve message order before playback.

ElevenLabs documents a multi-context endpoint for this use. It recommends one connection per user session.
The expected benefit is less connection setup per message. No local measurement establishes the saved time.
[Provider guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/multi-context-web-socket).

### 3. Reduce duplicate text buffering

The app's `STREAM_UNIT` is 120 characters. The voice provider's first threshold is 50 characters.
A sentence boundary can release text sooner, but a long streamed sentence can still wait in TalkToMe.
Use a smaller first clause or a bounded first-text timer. Keep word and markup boundaries intact.

This helps adapters that supply deltas. The current Codex attachment supplies completed public messages.
For that attachment, reducing the buffer cannot recover text that the adapter did not receive earlier.
Compare the provider's automatic generation mode with the current schedule after the app buffer changes.
[Provider latency guide](https://elevenlabs.io/docs/api-reference/reducing-latency).

## Input experiment

Start transcript completion at a likely pause while Smart Turn checks the same audio.
Hold the result until Smart Turn accepts the turn.
If speech resumes, retain the committed segment and append the next segment to the same user turn.
Never send a provisional segment to the agent.

This overlaps transcript completion with turn detection.
Starting both at 450 ms only hides their overlapping time. It does not remove the 450 ms pause.
Starting transcript completion earlier could hide more time, but increases premature segmentation.
The client needs segment identifiers, ordered assembly, and one active commit at a time.

ElevenLabs permits multiple committed segments in one session. Frequent commits can reduce transcription quality.
Thus, do not commit every partial transcript. Treat this option as an experiment with a conservative pause trigger.
[Commit behavior](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies).

## Largest conditional gain: public text deltas

The Codex adapter reads only completed `AgentMessage` items from the rollout file.
It cannot start speech from the first clause while that public message is still being generated.

The installed protocol schema includes `AgentMessageDeltaNotification` with thread, turn, item, and delta fields.
That schema alone does not prove that a second client can observe a terminal-owned thread.
Investigate an observer connection that keeps the terminal as the only writer.
Do not use a second resume or turn-start operation to get the events.

If an observer can receive public deltas, send a complete first clause to speech before the message ends.
Filter reasoning and tool output. Deduplicate final message records against prior deltas.
This could save the remaining message-generation time. The gain depends on message length and host access.

## Smaller changes

| Change | Known boundary | Limit |
| --- | --- | --- |
| File notifications with periodic polling as fallback | The adapter polls every 100 ms. | This changes observation delay, not when Codex accepts input. |
| Smaller audio capture blocks | 2048 samples take about 42.7 ms at 48 kHz. | Smaller blocks increase callback work. |
| Earlier playback scheduling | The first audio source has an 80 ms lead. | Reducing the lead can cause underruns or clipped starts. |
| Smaller input packets | The app sends 160 ms packets. | Commit already flushes pending audio, so this is not a fixed 160 ms saving. |
| Short first replies and subagents | The skill already requests this behavior. | Host scheduling still controls when the main agent receives input. |

These numbers describe source constants. They are not measured improvements and must not be added into a claimed total.

## Measure without transcript clutter

Keep a bounded history of per-turn durations after the call ends.
Store timing and mode fields without transcript text or audio.
The room currently retains only the current turn's timing and clears it at call end.

Add marks for commit sent, committed text received, cancellation start and end,
voice connection ready, first speech text sent, first audio received, and first audio scheduled.
Keep the existing queue, rollout, and first-audible marks.
Compare first turns, later turns, interruptions, and turns with tool work separately.

Queue acceptance, rollout observation, terminal drawing, and audible speech are different measurements.
A 1.5-second visible terminal delay does not identify which stage delayed audible output.
A short set of normal calls can find the dominant stage before a larger comparison.

## Suggested order

1. Save timing records outside the transcript.
2. Move speech generation into an ordered worker.
3. Reuse the ElevenLabs output connection.
4. Reduce the first text buffer for adapters with deltas.
5. Investigate Codex public delta observation.
6. Compare early transcript completion with the current Smart Turn sequence.
7. Tune small polling and playback delays after the larger waits are clear.

This pass changes research notes only. No app code, tests, builds, or calls changed.
