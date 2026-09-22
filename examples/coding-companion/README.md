# Coding Companion Example

Use join-call to turn your AI coding agent into a voice-enabled pair programmer. Join a meeting, discuss code, and make changes — all through conversation.

## Overview

This example shows how to:
1. Join a meeting from your coding agent
2. Have voice conversations about your code
3. Search, edit, and commit while talking
4. Share your screen to show code or diagrams

## Prerequisites

- Claude Code, Cursor, or another Agent Skills-compatible framework
- AgentCall API key (free at [agentcall.dev](https://agentcall.dev))
- Python 3.10+ with `pip install aiohttp websockets`

## Quick Start

### 1. Setup API Key

```bash
mkdir -p ~/.agentcall
echo '{"api_key": "YOUR_KEY"}' > ~/.agentcall/config.json
```

### 2. Join a Meeting

Tell your agent:

> *"Join https://meet.google.com/abc-def-ghi"*

The agent will:
1. Start the meeting bridge
2. Join the call as "Agent"
3. Greet the first participant
4. Begin listening for questions

### 3. Have a Conversation

**You (in meeting):** "Hey, what's in the main function?"

**Agent:** *searches codebase* "The main function initializes the database connection and starts the HTTP server on port 8080. Want me to show you the code?"

**You:** "Yeah, share your screen"

**Agent:** *shares editor view* "Here it is. As you can see, it first loads environment variables, then..."

## Example Conversations

### Code Review

```
You: "Review the latest PR for any issues"
Agent: "Let me check... I see PR #42 changes the auth middleware. Looking at the diff now."
Agent: "Found a potential issue — the token validation skips expired tokens if they're within 5 minutes of expiry. This could be a security concern."
You: "Good catch. Can you suggest a fix?"
Agent: "Sure. We should check the exp claim explicitly. I'll put the suggested code in chat."
Agent: [in chat] "Change line 28: if token.exp > time.time() - 300: → if token.exp > time.time():"
```

### Debugging Together

```
You: "The tests are failing, can you figure out why?"
Agent: "Running the tests now... The error is in test_user_creation — it's expecting a 201 but getting 400."
Agent: "Looking at the test... it's missing the required 'email' field in the request body."
You: "Can you fix it?"
Agent: "Done. I've added the email field to the test fixture. Running tests again... all passing now."
You: "Great, commit that"
Agent: "Committed with message 'fix: add missing email field to user creation test'"
```

### Architecture Discussion

```
You: "Walk me through how the auth system works"
Agent: "Let me share my screen to show the diagram..."
Agent: [shares Mermaid diagram] "Users authenticate via the /login endpoint, which validates credentials against the users table."
Agent: "On success, we mint a JWT with user ID and roles. That token is checked by the auth middleware on every protected route."
You: "What about refresh tokens?"
Agent: "We store refresh tokens in Redis with a 7-day TTL. When the access token expires, the client can POST to /refresh with the refresh token to get a new pair."
```

## Tips for Good Sessions

### 1. Use Chat for Code

Speaking code is awkward. Use chat for:
- File paths
- Code snippets
- URLs and links
- Error messages

```
Agent (voice): "I found the bug. It's a null pointer in the user service."
Agent (chat): "Line 42 in src/services/user.ts: user.profile?.name should be user?.profile?.name"
```

### 2. Keep Context

Your agent maintains full session context. You can:
- Reference earlier discussions
- Build on previous changes
- Ask follow-up questions

### 3. Screenshare for Visuals

Share your screen for:
- Code walkthrough
- Architecture diagrams
- Running applications
- Test results

```json
{"command": "screenshare.start", "url": "https://mermaid.live/edit#..."}
```

### 4. Delegate Long Tasks

For tasks that take more than a few seconds:

1. Agent acknowledges: "Let me work on that"
2. Agent runs tests/builds/deploys
3. Agent reports back: "Done. All tests pass."

The agent keeps checking for your messages during long tasks.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Your Agent    │────▶│   join-call     │────▶│   AgentCall     │
│ (Claude/Cursor) │     │   (bridge)      │     │  (infrastructure)│
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        │ Commands              │ WebSocket             │ Meeting Bot
        │ (tts.speak,           │ (events,              │ (audio, video,
        │  send_chat,           │  commands)            │  transcription)
        │  screenshare)         │                       │
        ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Video Meeting                             │
│                (Google Meet / Zoom / Teams)                      │
└─────────────────────────────────────────────────────────────────┘
```

Your agent:
- Receives transcripts as `user.message` events
- Sends responses via `tts.speak` commands
- Shares screens via `screenshare.start` commands
- Maintains full coding capabilities throughout

## Cleanup

When the meeting ends:

1. Agent receives `call.ended` event
2. Agent kills the bridge process
3. Agent cleans up temp files

If the agent needs to leave early:

```json
{"command": "leave"}
```

## Next Steps

- Read the full [SKILL.md](../../SKILL.md) for all commands and events
- Try different modes: `audio`, `webpage-av`, `webpage-av-screenshare`
- Customize the bot name and voice in `~/.agentcall/config.json`

---

Built with [join-call](https://github.com/rohanprichard/join-call), powered by [AgentCall](https://agentcall.dev)
