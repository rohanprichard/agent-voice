# Speech detection and user turns

Date: October 5, 2026.

## Behavior

TalkToMe uses local Silero voice activity detection (VAD) to detect speech.
Smart Turn v3.2 examines a pause to determine whether the thought is complete.
ElevenLabs supplies transcription and speech output. It does not determine when TalkToMe sends the user turn.

The app keeps transcript segments until it accepts the complete thought.
If speech resumes during detection or transcript completion, the app retains the segments in the same turn.
After five seconds of silence, the app requests transcript completion even if the model remains uncertain.
Long speech uses ordered transcript segments.
After 20 seconds of streamed audio, recognized speech permits a segment completion request.
A delayed transcript must wait for all earlier microphone frames to reach VAD before delivery.

During playback, local VAD continues to receive microphone audio with browser echo cancellation.
The app sends silence to the recognizer until it detects a possible interruption.
Then it pauses playback and supplies the retained microphone frames to the recognizer.
A spoken request discards the current reply and queued speech.
No words, or a brief “mm-hmm” or “uh-huh”, permits playback to resume.
Short requests such as “stop” still interrupt.

Stopping playback does not cancel the agent's current tool or terminal task.
The agent receives the new request after the user turn ends, through the existing call path.
The existing **Stop reply** button still stops playback.

## Initial settings

| Setting | Value | Purpose |
| --- | --- | --- |
| Model audio rate | 16 kHz, mono | Match the model input |
| VAD frame | 512 samples, 32 milliseconds | Supply one model frame |
| Speech start probability | 0.5 | Detect possible speech |
| Continued speech probability | 0.35 | Retain quieter speech within a turn |
| Sustained speech | 96 milliseconds | Reject a single noise frame |
| Pause before model inference | 320 milliseconds | Supply a possible ending |
| Completion probability | 0.65 | Prefer more certain endings |
| Maximum silence wait | 5 seconds | Prevent an indefinite wait for completion |
| Maximum model context | 8 seconds | Match Smart Turn's input limit |
| Interruption audio buffer | Up to 256 milliseconds | Retain the first words |
| Empty interruption recovery | 2 seconds of silence | Resume after detection produces no words |
| Transcript timeout | 8 seconds | End speech input after a missing final result |

These values are initial settings, not results from a microphone calibration.
The app examines each pause once. More silence must not replace the model's speech context.
New speech permits a new model inference with the new audio.
The five-second limit controls uncertain endings. It does not include network transcription delay.

## Runtime and data

A local Python process runs the detection models through ONNX Runtime.
The app starts it through `uv`, which the existing setup already requires.
The build downloads both models and includes them in the installer.
The first call installs Python dependencies through `uv`.
Later calls use the cached files.
Python dependencies use [a script lock file](../../desktop/voice/detector.py.lock).
Model URLs identify fixed source revisions. SHA-256 checksums identify the expected model files.

Detection audio stays in memory on the Mac. The detector does not save or upload it.
The app still sends user speech to ElevenLabs.
The app does not send microphone audio to an agent server.
The app stops the detector when the call ends or speech input stops.
A failed preparation shows an error. It does not silently use a different detector.

## Checks

The app tests cover incomplete thoughts, resumed speech, transcript segmentation, stale results, and the silence limit.
They also cover short interruptions, acknowledgment recovery, empty detection, queued speech, and late speech tokens.
The microphone tests examine retained audio frames, mute races, and a stream that arrives after the call ends.
Process tests examine concurrent requests and worker exit.
The existing integration test uses the real `talktome-server`.

The real models also processed eight published English human recordings from the [Smart Turn test dataset](https://huggingface.co/datasets/pipecat-ai/smart-turn-data-v3.2-test).
The test selected the first four human recordings of each endpoint class in the dataset's first 100 rows.
The dataset identifies these recordings as non-synthetic. The test did not use generated speech.

| Dataset row | Expected ending | Completion probability |
| --- | --- | --- |
| 1 | Complete | 0.9634 |
| 10 | Complete | 0.9893 |
| 17 | Complete | 0.9893 |
| 25 | Complete | 0.9865 |
| 3 | Incomplete | 0.0177 |
| 37 | Incomplete | 0.0135 |
| 39 | Incomplete | 0.0072 |
| 41 | Incomplete | 0.0084 |

All eight results agreed with the labels at the initial threshold.
Silero detected speech in all eight recordings.
Warm Smart Turn inference took 44.9–49.9 milliseconds on the test Mac. The first inference took 123.5 milliseconds.
These times measure model inference only. They do not measure the delay before a spoken agent reply.
Eight samples do not establish general accuracy.

The disk image build passed.
The packaged helper passed model checksum tests, complete and incomplete turn requests, and a VAD request.

## Remaining live checks

The tests did not use a live ElevenLabs call or the user's microphone.
Speaker echo, Bluetooth routing, microphone sensitivity, and background speech still need live checks.
The acknowledgment rule covers the stated phrases. It is not a general model of interruption intent.
Long pauses beyond five seconds can end a thought before the user intended.
These limits must remain visible when the initial settings change.

## Sources

- [Silero model and source](https://github.com/snakers4/silero-vad)
- [Smart Turn model, input contract, and inference source](https://github.com/pipecat-ai/smart-turn)
- [ElevenLabs transcript segments and manual commits](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies)
- [Detector process](../../desktop/src/phone/detector.ts)
- [Model runner](../../desktop/voice/detector.py)
- [Speech and transcript controller](../../desktop/src/ui/voice.ts)
