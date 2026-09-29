---
name: talktome
description: Start a live voice call through the local TalkToMe app when the user says call me, talk to me, or talk_to_me. Use shell commands.
---

# TalkToMe

TalkToMe adds voice to an agent session. The desktop app handles the microphone, speech, and call controls.
The connection method depends on the host. Do not assume that every host supports automatic terminal input and output.

## Find the call command

TalkToMe uses the host's terminal tool to run `talktome` commands.
The host does not need a tool named `talk_to_me` or a telephone service.
This skill starts a two-way desktop voice call. A generated audio file cannot replace that call.
Run the commands on the Mac that runs TalkToMe.
If the terminal runs on another computer, state that limit before attempting a local call.
If `talktome` is absent from the shell path, examine `~/.local/bin/talktome`.
Use that absolute path for all call commands if the file exists.
If neither command exists, ask the user to install the command from TalkToMe Settings.

## Check the shell before a call

Use the host's shell tool to run every command in this skill.
When you look for the command, run one bounded lookup such as `command -v talktome` and give
the shell tool a short timeout.
If the shell does not start, or the lookup times out with no output, report that shell failure
once and stop.
Do not repeat the call command after a shell startup failure.
This rule keeps a stalled discovery command from becoming repeated call attempts.
It does not fix a Hermes executor that cannot run shell commands.

## Keep the main agent available

During a call, always delegate work to subagents unless the user explicitly requests no subagents.
Keep the main agent available for conversation, clarification, interruptions, and short progress reports.
Delegate research, file reads for a task, implementation, builds, and other extended work.
Do not wait on a worker when the host permits you to receive another user message.
Keep the worker's scope and required result clear. Apply new user instructions to the worker's task.
Review worker results before you report completion. Do not read raw worker output aloud.

The main agent handles voice connection commands and short conversation directly.
If the host has no subagent function, state that limit once. Do not claim that you delegated the work.
Use the available host functions without inventing a subagent command.
If the user requests no subagents, do the work directly until the user changes that instruction.

## Select the connection

Run `talktome providers` to see the available connection methods.

| Host | Method | Spoken output |
| --- | --- | --- |
| Codex | Existing terminal session | Public replies are captured automatically. |
| Claude Code | Cooperative commands in this session | Send each spoken reply with `talktome reply`. |
| Hermes Agent chat or terminal | Cooperative commands in this session | Send each spoken reply with `talktome reply`. |
| Hermes API session | Existing REST API session | The adapter captures public output. This path is experimental. |
| OpenClaw chat with local shell access | Cooperative commands in this session | Send each spoken reply with `talktome reply`. |
| OpenClaw Gateway session | Existing Gateway session key | The adapter captures public output. This path is experimental. |
| Other hosts | Cooperative commands in this session | Send each spoken reply with `talktome reply`. |

Cooperative mode works with any host that can run shell commands. It does not create another model session.
Hermes API and terminal sessions share one database. An API call with a terminal session ID writes to that session. The open terminal does not show those turns until you resume it. Hermes runs one turn at a time for each session, so a voice turn waits while the terminal works.
Use `--connection cooperative` with Hermes or OpenClaw if the current session has no supported gateway connection.

## Start a Codex call

Use the actual session identifier supplied by Codex:

```sh
talktome call --agent codex --thread "$CODEX_THREAD_ID" --greeting "Hey, what would you like to talk about?"
```

The terminal keeps its model, tools, context, and history. Write short public replies as usual.
Do not use `listen` or `reply` for the automatic Codex connection.

## Start a cooperative call

Use the current host session identifier if it is known. Otherwise, create one unique connection identifier and retain it for this call.
Do not invent a host environment variable. A cooperative connection identifier does not need to be a host resume identifier.

```sh
talktome call --agent claude --thread SESSION_ID --greeting "Hey, what would you like to talk about?"
```

For an unlisted host, use `--agent generic`.
For another listed host, add `--connection cooperative`.
Replace `SESSION_ID` with the same identifier in every command below.

After the user answers, repeat this procedure:

1. Run `talktome listen --thread SESSION_ID --after SEQUENCE --timeout 25`.
2. Retain the returned `seq` for the next listen command.
3. Read the current `pending` turn, including its `call_id`, `turn_id`, and text.
4. Delegate the requested work while the main agent handles the conversation.
5. Send a short progress reply with a unique item identifier when needed.
6. Send the final reply when the answer is ready.
7. Listen for the next user turn.

Start with `--after 0`. An empty result means that no new user turn is available.
The `pending` field can repeat after a retry. Do not start the same task twice.
A `turn.cancelled` event means that the voice turn ended. Do not send more replies for that turn.
A later `pending` turn takes priority over an earlier event. Use its identifiers.
If the call closes, stop the listen loop.

Use a text file for replies that contain quotes or shell syntax:

```sh
talktome reply --thread SESSION_ID --call-id CALL_ID --turn-id TURN_ID --item-id progress-1 --text-file /tmp/voice-progress.txt --progress
```

```sh
talktome reply --thread SESSION_ID --call-id CALL_ID --turn-id TURN_ID --item-id final-1 --text-file /tmp/voice-answer.txt
```

A reply without `--progress` ends the voice turn. Use a new item identifier for each progress message.
Reuse the same item identifier and text only to retry that exact reply.
The main agent must keep listening while subagents do extended work.
If a worker finishes after its voice turn ends, retain its result. Use the result when the current conversation needs it.

## Call across the remote bridge

Use the remote bridge only when this server already has a saved bridge configuration.
Check it first with `talktome remote-status`.
Do not run `remote-setup` or `remote-daemon` unless the user asks.
The pairing code is a credential. Read it from standard input; never put it in a command
argument, a log, or a transcript.

The daemon owns the network connection. Every command below writes only a private local
file, so it works when a sandbox blocks loopback connections. The laptop keeps the
microphone, speech, and call controls; no microphone audio crosses the bridge.

```sh
talktome --remote call --agent claude --thread CONNECTION_ID --greeting "Hey, what would you like to discuss?"
talktome --remote listen --thread CONNECTION_ID --after 0 --timeout 25
talktome --remote reply --thread CONNECTION_ID --call-id CALL_ID --turn-id TURN_ID --item-id ITEM_ID --text-file /tmp/voice-reply.txt
talktome --remote end
```

Follow the same listen-and-reply procedure as a local cooperative call.
Reply with the identifiers from the pending turn.
Add `--progress` to a reply that is not the final answer.
Reuse the same `--item-id` only to retry that exact reply.
Pass `--request-id` only to retry the same request; a reused request ID with different
text fails.

The laptop must be online. If it is not, `call` returns an unavailable result and the
ring is not saved for later.
A lost delivery returns an explicit unknown result. Do not resend a mutating command
after that error.
`talktome --remote end` ends only this pair's call and cannot end a local call.
The `talktome relay-*` commands belong on the relay host, not on this server.

## Call from a Hermes chat

Use cooperative mode for a Hermes chat or terminal session.
Use the external adapter only when the user supplies an existing Hermes API session.
Do not assume that the chat session is an API session.

Choose one connection identifier. If the host supplies no session identifier, run `uuidgen` and retain its output.
Replace `CONNECTION_ID` with that value in each command.

```sh
talktome call --agent hermes --connection cooperative --thread CONNECTION_ID --greeting "Hey, what would you like to discuss?"
```

After the user answers, follow the cooperative procedure above.
Run `talktome listen` to receive each user turn. Run `talktome reply` to speak each answer.
Ordinary Hermes chat text does not automatically become speech in this mode.
Keep the main agent in the listen loop while subagents do extended work.

## Call from an OpenClaw chat

Use cooperative mode when this chat has shell access to the Mac that runs TalkToMe.
Use the Gateway adapter only when the user supplies a configured Gateway and its actual session key.
Do not request a Gateway token for a cooperative call.

Choose one connection identifier as described in the Hermes section.

```sh
talktome call --agent openclaw --connection cooperative --thread CONNECTION_ID --greeting "Hey, what would you like to discuss?"
```

After the user answers, follow the cooperative procedure above.
Use `listen` for user turns and `reply` for spoken answers.
Ordinary OpenClaw chat text does not automatically become speech in this mode.
If the shell runs in a remote Gateway or container, it cannot directly control this Mac's local TalkToMe app.

## Start an external session call

Use a configured host and its actual API session identifier:

```sh
talktome call --agent hermes --thread HERMES_API_SESSION_ID --greeting "Hey, what would you like to work on?"
```

```sh
talktome call --agent openclaw --thread GATEWAY_SESSION_KEY --greeting "Hey, what would you like to work on?"
```

Do not configure a token or start a host without the user's instruction.
Read the provider error if the gateway cannot accept the connection. Do not bypass its permissions.

## Read the call result

The call command rings first. It waits for the user to answer.
The greeting plays only after the user answers. Use one short opening question.
The app uses the session name when available. Use `--name` for a call title.
Transcript labels use the agent name, not the call title.

Read `answered` in the result. If it is false, say that the call was not answered once.
Do not call repeatedly. A local ring stops after 30 seconds, or when the user declines it.

The command exchanges private files with the app. It can work when the host sandbox blocks loopback network access.
The host still needs permission to write to the workspace or temporary directory.

## Speak for the ear

Give one short public reply before extended work. Then delegate the work.
Keep spoken replies to one or two sentences unless the user asks for detail.
Do not read code, file paths, tables, or raw tool results aloud.
State what changed or what you found. Keep the full technical detail in the transcript when needed.

## Handle interruptions

A TalkToMe playback report can state how much of the previous reply played.
Do not assume that generated text was heard. The report is conservative and can omit an uncertain partial sentence.
Answer the new request. Do not repeat the full previous reply unless the user asks.
Stopping speech does not always stop host work. Codex terminal and cooperative connections keep the host under its original controller.
Tell a worker about a changed task. Cancel worker work only when the host permits it and the new request requires it.

## End the call

When the user asks to end the call, run:

```sh
talktome end
```

Do not end the call while the user is still speaking.

## Connection errors

Report an error in one sentence. Do not retry a failed call repeatedly.

- If `talktome` is missing, ask the user to install the command from TalkToMe Settings.
- If the app is closed and cannot start, ask the user to open it.
- If Codex has no transcript yet, exchange one terminal message before the next call.
- If an API host lacks a required feature, use cooperative mode or retain text conversation.
- If a reply names a cancelled turn, discard that reply and listen for the current turn.
- If a sandbox permits no file writes, state that the voice connection cannot start there.
