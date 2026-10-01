---
name: talktome
description: Voice calls with the user through talktome remote calling. Use when the user asks you to call them, ring them, check in by voice, or tell them when a long task is done, and when you need a decision from the user while they are away from the keyboard.
---

# talktome calls

The `talktome` MCP server rings the user's computer through the talktome app. The talktome server on this machine carries the call.

## Tools

- `call_user` rings the user. With `question`, the call asks it, ends after the answer, and returns the answer. Without `question`, the call stays open for `call_turn`.
- `call_turn` says something in the open call and returns what the user says next. `user_said` is null when the user said nothing in time. `ended` is true when they hung up.
- `end_call` hangs up. Pass `say` for a short goodbye.
- `notify_user` shows a notice without ringing. Use it for news that needs no answer, such as a finished task.

## How to talk

- The user hears your words as speech. Use one or two short sentences.
- Do not read out markdown, code, file paths, or URLs.
- Ask one question at a time.
- When the user asks you to do some work and then call them, do the work first. Call once, with the result. Do not call to say that you are starting.
- If the user asks during a call for work that takes more than a minute, say what you will do and end the call. Do the work. Then call again, or use `notify_user`, with the result.

## When the user calls in

The user can join this session by voice while you work. Their words arrive as context after a tool call, or as a reason to continue when you stop. The context starts with "The user just said this on the talktome voice call". Answer in your normal reply, in one or two short sentences, because talktome speaks it. Do not use `call_user`, `call_turn`, or `end_call` for a call the user started: it is already connected. Then continue the task, unless the user told you to stop or change it.
