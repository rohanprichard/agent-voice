---
name: join-call
description: >
  Join video meetings (Google Meet, Zoom, Microsoft Teams) as an AI bot with
  voice and screenshare. Paste a meeting URL and your agent can talk, listen,
  share screens, and chat — all while maintaining full coding capabilities.
  Powered by AgentCall (agentcall.dev).
argument-hint: <meeting-url> [--mode audio|webpage-av-screenshare] [--name BotName]
license: MIT
---

# join-call

**Let your AI agent join video meetings with voice and screenshare.**

Use this skill when asked to:
- Join a meeting, call, or video conference
- Participate in a Google Meet, Zoom, or Teams call
- Talk to someone in a meeting
- Share your screen in a meeting
- Present something during a call

## Prerequisites

- Python 3.10+ with `pip install aiohttp websockets`
- AgentCall API key (free tier: 6 hours, all features)

### API Key Setup

Before joining a meeting, ensure an API key is configured:

1. **Check** `~/.agentcall/config.json` — if it has `api_key`, you're ready
2. **Check** `AGENTCALL_API_KEY` env var — if set, you're ready
3. **If neither exists**, ask the user to get a free key at https://agentcall.dev

Save the key:
```bash
mkdir -p ~/.agentcall
echo '{"api_key": "USER_KEY_HERE"}' > ~/.agentcall/config.json
```

**Do NOT ask for the API key every session** — check the config file first.

## Quick Start

### Join a Meeting

```bash
python scripts/join.py "https://meet.google.com/abc-def-ghi" --name "Agent"
```

### With Screenshare

```bash
python scripts/join.py "https://meet.google.com/abc-def-ghi" --name "Agent" --mode webpage-av-screenshare
```

## How to Join a Call

### Step 1: Start the Bridge

Run the bridge script in background with file-based I/O:

```bash
EVENTS="$PWD/meeting-events.jsonl"
COMMANDS="$PWD/meeting-commands.jsonl"
: > "$COMMANDS"

python scripts/join.py "<meeting-url>" --name "Agent" --output "$EVENTS" \
  < <(tail -f "$COMMANDS") &
BRIDGE_PID=$!
```

### Step 2: Monitor Events

Stream events (recommended for Claude Code with Monitor tool):

```bash
tail -f "$EVENTS" | grep --line-buffered -E \
  '"event": "(user\.message|greeting\.prompt|call\.(ended|bot_ready)|participant\.(joined|left)|chat\.received|tts\.(done|error))"'
```

### Step 3: Send Commands

Append commands to the commands file:

```bash
echo '{"command": "tts.speak", "text": "Hello everyone!"}' >> "$COMMANDS"
```

## Events You Receive

| Event | Description |
|-------|-------------|
| `call.bot_ready` | Bot has joined the meeting |
| `greeting.prompt` | First participant joined — greet them |
| `user.message` | Someone spoke (VAD-coalesced transcript) |
| `chat.received` | Meeting chat message received |
| `participant.joined` | Someone joined the meeting |
| `participant.left` | Someone left the meeting |
| `tts.done` | TTS finished speaking |
| `call.ended` | Meeting ended |

## Commands You Send

### Voice

```json
{"command": "tts.speak", "text": "Hello everyone!", "voice": "af_heart"}
```

Available voices: `af_heart`, `af_bella`, `am_adam`, `am_michael`, `bf_emma`, `bm_george`

### Chat

```json
{"command": "send_chat", "message": "Here's the PR link: https://github.com/..."}
```

Use chat for URLs, code, and text that sounds bad via TTS.

### Screenshare (webpage-av-screenshare mode)

Start sharing:
```json
{"command": "screenshare.start", "url": "https://your-dashboard.com"}
```

Or share local content:
```json
{"command": "screenshare.start", "port": 3001}
```

Stop sharing:
```json
{"command": "screenshare.stop"}
```

### Screenshot

```json
{"command": "screenshot"}
```

Returns base64 JPEG of what's on screen — useful for reading slides or presentations.

### Leave

```json
{"command": "leave"}
```

**Always send `leave` when done** — orphaned bots consume credits.

## The Call Loop (MANDATORY)

You MUST follow this algorithm for the entire call duration:

```
1. Start bridge with --output
2. Monitor events via tail -f or polling

3. CALL_LOOP (repeat until call.ended):
   a. CHECK for new events
   b. Process events:
      - greeting.prompt → greet the participant via tts.speak
      - user.message → respond appropriately
      - chat.received → process text input
      - call.ended → EXIT LOOP
   c. If doing work (code search, file read):
      - Acknowledge first: "Let me check that"
      - Do ONE step
      - Check for new events
      - Continue
   d. Sleep briefly if no events

4. After EXIT: kill bridge, clean up files
```

**Critical rules:**
- NEVER stop the loop before `call.ended`
- Greet participants when they join (greeting.prompt)
- Acknowledge before long tasks ("Let me check that")
- Always clean up when done

## Active Participation (Default Behavior)

Unless explicitly asked to be silent, you MUST:

1. **Greet** — When `greeting.prompt` fires, say hello
2. **Respond** — If addressed by name or asked a question, respond
3. **Contribute** — Share relevant knowledge proactively
4. **Acknowledge** — If processing, say "Let me check that" first

**Silent/notetaker mode is opt-in only.** Only go silent if the user explicitly asks.

## Modes

| Mode | What You Get | When to Use |
|------|--------------|-------------|
| `audio` | Voice only | Simple conversations (default) |
| `webpage-av` | Voice + animated avatar | Visual presence |
| `webpage-av-screenshare` | Voice + avatar + screenshare | Presentations, demos |

## Tips for Good Conversations

1. **Keep responses short** — 2-3 sentences for normal replies. Meetings are real-time.

2. **Use chat for code/URLs** — TTS reads `$` as "dollar", `{}` as "curly brace". Put code in chat:
   ```
   tts.speak: "I found the bug. Posting the fix in chat."
   send_chat: "Change line 42: user.name → user.displayName"
   ```

3. **Acknowledge before work** — Don't leave silence. Say "Let me check" before searching code.

4. **Check events during work** — The user might interrupt or add context. Check between steps.

## Screenshare Patterns

### Share a URL

```json
{"command": "tts.speak", "text": "Let me share my screen."}
{"command": "screenshare.start", "url": "https://slides.google.com/..."}
```

### Share Local Content

Start a local server and share via tunnel:

```bash
python -m http.server 3001 --directory /tmp/slides/
```

```json
{"command": "screenshare.start", "port": 3001}
```

Update content by modifying files — the page auto-refreshes.

### Stop Sharing

```json
{"command": "screenshare.stop"}
```

## Cleanup (MANDATORY)

When the call ends:

1. Send `{"command": "leave"}` (if you're ending the call)
2. Kill the bridge subprocess
3. Kill any local HTTP servers you started
4. Delete event/command files

Orphaned bots run until max_duration (1 hour), consuming credits.

## Examples

### Simple Greeting

```
Event: {"event": "greeting.prompt", "participant": "Alice"}
Action: {"command": "tts.speak", "text": "Hi Alice! I'm your coding assistant. What can I help with today?"}
```

### Answering a Question

```
Event: {"event": "user.message", "speaker": "Alice", "text": "what's in the main function"}
Action: *search codebase for main function*
Action: {"command": "tts.speak", "text": "The main function sets up the database and starts the server on port 8080. Want me to share the code in chat?"}
```

### Sharing a Screen

```
Event: {"event": "user.message", "speaker": "Bob", "text": "can you show us the architecture diagram"}
Action: {"command": "tts.speak", "text": "Sure, let me share my screen."}
Action: {"command": "screenshare.start", "url": "https://miro.com/app/board/xxx"}
Action: {"command": "tts.speak", "text": "Here's our system architecture. The API gateway is on the left..."}
```

## Dependency

This skill wraps [AgentCall](https://agentcall.dev). All meeting infrastructure (joining, streaming, TTS, transcription) is handled by AgentCall.

- **Free tier**: 6 hours, 1 concurrent call, all features
- **Pro**: Per-minute billing for more usage

Get your free API key at [agentcall.dev](https://agentcall.dev).

## Troubleshooting

### Bot stuck on "joining"

Normal. Bots take 30-90 seconds to join. Google Meet is fastest.

### No transcript events

Check that `--transcription` is not disabled (it's on by default).

### Screenshare shows blank

Verify the URL is accessible. For local content, ensure the HTTP server is running.

---

Powered by [AgentCall](https://agentcall.dev) | MIT License | [rohanprichard/join-call](https://github.com/rohanprichard/join-call)
