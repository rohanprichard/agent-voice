# Security

## Report a vulnerability

Do not open a public issue for a security problem.

1. Open the repository on GitHub.
2. Select **Security**, then **Report a vulnerability**.
3. Describe the problem, the affected version, and the steps to reproduce it.

Use GitHub's private vulnerability reporting feature to report a security problem.
talktome is a small project. Only the latest release gets security fixes.

## Trust model

talktome runs for one user. On each machine, it trusts every program that runs as that user.
This section lists what talktome exposes, so that you can decide if it fits your use.

### The app and its servers

- The app starts `talktome-server` on this Mac as a child process, and on a server with `ssh -o BatchMode=yes`. It talks to it on stdin and stdout.
- Nothing listens on the network. On a server, SSH does the authentication and the encryption.
- `ssh` never asks for a password and never accepts a new host key by itself.
- The Electron windows use context isolation and the renderer sandbox. They do not enable Node.js integration.

### The local socket

- `talktome-server` serves a Unix socket with mode `0600`, in a folder with mode `0700`.
- Any program that runs as your user can use it: it can ring you, speak in a call, and answer a hook.
- A newer server asks a running one to stop, so the newest app connection wins.

### Agents

- The plugin installer writes files into the agent's own folders: `~/.claude/skills/talktome`, a local Codex marketplace in `~/.codex/talktome-plugins`, `~/.hermes/plugins/talktome`, and OpenClaw's extensions.
- The hooks and MCP servers run `talktome-server` by its full path.
- In a call into a project, talktome runs `claude -p` or `codex exec` in that folder, with the agent's own permissions. Claude asks you in the call before a tool that needs permission runs.
- The connected agent receives what you say. talktome does not add a sandbox.

### Speech data

- Speech uses your own ElevenLabs account. Microphone audio goes from the Mac to ElevenLabs, and reply text goes to ElevenLabs to be spoken.
- The ElevenLabs key is kept with the macOS keychain. The app makes a single-use token for each call.
- Audio never goes to your servers.

## Supported versions

| Version | Security fixes |
| --- | --- |
| Latest release | Yes |
| Older releases | No |
