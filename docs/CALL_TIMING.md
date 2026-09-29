# Call timing

The call transcript shows the time from the end of speech to the first audio from the agent. It shows the latest voice turn.

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

The call transcript shows a dash if a stage has no mark. Other agent types do not use `codex queue`.
