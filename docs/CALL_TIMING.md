# Call timing

The app records the time from the end of speech to the first audio from the agent, for each voice turn. The call surface does not show these times. The app keeps them in `timings.json` in the data folder. `GET /v1/call/timings` returns them, and `call_id` selects one call.

| Name | Start | End |
| --- | --- | --- |
| Pause | Last microphone buffer with speech | The microphone sends the recording |
| Upload + transcribe | The microphone sends the recording | The server gets the text |
| Codex queue | The server gets the text | `codex queue` accepts the text |
| Agent | `codex queue` accepts the text | The first agent message appears |
| Voice | The first agent message appears | The audio level rises in Web Audio |

The microphone and server use the same computer clock. The player checks the Web Audio level every 10 ms. The first level above 0.04 marks audio.

The microphone uses the selected pause before it sends speech. Quick waits 0.7 s. Balanced waits 0.9 s. Patient waits 1.8 s.

This mark measures the audio graph. It does not measure the speaker or the time for sound to reach the listener.

A stage with no mark is missing from the record. Other agent types do not use `codex queue`.
