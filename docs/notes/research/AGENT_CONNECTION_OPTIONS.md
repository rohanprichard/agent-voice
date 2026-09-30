# Agent connection options

Research date: September 24, 2026.

Implementation update: The user later approved both adapters.
See managed agent sessions (since removed) for the implementation and test results.
The findings below describe the source at the time of the research.

## Decision and scope

The project needs both managed sessions and connections to existing terminal sessions.
TalkToMe-managed sessions come first.
The specific adapter remains a proposal, not an approved implementation.

This review used the [test transcript](../test_run/transcript_codex.md), current source, local Codex protocol types, and official documentation.
No live agent conversation or paid model call ran during this review.
The research subagent reached its usage limit. The main agent completed the source review.

## What the test shows

The transcript contains four user messages, ten `talktome_listen` calls, and four `talktome_speak` calls.
Two listen results contain empty timeouts. Three listen results repeat the agent's own reply.
Connect and disconnect bring the total to sixteen MCP calls, separate from two shell commands.
Here, MCP means Model Context Protocol.

The repository question shows the missing progress clearly.
Codex writes a public message: “I will review the repository files and give you a short explanation.”
That message never enters `talktome_speak`, so TalkToMe cannot speak it.
The user-message event and the final reply event are 27.689 seconds apart.
This interval is not a measurement of the first audible output.
The transcript cannot separate model time from speech synthesis time.

The reply text appears in the speak arguments, the speak result, and the next listen result.
These copies add unnecessary context.
Reading the README also adds context, but that read serves the user's task.
The transcript contains no token accounting, so it cannot establish exact costs or savings.

Waiting in ordinary program code does not consume model tokens.
Returning empty tool results asks the model to process another result and decide to wait again.
The proposed controller removes that decision from the model.
Persistent sessions still contain conversation history. They do not make previous context free.

## Current source limits

| Location | Finding | Required change for streamed speech |
| --- | --- | --- |
| MCP server (since removed) | Receives explicit tool calls, not the host's public output | Add a host adapter that receives output events |
| [Listen endpoint](../../../src/talktome/app.py) | Returns the agent's own reply events | Filter input events separately from output events |
| [Reply endpoint](../../../src/talktome/app.py) | Synthesizes the complete text before it emits the reply | Send text before speech completes |
| [Room](../../../src/talktome/room.py) | Allows only one reply per user turn | Permit progress and final messages within one turn |
| [Audio playback](../../../src/talktome/static/app.js) | Each new audio item stops the previous item | Add an ordered audio queue |

A prompt change alone cannot solve these limits.
A progress call to `talktome_speak` would mark the turn as answered and prevent the final reply.
The current microphone pauses during playback. Automatic interruption by speech needs separate work.

The test also ends with `talktome_disconnect` after the user asks to hang up.
`Room.disconnect()` releases the agent but does not call `Room.end()`.
The transcript does not establish the microphone state afterward.
The replacement must distinguish agent disconnection, speech cancellation, work cancellation, and call end.

## Viable options

| Option | Value | Limit | Recommendation |
| --- | --- | --- | --- |
| Native host adapter | Receives public output and controls turns without listen tools | Requires an adapter for each host | First experiment |
| Command-line event stream | Small prototype with structured output | Control and output detail depend on the host | Alternative prototype |
| Smaller MCP results | Removes echoes and unnecessary status fields | Does not capture ordinary host messages | Compatibility improvement |
| Existing-session channel or hook | Keeps the user's terminal session | Host-specific access and output capture | Second connection mode |
| Separate voice model | Could shorten long updates for speech | Adds cost, delay, and possible changes in meaning | Defer until needed |

### Codex first

Codex App Server supports persistent threads, turn control, output deltas, tool events, and approval requests.
Its message items can identify `commentary` and `final_answer` phases.
The client must handle missing phase information.
These features make it the recommended first managed adapter. This is an architectural recommendation, not a completed test.
See the [official App Server documentation](https://developers.openai.com/codex/app-server).

The local installation reports `codex-cli 0.156.1`.
Its generated protocol types include `turn/start`, `turn/steer`, `turn/interrupt`, and `thread/resume`.
`AgentMessageDeltaNotification` includes thread, turn, item, and text fields, but no phase field.
The adapter must associate each delta with its message item.
The local command labels App Server experimental, so the adapter needs version tests.

`codex exec --json` offers structured events and session resume for a smaller experiment.
Do not treat JSON event output as a guarantee of token-by-token text output.
See [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive).

Resuming saved history is not the same as attaching to a running terminal process.
Do not let two clients write to one thread until ownership behavior passes a specific test.
Preserve the user's chosen model, tools, working folder, authentication, and approval policy.

### Claude and existing terminals

Claude Code supports streamed command-line output with partial messages and session resume.
See [Claude Code headless use](https://code.claude.com/docs/en/headless).
Its Agent SDK exposes text deltas and completed messages.
The adapter must avoid speaking the same text from both event forms.
See [SDK streamed output](https://platform.claude.com/docs/en/agent-sdk/streaming-output).

Claude Channels can push messages into an enabled Claude Code session.
The channel requires host support and explicit setup. Output still uses a reply tool.
It does not automatically mirror all public commentary.
This makes it a candidate for terminal attachment, not a universal replacement.
See the [Channels reference](https://code.claude.com/docs/en/channels-reference).

Standard MCP progress notifications describe progress for a request.
They do not define a subscription to all host messages or guarantee that a model starts a new turn.
See the [MCP progress specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress).

## Proposed connection boundary

```text
Microphone or typed message
  -> TalkToMe session controller
  -> Host adapter -> Agent and its existing tools
  <- Public text, tool status, approval requests, turn state
  -> Transcript and speech queue
```

The controller waits in ordinary code. It sends a user message only when input arrives.
The adapter maps host events into a small shared interface.
No second reasoning model is necessary for this path.
MCP remains available for tools and existing integrations.

Proposed events include `message.delta`, `message.done`, `tool.status`, `approval.required`, `turn.done`, and `error`.
Each message has a session identifier, turn identifier, and item identifier.
Speech chunks also need sequence numbers and a cancellation generation.
Progress messages do not end the turn.
Each adapter declares support for progress, resume, interruption, approvals, and terminal attachment.
Unavailable features must remain visible as unavailable.

The desktop client handles the local microphone, playback, and screen permissions.

## What the app should speak

The missing sentence in the test is public commentary, not private reasoning.
Capture public commentary directly instead of asking the model to repeat it through a speech tool.
Do not depend on private reasoning access.

| Output | Transcript | Speech |
| --- | --- | --- |
| Public progress | Show immediately | Speak complete sentences when enabled |
| Final answer | Show as text arrives | Speak each sentence once |
| Tool event | Show a short factual status | Optional short status, not raw logs |
| Exposed reasoning summary | Optional separate view | Off by default |
| Private reasoning | Not required | Not required |

The speech buffer must handle sentence boundaries, Markdown, repeated events, and cancellation.
Old progress must not delay the final answer indefinitely.
Stopping speech must not silently stop agent work.
Ending a call must stop capture and playback and explicitly resolve pending agent work.

ElevenLabs supports streamed audio for supplied text and a WebSocket path that accepts partial text.
Partial text still involves buffering and does not guarantee lower delay.
See [audio streaming](https://elevenlabs.io/docs/api-reference/text-to-speech/stream) and [partial text input](https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-stream-input).
The first experiment can instead use complete sentences with the existing local voice path.
This does not imply that the current Kokoro implementation streams inference.

## Proposed first experiment

Use the existing interface. Defer the floating pill until the agent connection passes these tests.

1. Start one managed Codex thread through App Server.
2. Send the repository question from the saved test.
3. Show public progress before the final answer.
4. Speak public progress once through the existing voice provider.
5. Keep the session idle for five minutes without model-driven listen calls.
6. Exchange ten messages in the same thread.
7. Test interruption during tool work and speech playback.
8. Test approval requests without bypassing the host's approval policy.
9. Test reconnection without repeated speech or concurrent thread writers.
10. Compare measured usage and delays with the existing MCP path.

Record input acceptance, first public text, first audible output, final completion, and provider failures separately.
Use host token accounting where available. Record model, context, and cache differences before comparing results.
Use a smaller model for bounded tests, as the user requested.
Do not claim savings, reliable cancellation, or terminal attachment before these tests pass.

This review changes documentation only. Adapter implementation remains the next proposed step.
