# Codex observer evidence

## Answer

Do not add a second proxy as an observer. The public protocol has no
`thread/subscribe` method. `thread/start` and `thread/resume` subscribe a
connection. The required no-write method list excludes both methods.

`thread/read` reads stored data. It does not subscribe the connection. Thus, it
cannot receive live `item/agentMessage/delta` events.

Keep the rollout reader. It preserves the terminal as the only thread writer.
Do not use `thread/resume` as an observer operation. The server source attaches
a listener during resume. This changes the loaded-thread subscription state.

## Supported

- The local schema defines `item/agentMessage/delta`. Its fields are `threadId`,
  `turnId`, `itemId`, and `delta`.
- The schema defines `thread/unsubscribe`, but no `thread/subscribe`.
- The official App Server guide says `thread/start` automatically subscribes a
  client. It describes `thread/resume` as a way to reopen a thread. It says to
  read notifications after a turn starts.
- The public server source sends events to all subscribed connection IDs. Its
  listener-attach paths include start, resume, fork, revert, real-time input,
  and internal recovery.
- The public source maps `AgentMessageContentDelta` to
  `item/agentMessage/delta`. It maps completed messages separately to
  `item/completed`.

## Delta use

`item/agentMessage/delta` is a typed agent-message event. It can arrive before
`item/completed`. It does not contain a phase field. The client must wait for
`item/started` to get the phase, or treat the delta as an unclassified agent
message.

This research does not prove that the rollout gives a usable delta before its
completed item. The current TalkToMe reader only accepts completed
`AgentMessage` records.

## Unproven

- A new initialized proxy can subscribe to a terminal-owned live thread without
  `thread/resume`.
- A second proxy can receive that thread's deltas without a write-side lifecycle
  method.
- A rollout delta has a stable public format and a phase that makes it safe for
  speech before completion.

## Sources

- Local generated schema: `/private/tmp/talktome-codex-schema.jAHYnA/v2/AgentMessageDeltaNotification.json`, `ThreadReadParams.json`, and `ThreadUnsubscribeParams.json`.
- [Codex App Server guide](https://developers.openai.com/codex/app-server)
- [Thread lifecycle source](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/thread_lifecycle.rs)
- [Thread processor source](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/thread_processor.rs)
- [Thread state source](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/thread_state.rs)
- [Event mapping source](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/event_mapping.rs)
- [Event delivery source](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/bespoke_event_handling.rs)
