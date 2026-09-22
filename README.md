# join-call

**Let your AI agent join Google Meet, Zoom, and Microsoft Teams — paste a link, start talking.**

An [Agent Skill](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/plugins-and-skills) that enables AI coding agents (Claude Code, Cursor, Codex, Windsurf, and 30+ more) to join video meetings with full voice and screenshare capabilities. Built on [AgentCall](https://agentcall.dev).

## What It Does

Paste a meeting link and your agent joins as a participant that can:

- **Talk** — respond via text-to-speech (54 voices, 9 languages, sub-second latency)
- **Listen** — receive real-time transcripts of what participants say
- **Screenshare** — present URLs, dashboards, code, slides dynamically during the call
- **Chat** — send and receive meeting chat messages

The agent keeps its full session context — it can search code, edit files, run commands, and commit changes while talking in the meeting. The meeting is just another I/O channel.

## Quick Start

### Prerequisites

1. **A coding agent** — Claude Code, Cursor 2.5+, OpenAI Codex CLI, Windsurf, or any Agent Skills-compatible framework
2. **Python 3.10+** with `pip install aiohttp websockets`
3. **AgentCall API key** — free tier available at [agentcall.dev](https://agentcall.dev)

### Install

#### Claude Code

```bash
/plugin marketplace add rohanprichard/join-call
/plugin install join-call@join-call
```

#### Cursor 2.5+

Use `/add-plugin` in the editor, or browse cursor.com/marketplace.

#### From GitHub (any agent)

```bash
git clone https://github.com/rohanprichard/join-call.git
```

Then point your agent at `join-call/SKILL.md`:

- **Claude Code (single-session)** — drop folder into `.claude/skills/`
- **Windsurf** — drop folder into `.windsurf/skills/`
- **Codex CLI** — drop into `~/.codex/skills/`

### Setup API Key

Get a free AgentCall API key at [agentcall.dev](https://agentcall.dev), then:

```bash
mkdir -p ~/.agentcall
echo '{"api_key": "YOUR_KEY_HERE"}' > ~/.agentcall/config.json
```

Or set the environment variable:

```bash
export AGENTCALL_API_KEY="YOUR_KEY_HERE"
```

### Join a Meeting

Tell your agent:

> *"Join this meeting: https://meet.google.com/abc-def-ghi"*

That's it. The agent joins, greets participants, and participates in the conversation.

## Capabilities

| Feature | Description |
|---------|-------------|
| **Voice** | Real-time TTS with 54 voices across 9 languages |
| **Transcription** | Live speech-to-text from all participants |
| **Screenshare** | Share URLs, local pages, slides, dashboards |
| **Chat** | Send/receive meeting chat messages |
| **Screenshots** | Capture what's on screen (presentations, slides) |

### Supported Platforms

| Platform | Status |
|----------|--------|
| Google Meet | ✅ Full support |
| Zoom | ✅ Full support |
| Microsoft Teams | ✅ Full support |

## Usage Examples

### Voice Conversation

```
User: "Join https://meet.google.com/xyz and help me review the PR"
Agent: *joins meeting, greets participant*
Agent: "Hi! I'm ready to review the PR. Can you share your screen or tell me the PR number?"
```

### Screenshare Presentation

```
User: "Show them the deployment dashboard"
Agent: *shares https://dashboard.example.com in the meeting*
Agent: "Here's our deployment dashboard. As you can see, all services are healthy..."
```

### Code Review in Meeting

```
User (in meeting): "What's in the main function?"
Agent: *searches codebase*
Agent: "The main function initializes the database connection and starts the HTTP server on port 8080..."
```

## Modes

| Mode | Visual | Use Case |
|------|--------|----------|
| `audio` | Voice only | Simple voice conversations, note-taking |
| `webpage-av` | Voice + avatar | Visual presence with animated avatar |
| `webpage-av-screenshare` | Voice + avatar + screenshare | Presentations, sharing content |

Default mode is `audio`. For avatar or screenshare, specify in your request:

> *"Join the meeting with screenshare capability"*

## How It Works

join-call is a thin wrapper around [AgentCall](https://agentcall.dev), the infrastructure layer that handles:

- Meeting bot orchestration (joining, leaving, reconnecting)
- Real-time audio/video streaming
- Speech-to-text and text-to-speech
- Secure tunneling for screenshare content

This skill provides the Agent Skills interface (SKILL.md) and convenience scripts so any compatible agent can participate in meetings with minimal setup.

## vs. Listen-Only Tools

Traditional meeting integrations are passive — they join, record, and generate summaries after the call ends.

join-call is an **active participant**:

| Feature | Listen-Only Tools | join-call |
|---------|-------------------|-----------|
| Real-time voice responses | ❌ | ✅ |
| Screenshare during call | ❌ | ✅ |
| Code search while talking | ❌ | ✅ |
| Interactive Q&A | ❌ | ✅ |
| Commit changes during call | ❌ | ✅ |

## AgentCall Dependency

This skill requires [AgentCall](https://agentcall.dev) for meeting infrastructure:

- **Free tier**: 6 hours of meeting time, 1 concurrent call, all features
- **Paid**: Per-minute billing for additional usage

AgentCall handles all the complex meeting bot infrastructure so you don't have to. See [agentcall.dev](https://agentcall.dev) for pricing details.

## Configuration

Configuration is stored in `~/.agentcall/config.json`:

```json
{
  "api_key": "ak_ac_xxxxx",
  "default_mode": "audio",
  "default_voice": "af_heart",
  "default_bot_name": "Agent"
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `api_key` | required | Your AgentCall API key |
| `default_mode` | `audio` | Default call mode |
| `default_voice` | `af_heart` | Default TTS voice |
| `default_bot_name` | `Agent` | Bot name in participant list |

## Troubleshooting

### "No API key found"

Set up your API key:
```bash
mkdir -p ~/.agentcall
echo '{"api_key": "YOUR_KEY"}' > ~/.agentcall/config.json
```

### "Bot is stuck joining"

Meeting bots take 30-90 seconds to join (varies by platform). Google Meet is fastest, Teams/Zoom can take longer. The agent will wait automatically.

### "Can't hear the bot"

Ensure the meeting host hasn't muted the bot. In some meetings, new participants join muted by default.

### "Screenshare not working"

Screenshare requires `webpage-av-screenshare` mode. Tell your agent:
> *"Join with screenshare enabled"*

## Examples

See [examples/coding-companion/](examples/coding-companion/) for a walkthrough of using join-call as a voice-enabled coding assistant.

## License

MIT — use, modify, redistribute freely.

---

Built by [Rohan Richard](https://github.com/rohanprichard), powered by [AgentCall](https://agentcall.dev)
