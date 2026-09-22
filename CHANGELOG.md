# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-22

### Added

- Initial release of join-call Agent Skill
- SKILL.md with YAML frontmatter and agent instructions for joining meetings
- Python bridge script (`scripts/join.py`) wrapping AgentCall
- Support for Google Meet, Zoom, and Microsoft Teams
- Voice capabilities via TTS (54 voices, 9 languages)
- Screenshare support in `webpage-av-screenshare` mode
- Meeting chat send/receive
- Screenshot capture for reading presentations
- VAD-coalesced transcript events for natural conversation flow
- `.claude-plugin/` metadata for Claude Code marketplace
- Coding companion example with conversation patterns

### Dependencies

- Requires [AgentCall](https://agentcall.dev) API key (free tier available)
- Python 3.10+ with `aiohttp` and `websockets`

---

Built by [Rohan Richard](https://github.com/rohanprichard), powered by [AgentCall](https://agentcall.dev)
