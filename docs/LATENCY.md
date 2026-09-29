# Call latency

## Source changes: September 28, 2026

The app now overlaps transcript completion with Smart Turn.
It also separates speech generation from the agent reader and reuses the ElevenLabs output connection.
No call measurements establish the time saved by these changes yet.

## Speech input

The first Smart Turn check starts one early Scribe commit for the utterance.
The microphone continues to record. The client holds later audio while the model checks the pause.
If the model accepts the pause, the client uses the early transcript without a second commit.

If speech resumes, the client releases the held audio to Scribe.
At the next turn boundary, it joins the committed prefix with the final segment.
The agent receives one complete message. It never receives the provisional segment.
Later Smart Turn checks do not start more early commits for that utterance.

The held audio limit is four seconds. An overflow, unexpected commit, or failed connection selects batch transcription.
The batch path uses the full recording, including audio that the early commit covered.
Mute, call changes, and microphone resets discard stale segments.
Fixed-pause mode keeps its existing commit at the end of the recording.

The capture block decreases from 2048 to 512 samples.
At 48 kHz, these blocks cover approximately 42.7 ms and 10.7 ms respectively.
The speech and interruption thresholds remain in seconds. The input packet remains 160 ms.
These source constants do not establish an equal reduction in call latency.

## Speech output

The agent reader now adds text to a separate speech worker.
It can read later messages and tool events while ElevenLabs generates audio.
The worker preserves the order in which messages first appear, including interleaved deltas.
It bounds each turn to 16,000 queued text characters and 64 messages.
The transcript retains text beyond these limits.

The app opens an ElevenLabs multi-context connection when the agent connects.
Each public message uses a separate context on that connection.
The worker flushes the context when the message ends.
It sends the old context close before it starts the next context.
An interruption removes the audio callback immediately and closes the old context in a separate task.

The connection closes when the call disconnects.
After an idle socket closes, the next message can open a new connection.
A connection failure before speech starts selects the existing sentence path.
The app does not replay a partly spoken message after a transport failure.
The transcript remains available when speech fails.

The text buffer now releases whole words at a threshold of 50 characters, reduced from 120.
This change helps adapters that send text deltas.
The provider remains `eleven_flash_v2_5`, with the existing generation schedule.
The 80 ms playback lead remains unchanged because earlier calls lost the start of speech.

ElevenLabs documents separate contexts on one connection and a close operation for interruptions.
The implementation accepts both documented response spellings: `contextId`/`context_id` and `isFinal`/`is_final`.
[Provider reference](https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-multi-stream-input).

## Codex delivery

The persistent queue proxy remains the input path.
On macOS, file notifications wake the rollout reader when Codex writes new records.
The 100 ms poll remains as a fallback for missed notifications or unsupported systems.
This removes a polling wait. It does not change terminal drawing or agent scheduling.

The public protocol has no documented observer method that avoids thread start or resume.
Thus, the attachment still reads completed public messages from the rollout file.
It does not start a second thread writer to get deltas.
[Observer evidence](notes/research/CODEX_OBSERVER.md) records this limit and the source links.

## Timing records

The app keeps the most recent 200 turn records in `timings.json` within its data directory.
The file has permission mode `0600`. A worker thread writes a separate file before replacement.
The records contain identifiers, timing marks, and mode fields. They contain no transcript text or audio.
The transcript window does not show these records.

`GET /v1/call/timings` returns the history. The optional `call_id` query filters it.
The endpoint uses the existing local authentication.
Each record includes `durations_ms` for available pairs of marks.
Missing marks omit the corresponding duration.
Overlapping stages must not be added into a total.

| Marks | Meaning |
| --- | --- |
| `speech_end_ms`, `capture_end_ms` | Last detected speech and recording end |
| `commit_sent_ms`, `committed_ms` | Final required commit and its transcript result |
| `room_message_ms` | The server adds the user message |
| `cancel_start_ms`, `cancel_end_ms` | Cancellation of the previous task |
| `queue_start_ms`, `queued_ms`, `accepted_ms` | Queue request, queue response, and observed host acceptance |
| `first_message_ms` | First public agent text observed by TalkToMe |
| `tts_ready_ms`, `first_tts_text_ms` | Voice context ready and first text write complete |
| `first_audio_received_ms` | First streamed audio reaches the server |
| `first_audio_scheduled_ms` | The browser schedules the first audio buffer |
| `first_audio_ms` | The existing browser clock and audio-level estimate |

If speech resumes after an early commit, the commit marks describe the final segment.
They do not describe the earlier segment.
The first-audible estimate is not a physical microphone measurement of speaker output.
Local sentence speech does not supply all streaming marks.
Late reports can update a retained turn after the call ends.

## Checks and remaining measurements

Static checks cover Python syntax, Ruff rules, JavaScript syntax, and patch whitespace.
No automated tests, app build, or calls ran for this change.

Normal calls must still check pauses inside sentences, resumed speech, interruptions, and final replies after tool work.
Compare the first turn with later turns. Compare uninterrupted replies with interrupted replies.
Measure the saved time before changing the playback lead or enabling speculative agent input.

## Related notes

- [Latency priorities](notes/research/LATENCY_PRIORITIES.md)
- [Provider options](notes/research/LATENCY_PROVIDER_OPTIONS.md)
- [Smart Turn](SMART_TURN.md)
