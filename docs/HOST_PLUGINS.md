# Host plugins

Date: September 29, 2026.
Status: The Hermes plugin passed live calls. The OpenClaw plugin passed its unit tests and a live ring, but its agent runs are not proven yet. See [What was tested](#what-was-tested).

## Why a plugin

With the skill, the model runs the call. It runs `talktome listen`, reads the turn, and runs `talktome reply`.
Each voice turn therefore costs at least two extra model calls on the whole session before the real answer.
On a Hermes session with 300,000 tokens, each of these calls took 5 to 15 seconds.

A plugin moves that loop into the host.
The model calls one tool to ring the user. After the user answers, the plugin runs `listen` and `reply` itself.
Each spoken turn reaches the model as a normal message, and the model only answers.

The plugins use the `talktome` command, so they work in the same two places as the skill:

- On the Mac that runs TalkToMe.
- On a server that is paired with the Mac through the [remote bridge](REMOTE_BRIDGE.md). The plugin reads `talktome remote-status` and adds `--remote`.

## Install

```sh
talktome plugin install --agent hermes
talktome plugin install --agent openclaw
```

Then restart the host gateway: `hermes gateway restart` or `openclaw gateway restart`.

`talktome plugin status --agent AGENT` shows whether the installed plugin matches this version of TalkToMe.
`talktome plugin remove --agent AGENT` removes it.

The plugin files ship inside the talktome package, so the plugin and the command have the same version.
After you update talktome, run `plugin install` again.

## Place a call

Ask the agent to call you. The agent calls the `talktome_call` tool with a greeting.
The tool rings the Mac and waits for the answer. It returns `answered: true` or `answered: false`.
`talktome_end` ends the call. The agent uses it only when the user asks.

The skill tells the agent to use the tool when it exists.

## Hermes

The plugin is a Hermes platform named `talktome`. A call is a chat on that platform.

- When the user answers, the plugin points the call's chat at the session that placed the call. It uses the same session switch as `/resume`. The voice turns continue that conversation.
- Hermes can send more than one message for a turn, for example a short note before a tool call and then the answer. The plugin holds the newest message and speaks the one before it as progress. When Hermes finishes the turn, the held message is spoken as the final reply.
- The plugin removes markdown, code blocks, and URLs before speech.
- A turn that fails with no reply speaks one short apology, so the turn on the Mac ends.

`plugin install` also writes these values under `display.platforms.talktome` in the Hermes config, but only for keys that are not set:

| Key | Value | Reason |
| --- | --- | --- |
| `tool_progress` | `off` | Tool progress lines do not make sense as speech. A global `display.tool_progress` outranks a platform default, so the plugin sets its own. |
| `streaming` | `false` | Voice has no message edits. |
| `interim_assistant_messages` | `true` | A short note before long work becomes spoken progress. |
| `show_reasoning`, `long_running_notifications`, `busy_ack_detail` | `false` | Status text is not speech. |

The platform sets a home channel, so the gateway does not ask for `/sethome` on the first call.
The bridge credential and the user's answer to the ring authorize each turn, so the platform uses upstream authorization.

## OpenClaw

The plugin registers the two tools. The tool factory receives the caller's session key.

- Each spoken turn runs through OpenClaw's embedded agent in the caller's session, with a short voice prompt. The bundled `voice-call` plugin runs its agent in the same way.
- Block replies are spoken as progress. The last one is the final reply.
- When the user talks over a reply, TalkToMe cancels the turn. The plugin then aborts the agent run for that turn.
- The plugin uses the agent's configured model.

## Limits

- The call's chat and the original chat share one session. If both chats send a message at the same time, the two turns can overlap. In practice the first voice turn starts after the greeting, when the tool call has already finished.
- A Hermes turn that the user talks over is not stopped. Hermes decides what to do with the new message, based on its `busy_input_mode`.
- The plugins depend on host internals: the Hermes session store and the OpenClaw extension API. A host update can change them. `hermes plugins doctor talktome` checks the Hermes plugin.

## What was tested

Hermes Agent v0.20.4 on Ubuntu 24.04, paired with a Mac through the SSH bridge:

- A one-shot cron job asked Hermes to call. The Mac rang, and a script answered and sent text turns.
- "What is two plus two?" returned "Two plus two is four." as the final reply.
- A question that needed a terminal command returned the disk space in about 7 seconds. No tool progress lines were spoken.
- A second turn in the same call remembered the first turn.
- A hang-up on the Mac ended the plugin's loop at once.

Still to check with Hermes:

- A call placed from a real chat, where the session stays live after the tool call.
- A spoken interruption during a long tool run.

OpenClaw 2026.2.15 on the same server:

- The plugin logic passed unit tests with a fake laptop and a fake agent run.
- The live agent runs could not be checked. The OpenClaw agent on that server fails every turn with `HTTP 401: User not found.` from OpenRouter, before any TalkToMe code runs.
