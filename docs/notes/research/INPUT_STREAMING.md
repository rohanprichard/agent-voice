# Input audio streaming

## Decision

Use live speech recognition for calls that use ElevenLabs. Keep the current batch path for local Whisper calls. Send only a committed transcript to the agent.

This design can overlap recognition with speech. It can show partial text before a spoken turn ends. It does not remove a delay after the call transcript shows the final text. That delay is in the Codex delivery path.

The existing `hearing.Ear` prototype reruns Whisper over the audio it received. A prior local measurement found 1.41 seconds per `base.en` run. That cost exceeds a 0.8-second update interval on this machine. Keep this prototype out of the first live input change. [Work log](../WORK_LOG.md), ear (since removed).

## Current path

The hidden renderer captures microphone samples in `static/audio-worklet.js`. `static/audio.js` keeps the samples in memory. The pause modes are 0.7, 0.9, and 1.8 seconds. The default is 0.9 seconds. The renderer pauses the microphone after the pause ends.

With Whisper, `app.py` reads the full request before `Speech.transcribe` starts. ElevenLabs sends audio to Scribe Realtime while the user speaks. If that path fails, the app sends the saved WAV file to the batch `scribe_v2` endpoint. After recognition, the server adds `user.utterance` to the room. The adapter runs `codex queue` and waits for the terminal's rollout file to show that Codex accepted the message. The call transcript can show the text before the terminal shows it. [Audio capture](../../../src/talktome/static/audio.js), [renderer](../../../src/talktome/static/app.js), [server](../../../src/talktome/app.py), [recognition](../../../src/talktome/speech.py), [Codex adapter](../../../src/talktome/attach.py).

The room keeps `room_message_ms`, `queue_start_ms`, `queued_ms`, and `accepted_ms` while a call is active. These marks show when the app adds the message, starts the queue command, and finds the user message in the rollout. The call transcript no longer shows these marks. The reported 1.5-second gap is a user observation, not a measured stage in the repository. [Room](../../../src/talktome/room.py), [adapter](../../../src/talktome/attach.py), [managed session](../../../src/talktome/managed.py).

## Provider facts

ElevenLabs Scribe v2 Realtime accepts audio chunks through a WebSocket. It sends `partial_transcript` during speech and `committed_transcript` after a commit. Later partial text can replace earlier partial text. The committed text is stable. Its model ID is `scribe_v2_realtime`. This is a different endpoint and model from the app's batch `scribe_v2` path. [Realtime API](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime), [event reference](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/event-reference).

The provider accepts manual commits and voice activity detection (VAD) commits. With manual commits, TalkToMe can keep control of the turn boundary. The provider says that processing starts after the first two seconds of audio. It also warns that many commits in a short time can reduce model quality. Thus, live input does not guarantee a faster result for a short question. [Commit guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies).

The provider supports mono 16-bit PCM at several sample rates, including 16, 44.1, and 48 kHz. It recommends 16 kHz and chunks from 0.1 to 1 second. A browser client needs a single-use token from the server. A server connection can use the API key. The token expires after 15 minutes. [Commit guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies), [client guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/client-side-streaming), [token API](https://elevenlabs.io/docs/api-reference/tokens/create).

## Implemented path

1. Keep the current `AudioWorklet` and microphone controls. Do not start a second microphone capture.
2. The local server gets a single-use Scribe token. The browser uses that token for a direct provider WebSocket. The API key stays in Python. The server checks the call ID before it gives a token. [Client guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/client-side-streaming), [token API](https://elevenlabs.io/docs/api-reference/tokens/create).
3. Collect the worklet's 2048-sample frames into 0.16-second PCM chunks. Use the microphone's sample rate when Scribe supports it. Use the batch path for other rates.
4. Send the existing pre-roll at speech onset. Send later audio chunks as speech arrives. Show each partial as temporary text in the call transcript. Do not add partial text to `room.messages`.
5. Use the current end-of-turn decision to send one manual commit. Wait for `committed_transcript`, then call `room.utterance` once. Send that one message to Codex.
6. Close the socket on call end. Ignore late partials from an old call. If the provider fails or takes too long, use the saved audio with the batch path.

Manual commit keeps recognition and turn detection separate. It also prevents a partial revision from becoming a second Codex message. The provider's example VAD values are for transcript commits. They do not establish a safe turn boundary for this user. [Commit guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies), [voice turn research](VOICE_TURN_TAKING.md).

## The delay after the call transcript

TalkToMe marks `room_message_ms` when it adds the user message. It marks `queue_start_ms` before `codex queue`, `queued_ms` at command return, and `accepted_ms` at rollout pickup. The room keeps these marks during the call. See [Codex terminal delivery](CODEX_TUI_DELIVERY.md) for the next measurement.

If `queue_start_ms` to `queued_ms` is large, examine process startup and the command. If `queued_ms` to `accepted_ms` is large, examine Codex queue dispatch. If both are small, examine the terminal display. The current call gives no basis to assign the reported 1.5 seconds to one part. [Codex adapter](../../../src/talktome/attach.py), [terminal delivery](CODEX_TUI_DELIVERY.md).

Compare the existing batch path with Scribe Realtime on the same real calls. Record speech end, commit, committed text, queue start, queue return, rollout pickup, and first audio. Also record false turn cuts and transcription changes. A partial transcript can improve the display while the user speaks. Only a shorter time to committed text can move the Codex queue earlier.
