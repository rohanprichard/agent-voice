# Smart Turn

## Behavior

TalkToMe uses Pipecat Smart Turn v3.2 to check whether the user finished speaking.
The model runs locally on the CPU. It uses the existing ONNX Runtime dependency.
The app does not require the Pipecat framework or another microphone permission.

ElevenLabs starts transcript completion while the model checks the first pause.
Later audio stays in a buffer until speech resumes or the turn ends.
Whisper keeps its existing batch transcription path.
The app sends text to the agent only after the recording ends and transcription completes.

| Pause preference | First model check | Fixed-pause fallback |
| --- | --- | --- |
| Quick | 0.3 s | 0.7 s |
| Balanced | 0.45 s | 0.9 s |
| Patient | 0.7 s | 1.8 s |

A complete decision ends the recording. An incomplete decision keeps the recording open.
If speech resumes, the app discards the old result and checks again at the next pause.
A continuous silence of 3 seconds ends the recording even after an incomplete decision.
The existing 28-second recording limit also remains active.
These settings need normal call checks. No measurement establishes their accuracy in TalkToMe yet.

The microphone stays active during model inference. It retains the full recording for batch transcription if live input fails.
Resumed speech releases buffered audio to the live transcription connection.
The client joins transcript segments before it sends text to the agent.
[Call latency](LATENCY.md) describes this early commit path.
Only the last eight seconds go to Smart Turn. The model never receives text or calls an agent.
A request timeout of 650 ms restores the fixed-pause rule for that recording.
Missing models, download failures, and failed requests also use the fixed-pause rule.

## Settings

Smart Turn defaults to on. The app downloads the model in the background at startup.
The download size is 8,679,182 bytes. Later starts use the local file.
Settings shows the download state and offers a retry after a failure.
Select **Fixed pause** to disable Smart Turn. The app saves this setting.
End the call before changing the detector.

The model lives in `models/smart-turn-v3.2` within the app data directory.
The app pins the upstream revision and checks the SHA-256 digest before loading the model.
It does not save microphone recordings for this feature.
The packaged server includes the upstream BSD license in its `licenses` directory.

## Model interface

- Repository: `pipecat-ai/smart-turn-v3`
- Revision: `f766f81d3cfdf7737ac64aad813d91bbfd56bf93`
- File: `smart-turn-v3.2-cpu.onnx`
- SHA-256: `2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f`
- Input: `input_features`, shape `(1, 80, 800)`
- Output: `logits`, shape `(1, 1)`

The server accepts mono 16-bit WAV audio and resamples it to 16 kHz with the existing decoder.
It keeps the last eight seconds and adds zeros at the start if needed.
It normalizes the waveform before it computes the Whisper log-mel features.
The feature extractor uses `padding=0` to produce exactly 800 frames.

**Correction to the earlier research:** the pinned model ends with `Sigmoid`.
Its output is a probability despite the name `logits`. Do not apply sigmoid again.
The decision uses probability greater than `0.5`, as the Pipecat implementation does.
The earlier note inferred the output type from its name. That inference was incorrect.
Do not use the earlier synthetic scores to set the threshold.

The implementation uses the installed faster-whisper feature extractor.
It does not add `transformers`, PyTorch, or a second audio runtime.

## API and diagnostics

`POST /v1/speech/turn-detection` accepts `{"enabled": true}` or `{"enabled": false}`.
State responses include `speech.smart_turn` with the model, status, error, size, and enabled flag.

`POST /v1/call/turn-check?call_id=ID&playback_epoch=EPOCH` accepts a WAV body.
It returns `complete`, `probability`, and `inference_ms` with the call identity.
The endpoint requires authentication, an active call, and a current playback epoch.
It bounds the request size and permits only one inference at a time.
The browser also discards a result after speech resumes, mute, microphone stop, or recording reset.

Room timing stores `turn_reason`, `turn_probability`, and `turn_check_ms` when available.
These fields stay outside the transcript display.
The reason is `smart_turn`, `pause`, `silence_limit`, or `duration_limit`.

## Checks and limits

Static checks cover Python syntax, Ruff rules, JavaScript syntax, and patch whitespace.
No model inference, automated tests, app build, or live calls ran for this change.
The model graph inspection checked the final operation without processing speech.

Normal calls must still check short replies, pauses inside sentences, resumed speech, and background noise.
The published Pipecat recordings can support later accuracy checks without a new training dataset.
Smart Turn decides when speech ends. It does not decide whether an interruption is intentional.

## Sources

- [Pipecat local analyzer](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/audio/turn/smart_turn/local_smart_turn_v3.py)
- [Pipecat feature extraction](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/audio/turn/smart_turn/_whisper_features.py)
- [Pinned model](https://huggingface.co/pipecat-ai/smart-turn-v3/tree/f766f81d3cfdf7737ac64aad813d91bbfd56bf93)
- [Model license](../licenses/pipecat-smart-turn.txt)
