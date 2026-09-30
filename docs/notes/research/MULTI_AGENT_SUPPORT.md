# Multi-agent support

Research date: September 26, 2026.

## Decision

Add an adapter only when its host supplies one controlled session writer, public-output events, and a stop action.

Keep the current Codex attached-session adapter. It sends input with `codex queue` and reads the rollout file.

Do not give the attached adapter a stop control. The terminal owns the Codex thread.

Add OpenClaw support for a session that its Gateway owns. Add Hermes support for TalkToMe-managed sessions.

Keep Claude Code support for TalkToMe-managed sessions. Do not claim that `resume` attaches to a live terminal session.

Use a generic adapter only after its host passes the capability tests in this document.

## Current product boundary

`src/talktome/attach.py` has a Codex-specific attached adapter. It reads a local Codex rollout file and uses `codex queue`.

This adapter has one safe writer. It can stop speech, but it cannot stop agent work.

`src/talktome/host_adapters.py` starts managed Codex and Claude Code sessions. Both adapters send public text and tool status to TalkToMe.

`src/talktome/agents.py` installs the TalkToMe Model Context Protocol (MCP) server for Codex, Claude Code, and DeepSeek Harness.

MCP registration does not attach TalkToMe to a host session. MCP does not require the host to send all public output.

## Capability matrix

| Host | Managed session | Attach to a live terminal session | Public text stream | Stop agent work | Input control | Approval control | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Codex | Yes | Yes, current local adapter | Yes | Managed only | `turn/start` or `codex queue` | Managed only | Keep both modes |
| Claude Code | Yes | Experimental Channel only | Channel reply tool | Channel has no published stop | Channel event | Channel permission relay | Keep managed mode |
| Hermes Agent | Yes, API server | No proven safe method | Yes, Session Server-Sent Events | Probe run capability | Session REST endpoints | Yes, when capability exists | Add managed mode |
| OpenClaw | Yes, Gateway | Yes, Gateway-owned session | Yes, Gateway events or SSE | Yes | `chat.send` queue modes | Gateway scopes | Add Gateway mode |
| DeepSeek Harness | No known host protocol | No known host protocol | No known host protocol | No known host protocol | MCP tools only | Host-defined | Keep MCP registration only |
| Other agent | Host-defined | No, until tested | Host-defined | Host-defined | Host-defined | Host-defined | Use the generic contract |

“Yes” means that the cited host interface has the needed mechanism. It does not mean TalkToMe has the adapter.

## Claude Code

The Claude Agent SDK has a bidirectional `ClaudeSDKClient`. The client sends messages, receives streamed messages, and supports `interrupt()` in streaming mode. [Claude SDK client source](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/client.py)

The SDK emits partial messages when `include_partial_messages=True`. `StreamEvent` contains text deltas. A final `ResultMessage` has a session identifier and usage data. [Claude SDK message types](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py)

The current `ClaudeAdapter` uses this path. It must keep one live SDK client for each TalkToMe session when it needs a reliable stop action.

`resume=<session_id>` loads saved conversation history. It starts an SDK-controlled Claude Code process. It does not prove safe control of a terminal process that already owns that session.

Claude Channels use an MCP server. It sends events to an open Claude Code session. Claude Code can reply only when the channel supports replies. [Claude Channels](https://code.claude.com/docs/en/channels)

Events arrive only while the session stays open. Organizations can limit channel plugins. Claude Code requires Claude.ai authentication or a Console API key.

Channels do not work with Amazon Bedrock, Google Cloud Agent Platform, or Microsoft Foundry. They do not define a general subscription to terminal commentary.

Channels support the live terminal session only when that terminal starts with `--channels`. This gives a valid input path without another writer.

The terminal shows the inbound channel event. It does not show the reply text. The channel reply tool must send that text to TalkToMe.

This path is a research preview. A custom TalkToMe channel needs `--dangerously-load-development-channels` until Anthropic allows the plugin. Do not release it as normal support.

Treat Channels as an optional bridge experiment. Test one terminal owner, output delivery, stop behavior, approval routing, and reconnection before release.

The Claude SDK can route permission requests through `can_use_tool`. Keep `permission_mode="default"` unless the user selects another policy. [Claude SDK query source](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/query.py)

Claude Managed Agents can run an agent session in Anthropic infrastructure. It uses `sessions.create`, `sessions.events.send`, and `sessions.events.stream`. [Managed Agents migration](https://platform.claude.com/docs/en/managed-agents/migration)

Send `user.interrupt` to stop a Managed Agents run. The stop can wait for a tool call. Use completed `agent.message` events as the source of record. [Managed Agents events](https://platform.claude.com/docs/en/managed-agents/events-and-streaming)

## Hermes Agent by Nous Research

Hermes Agent has an API server for external user interfaces. It requires `API_SERVER_KEY` for its session endpoints. [Hermes API server](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md)

Use `POST /api/sessions` to create a managed session. Use `POST /api/sessions/{id}/chat/stream` for a turn.

The stream uses Server-Sent Events. It sends `assistant.delta`, `tool.started`, `tool.completed`, and `run.completed` events.

Read `/v1/capabilities` before the adapter starts. Require `run_submission` and `run_events_sse`.

The Runs API gives a run ID for each turn. Read `GET /v1/runs/{run_id}/events` for deltas, public commentary, tool events, and run state.

Use `POST /v1/runs/{run_id}/stop` only when `run_stop` is true. The API returns `stopping` before the run ends.

Use an `Idempotency-Key` when the adapter creates a run. Hermes keeps the key for 24 hours.

The API also has a run approval endpoint. Show an approval only when `/v1/capabilities` advertises `run_approval`.

The Runs API has a scoped stop endpoint. Do not apply it to a Hermes session that TalkToMe did not start.

The Runs API uses a session turn lease to serialize concurrent writers. It refreshes the transcript after a contended wait.

Do not attach to a Hermes terminal by reading `~/.hermes/state.db`. The database can show history, but it does not supply safe input delivery or live output events.

The Hermes server gives access to terminal commands, files, web search, memory, and skills. Keep `API_SERVER_KEY` on the local computer. [Hermes API server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)

## OpenClaw

OpenClaw Gateway uses a WebSocket protocol for clients. The protocol has roles, scopes, session control, chat control, approvals, and events. [OpenClaw Gateway protocol](https://docs.openclaw.ai/gateway/protocol)

Use the Gateway as the session owner. TalkToMe must use the Gateway protocol for every input and control action on that session.

The OpenClaw Gateway serializes runs for one session key. It records the active writer run ID before it writes a transcript.

`chat.send` supports `steer`, `followup`, `collect`, and `interrupt` queue modes. `steer` sends input to the active run. `interrupt` stops that run and then starts the new input.

Use `sessions.abort` for an explicit stop. Supply a `runId` when it is available, so the stop affects only the selected run. [OpenClaw session control](https://docs.openclaw.ai/gateway/protocol/rpc-session-control)

Use `chat.history` with its `deltaCursor` after a connection loss. Reapply its entries with the same reducer that handles live `session.message` events.

OpenClaw also has an OpenResponses HTTP endpoint. It streams text through Server-Sent Events when `stream: true`. Use `x-openclaw-session-key` to select a session. [OpenClaw OpenResponses API](https://docs.openclaw.ai/gateway/openresponses-http-api)

The HTTP endpoint gives full operator access under shared-secret authentication. Keep the Gateway token local.

Use the Gateway WebSocket adapter for an attached Gateway session. Use the HTTP endpoint only for a TalkToMe-managed compatibility mode.

The adapter uses protocol version 4. It sends `connect`, then calls `sessions.messages.subscribe`, `chat.history`, `chat.send`, and `sessions.abort`.

OpenClaw accepts `gateway-client` as the client ID and `backend` as the client mode. A loopback Gateway can accept token authentication for this client class.

It sends `chat.send` with `queueMode: "followup"` and an idempotency key. It accepts agent events only when `payload.runId` matches its returned run ID.

Assistant events use `stream: "assistant"`. Tool events use `stream: "tool"`. A `stream: "lifecycle"` event ends the TalkToMe turn.

The adapter requires `TALKTOME_OPENCLAW_TOKEN`. It accepts only a loopback Gateway URL.

Treat both native adapters as experimental until a user connects a local host and checks the full call path.

## Local host configuration

Save a host URL and token with `configure_external_provider(provider, url, token)`. It writes `agent-hosts.json` in the TalkToMe data directory.

The file uses mode `0600`. The write uses a new private temporary file and an atomic replace.

Environment variables override the saved values. The status function shows the configured URL and required setup. It does not show a token.

## Generic adapter contract

An adapter must expose these methods.

```text
start() -> session_id, capabilities
send(session_id, text, mode) -> run_id
events(session_id, cursor) -> public text, tool status, approval, run state
stop(session_id, run_id)
approve(session_id, approval_id, decision)
close(session_id)
```

The `capabilities` result must contain `managed`, `attach`, `text_stream`, `stop`, `approval`, `resume`, and `single_writer` values.

An attached adapter must return `single_writer=true`. It must send input through the owner protocol.

Do not treat a saved transcript, a resume option, a pseudo-terminal, or a shell pipe as session attachment.

If `stop=false`, TalkToMe must label the action "Stop speech". It must not label the action "Stop agent".

Give every event a session ID, run ID, item ID, sequence number, and event time. Keep a cursor after every event.

Accept public text only. Do not request or speak private reasoning.

## Host bridge protocol

Use a local MCP channel when a host can accept a channel plugin. The bridge has one input tool and one output tool.

```text
talktome.push(session_id, event_id, text)
talktome.reply(session_id, event_id, text, final)
talktome.status(session_id, event_id, state)
talktome.approval(session_id, approval_id, request)
```

The host calls `talktome.reply` for every public reply. The bridge sends `talktome.push` only through the host channel event path.

The bridge must reject a second active writer for the same `session_id`. It must reject repeated `event_id` values.

The host owns stop and approval actions. TalkToMe requests them only through a bridge action that the host documents.

## Implementation order

1. Add a Gateway adapter for OpenClaw sessions.
2. Add a Session Server-Sent Events adapter for Hermes Agent.
3. Keep the current Claude Code adapter as the managed implementation.
4. Add a Claude Channels experiment behind a feature flag.
5. Add the generic adapter registry after two adapters use the same event contract.

## Release checks

1. Start one long tool task in the host UI.
2. Connect TalkToMe to the same session.
3. Send one message during the task.
4. Make sure the host accepts one writer only.
5. Make sure TalkToMe speaks each public sentence one time.
6. Stop speech during output.
7. Stop the agent when the host advertises a run stop action.
8. Disconnect TalkToMe during output.
9. Reconnect with the event cursor.
10. Make sure the transcript has no lost, repeated, or foreign-session events.
11. Make sure an approval retains the host approval policy.

## Sources

All sources below were read on September 26, 2026.

- [Anthropic Claude Agent SDK client source](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/client.py)
- [Anthropic Claude Agent SDK query source](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/query.py)
- [Anthropic Claude Agent SDK message types](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py)
- [Anthropic Claude Channels](https://code.claude.com/docs/en/channels)
- [Anthropic Managed Agents migration](https://platform.claude.com/docs/en/managed-agents/migration)
- [Anthropic Managed Agents events](https://platform.claude.com/docs/en/managed-agents/events-and-streaming)
- [Nous Research Hermes Agent API server](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/api-server.md)
- [OpenClaw Gateway protocol](https://docs.openclaw.ai/gateway/protocol)
- [OpenClaw Gateway session control](https://docs.openclaw.ai/gateway/protocol/rpc-session-control)
- [OpenClaw OpenResponses API](https://docs.openclaw.ai/gateway/openresponses-http-api)
