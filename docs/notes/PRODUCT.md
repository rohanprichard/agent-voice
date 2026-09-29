# TalkToMe

TalkToMe is a local desktop voice room for an existing agent.
The user speaks into the app. The agent receives text, uses its tools, and sends a reply.
The app converts that reply to speech with the selected voice provider.

The agent keeps its project context and reasoning model. TalkToMe supplies the conversation interface.
Agents can use Model Context Protocol (MCP), HTTP, or a JSON Lines bridge.

## First version

- Electron desktop window
- Local Whisper speech recognition
- Installed system voices
- Downloadable Kokoro voices
- Optional ElevenLabs recognition and voice output
- Key entry with optional system-keychain storage
- One conversation view with separate settings and agent connection
- Model download and progress display
- Microphone and voice selection
- Call start, mute, interruption, and end controls
- Transcript and typed messages
- Centered controls before the first message
- Compact voice controls above an expanding transcript
- One connected agent per room
- Local authentication and bounded event history

The first version supports macOS system speech, Kokoro, and ElevenLabs voice output.
Linux and Windows need desktop tests. Standalone installers are not part of this build.
The microphone pauses during reply playback. Automatic voice interruption is not implemented.

## Longer-term direction

The goal is an agent that can explain the current screen and draw on it, similar to HeyClicky.
Screen capture, interpretation, and drawing will use the same conversation session.
The app will request screen access when the user enables those features.

Jev is a possible optional decision component after the app has structured screen information.
The current build does not use Jev or capture the screen.
