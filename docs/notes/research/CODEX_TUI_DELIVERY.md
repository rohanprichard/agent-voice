# Delay from the call transcript to the Codex terminal

## What the app does

The server adds the final user text to the room before it starts the Codex task.
The call window reads the room every 600 ms. Thus, visible text does not show when Codex accepted the message.
[Room](../../../src/talktome/room.py), [task start](../../../src/talktome/managed.py), [call window](../../../src/talktome/static/call.js).

The attached adapter starts `codex queue` in a new process for each user message.
It then reads the Codex rollout every 100 ms for the user message.
The app records `room_message_ms`, `queue_start_ms`, `queued_ms`, and `accepted_ms` while the call is active.
[Adapter](../../../src/talktome/attach.py), [timing marks](../../../src/talktome/managed.py).

The installed `codex queue` command uses `thread/queue/add` in the Codex app server.
Its success means that Codex put the message in its queue. It does not measure the terminal display.
The command does not send a request to resume an unloaded thread.
[Codex queue source](https://github.com/openai/codex/blob/main/codex-rs/tui/src/session_queue_commands.rs).

## What the call shows

The Sep 25 call showed a delay between the final call transcript and the Codex terminal.
The app cleared its timing marks when that call ended. Thus, this call cannot show which stage took that time.
The Codex rollout records when a turn starts and when the user message enters that turn.
It does not record when the call transcript appeared or when the terminal painted the message.
[Room end](../../../src/talktome/room.py), [rollout reader](../../../src/talktome/attach.py).

An earlier local measurement put `codex queue` launch and delivery at 0.09–0.31 s.
That measurement does not explain a 1.5 s gap by itself.
[Work log](../WORK_LOG.md).

## How to cut the delay

1. Keep the timing marks outside the call transcript. Record them for a real call before a transport change.
2. If `room_message_ms` to `queue_start_ms` is long, examine the app task and its prior-turn cancellation.
3. If `queue_start_ms` to `queued_ms` is long, keep one app-server connection and send `thread/queue/add` directly.
4. If `queued_ms` to `accepted_ms` is long, examine Codex queue dispatch and the active terminal turn.
5. If `accepted_ms` is early, measure the terminal display. The rollout cannot measure that display.

A direct app-server connection can remove one command launch per turn. It cannot bypass Codex queue dispatch.
The current 0.09–0.31 s measurement limits the likely gain until a real call shows a larger command cost.
The app must also manage connection loss and Codex protocol changes.
[Current command](../../../src/talktome/attach.py), [Codex queue source](https://github.com/openai/codex/blob/main/codex-rs/tui/src/session_queue_commands.rs).

Do not send partial speech text to the queue. Scribe can change that text before it commits the turn.
TalkToMe has no path to replace a message after it sends that message to Codex.
[Input design](INPUT_STREAMING.md), [attached adapter](../../../src/talktome/attach.py).
