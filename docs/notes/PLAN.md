# Current build plan

The [roadmap](ROADMAP.md) is the current source for product priorities and design decisions.
The project selected the first Canvas concept, with neon accents, blue surfaces, and a floating desktop pill.
Two separate audio wave lines represent the user and agent. Settings opens a larger window.
Implementation waits for the next user discussion about the agent interface, which is the immediate priority.

## Implemented

The app runs as an Electron window with a local Python server.
Whisper Small and Whisper Base English use CPU inference through faster-whisper.
macOS `say` supplies speech output. Linux can use eSpeak.
Kokoro supplies downloadable local voices. ElevenLabs supplies optional recognition and voice services through a user API key.
The current main view has a fixed sidebar, a conversation area, and separate Settings and agent connection views.
The proposed Canvas design removes the permanent sidebar.
First-start setup covers speech providers, microphone permission, and agent connection.
The app saves setup progress. Users can explicitly postpone either step.
System, Light, and Dark themes apply across all views.
Connection copy controls use the native clipboard through a restricted desktop interface.

The agent connection uses Model Context Protocol (MCP), HTTP, or the command bridge.
The agent client sends a heartbeat during tool use. The server rejects replies for canceled turns.
The app keeps conversation data in memory and clears cached reply audio when the call ends.

## Current tests

Server tests cover authentication, event delivery, agent ownership, stale turns, and interruption during speech synthesis.
The desktop test uses a generated microphone sample and the real local speech model.
The MCP test uses the official client to connect, listen, speak, and disconnect.
The onboarding test covers setup progress, permission denial and approval, native copying, themes, and the default window layout.
Permission tests use a fake permission handler. They do not request physical microphone access.

## Next improvements

1. Measure voice latency across supported machines.
2. Add tests for more accents and longer Kokoro replies.
3. Add voice interruption with tested echo cancellation.
4. Package the Python runtime with the desktop installer.
5. Test Linux and implement Windows speech output.
6. Add a compact desktop view.

## Screen features

The screen work has three separate parts:

| Part | Responsibility |
| --- | --- |
| Screen context | Capture a user-selected display or region |
| Screen interpretation | Supply text, element identifiers, and bounds |
| Drawing overlay | Render arrows, circles, and labels without changing the underlying app |

A screen snapshot needs an identifier, capture time, display identifier, and scale factor.
Drawing commands must refer to that snapshot and its coordinate system.
The overlay must clear when the call ends or the user dismisses it.
These fields will prevent old drawings from pointing at a changed screen.

An optional decision adapter can rank known elements or actions.
Jev needs structured text input. It cannot replace the screen interpreter.
See [the research](research/WORLD_MODELS.md) before adding a model dependency.

## References

AgentCall informed the event bridge and interruption design.
Its published bridge keeps the coding agent separate from meeting infrastructure.
See [AgentCall](https://github.com/pattern-ai-labs/agentcall).

SKI informed the local two-way voice flow.
Its public explanation distinguishes binary distribution from open-source code.
See [SKI's explanation](https://heyski.io/blog/what-is-ski-voice-coding-explained).

HeyClicky demonstrates screen annotations and spoken guidance.
See [HeyClicky's change history](https://www.heyclicky.com/changelog).

The historical SpeakType-based plan remains in [archive/PLAN.md](archive/PLAN.md).
