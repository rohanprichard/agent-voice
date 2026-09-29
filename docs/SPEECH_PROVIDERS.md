# Speech providers

## Local speech

Whisper uses the existing faster-whisper runtime. The app downloads Small or Base English from Hugging Face.
Kokoro uses the kokoro-onnx runtime and the fixed `model-files-v1.1` assets.
The app checks file size and SHA-256 hashes before it loads each Kokoro file.
The current selector exposes English voices only.

Sources: [Kokoro runtime](https://github.com/thewh1teagle/kokoro-onnx), [model assets](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1).

## ElevenLabs

The app uses these interfaces:

| Function | Request | Model |
| --- | --- | --- |
| Voice list | `GET /v2/voices` | None |
| Voice output | `POST /v1/text-to-speech/{voice_id}` | `eleven_flash_v2_5` |
| Recognition, fallback | `POST /v1/speech-to-text` | `scribe_v2` |
| Live recognition token | `POST /v1/single-use-token/realtime_scribe` | None |
| Live recognition | `wss://api.elevenlabs.io/v1/speech-to-text/realtime` | `scribe_v2_realtime` |
| Streamed voice output | `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/multi-stream-input` | `eleven_flash_v2_5` |

The key travels in the `xi-api-key` header. The app does not put it in a URL.
Voice output uses `mp3_44100_128`. The server converts this audio to WAV for playback.
Live recognition sends microphone audio through the Realtime WebSocket while the user speaks.
The server gets a single-use token for that connection. The API key stays in the Python server.
If the live connection fails, the app sends one WAV recording after each speech segment.
[Call latency](LATENCY.md) describes the live input and output paths.
The providers are separate choices. The default recognition provider remains Whisper.

Sources: [voice list](https://elevenlabs.io/docs/api-reference/voices/search), [voice output](https://elevenlabs.io/docs/api-reference/text-to-speech/convert), [recognition](https://elevenlabs.io/docs/api-reference/speech-to-text/convert).

## Credentials and data

The key stays in server memory unless the user selects Remember key.
With Remember key, the system keychain stores the key through Python keyring.
The app uses the data-directory path to identify its keychain entry.
The settings file contains only the preference to restore the key, not the key itself.
Key validation errors and state responses do not contain the key.

ElevenLabs receives microphone audio only when the user selects ElevenLabs recognition.
ElevenLabs receives reply text only when the user selects ElevenLabs voice output.
The app does not promise zero retention from ElevenLabs. The provider account controls its data rules and charges.

## Tests on September 23, 2026

- Real Kokoro download, hash checks, and speech output on macOS
- Real Whisper recognition from a synthetic microphone inside Electron
- Kokoro voice selection and preview in Settings
- Connected test-agent reply, playback, interruption, and typed message
- Mock ElevenLabs requests for voice output and recognition
- Mock keychain storage and removal
- Secret-free state and validation responses
- Settings changes rejected during a call

The tests did not use a live ElevenLabs key. A live account test remains necessary before release.
The tests did not record the physical microphone. Linux and Windows need desktop tests.
