# Voice turn timing and interruption

Research date: September 24, 2026. This note uses official documentation, public source code, and the TalkToMe source. It does not report a live call.

## What TalkToMe does now

The microphone starts a recording at root mean square (RMS) level `0.018`. It keeps speech active above `0.012`. It keeps `0.35` seconds of earlier audio. The microphone waits `0.7`, `0.9`, or `1.8` seconds of silence. Balanced (`0.9` seconds) is the default. It rejects speech shorter than `0.22` voiced seconds. These values come from [audio.js](../../../src/talktome/static/audio.js).

The app pauses the microphone while it speaks. The **Stop reply** button in the pill stops playback and sends `/call/interrupt`. Speech does not stop playback in this design. An earlier speech-onset interrupt stopped turns after room noise crossed one audio buffer. The [work log](../WORK_LOG.md) records that defect and its removal. The [app code](../../../src/talktome/static/app.js) shows the present path.

The managed call can cancel agent work. An attached terminal call can stop speech, but `codex queue` cannot stop the active terminal turn. The [work log](../WORK_LOG.md) describes this limit. The call interface must show this difference when it adds voice interruption.

## Evidence from other agents

### HeyClicky

HeyClicky says its always-on mode accepts speech during its own reply. Its public change log gives no detection rule or timing value. A later release says playback starts early to protect the first syllable on Bluetooth devices. The same release waits for silence after a reply before it changes the audio route. These are reported product changes, not a public implementation. [HeyClicky change log](https://www.heyclicky.com/changelog). The [source review](HEYCLICKY_REUSE.md) explains the public source limit.

### ElevenLabs

ElevenLabs gives its agents separate settings for turn eagerness and interruptions. It offers eager, normal, and patient turn modes. It recommends patient turns when a user needs time to form an answer. Its separate silence timeout starts a prompt after **1 to 30 seconds** of user silence. That timeout is not the short pause that ends each spoken phrase. [ElevenLabs conversation flow](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow).

ElevenLabs also lets an agent ignore selected interruption terms. Its agent API shows `interruption_ignore_terms`, `turn_eagerness`, and `turn_model` as separate fields. These fields do not disclose its private detection rules. [ElevenLabs agent API](https://elevenlabs.io/docs/api-reference/agents/update).

The ElevenLabs live transcript tool uses a separate voice activity detection (VAD) commit rule. Its example waits `1.5` seconds of silence and sets a VAD threshold of `0.4`. Those values serve **transcript commits**, not the agent's turn model. Copying them into TalkToMe's RMS detector has no sound basis. [ElevenLabs transcript guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies).

### LiveKit and Pipecat

LiveKit separates the end-of-turn delay from the interruption gate. Its VAD-only interrupt mode stops speech on detected user speech. Its adaptive mode checks audio to distinguish a real request from a short acknowledgment. The published defaults include `0.5` seconds of speech before interruption and a `2.0` second false-interruption window. LiveKit can resume speech after a false interruption. These are LiveKit settings, not measured TalkToMe settings. [LiveKit turn tuning](https://docs.livekit.io/agents/logic/turns/tuning/), [adaptive interruption guide](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/).

LiveKit also gives its turn detector a minimum and maximum wait. Its detector uses `0.3` and `2.5` seconds by default. The minimum VAD silence is `0.25` seconds. A longer maximum wait lets the detector defer a doubtful end without making every turn slow. [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/).

Pipecat Smart Turn runs after VAD finds silence. It reads up to eight seconds of the current user turn and decides if the user finished. Pipecat says to run it again with the full turn when speech resumes. The model is a possible replacement for a fixed silence rule, but the [work log](../WORK_LOG.md) records a test limit: synthetic speech did not separate complete from incomplete turns. Real conversational samples must come first. [Pipecat Smart Turn source](https://github.com/pipecat-ai/smart-turn).

The existing [AgentCall study](AGENTCALL.md) covers its two-stage transcript timer and interruption gate. Its public bridge uses a `1.25` second buffer after a final transcript. A partial transcript cancels that buffer. AgentCall uses a hosted recognizer, so this value is not a direct RMS setting for TalkToMe. [AgentCall bridge](https://github.com/pattern-ai-labs/agentcall/blob/main/scripts/python/bridge.py).

## Recommended path for TalkToMe

1. Record why each user phrase ends. Keep the RMS levels, voiced length, silence length, and transcript. Mark a user correction after a false cutoff. Use the [Codex delivery marks](CODEX_TUI_DELIVERY.md) for response time.
2. Examine real phrases in quiet rooms, with fans, and with different microphones. Include short answers, long pauses, and speech that fades. Tune the speech-start level and the end wait as separate values.
3. Restore a more patient pause for incomplete phrases before any model change. Keep a short wait for clear endings only after real speech tests support it. An RMS level alone cannot tell a thought pause from a completed turn. [Pipecat Smart Turn source](https://github.com/pipecat-ai/smart-turn).
4. Test Pipecat Smart Turn on real recorded phrases before it controls calls. Compare false cutoffs, late replies, and the end-of-speech to first-audio time against the current rule. Keep a maximum wait and the old rule as a fallback. [Pipecat Smart Turn source](https://github.com/pipecat-ai/smart-turn), [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/).
5. Add a separate capture path during playback for voice interruption. Check for sustained user speech before the app stops audio. Do not use one loud audio buffer as an interrupt. Record false stops and resume speech when no user phrase follows. [LiveKit turn tuning](https://docs.livekit.io/agents/logic/turns/tuning/).
6. For a managed call, stop playback, cancel the agent turn, and start the new turn after a real interrupt. For an attached call, stop playback and queue the new request. Show that the terminal agent continues its current work. [Managed call](../../../src/talktome/managed.py), [attached call limit](../WORK_LOG.md).

## Limits

The user reported early phrase cuts. The longer pause addresses that fault, but no source gives a threshold that works on this user's microphone. The user must try it in a real call. HeyClicky and ElevenLabs do not publish enough code to copy their turn logic. [HeyClicky change log](https://www.heyclicky.com/changelog), [ElevenLabs conversation flow](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow).
