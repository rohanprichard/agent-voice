# Security

## Report a vulnerability

Do not open a public issue for a security problem.

1. Open the repository on GitHub.
2. Select **Security**, then **Report a vulnerability**.
3. Describe the problem, the affected version, and the steps to reproduce it.

Use GitHub's private vulnerability reporting feature to report a security problem.
TalkToMe is a small project. Only the latest release gets security fixes.

## Trust model

TalkToMe runs on one Mac for one user account.
It trusts every program that runs as that account.
This section lists what TalkToMe exposes, so that you can decide if it fits your use.

### Local server

- The server listens only on `127.0.0.1:8765`.
- Each request must have the local token. The server compares tokens in constant time.
- The server refuses requests with an unknown `Host` or `Origin` header.
- The token file has mode `0600` in a data folder with mode `0700`.
- The desktop window uses an `HttpOnly`, `SameSite=Strict` cookie and a strict content security policy.
- The Electron windows use context isolation and the renderer sandbox. They do not enable Node.js integration.

### File inbox for agent commands

An agent sandbox often blocks network access to `127.0.0.1`.
Thus `talktome call` and related commands leave a request file for the app.
The app reads requests from its data folder and from `/tmp/talktome-<uid>/requests`.

- A request file needs no token. Any program that runs as your account can ring the app, end a call, or send a reply.
- The app reads a folder only if your account owns it and no other account can write to it.
- The app writes each reply to a new file name and does not follow symbolic links.

### Agent connections

- **Install** in Settings writes the TalkToMe skill into the skills folders of Codex, and of Hermes and OpenClaw when their profiles exist. It also writes the `talktome` command to a folder on your `PATH`.
- `talktome configure-agent` saves the Hermes or OpenClaw token as plain text in `agent-hosts.json` in the data folder. The file has mode `0600`.
- To find agent commands, the app starts your login shell once (`$SHELL -lic`). This runs your shell startup files.
- The connected agent receives your transcript. It runs its tools with its own permissions. TalkToMe does not add a sandbox.

### Speech data

- Local recognition and local voices keep audio on this Mac.
- ElevenLabs recognition sends microphone audio to ElevenLabs. ElevenLabs voices send reply text to ElevenLabs.
- The ElevenLabs key stays in memory, or in the system keychain if you select **Remember key**.

### Remote bridge (experimental)

The remote bridge connects an agent on a server to the app on your Mac through a relay that you host.
Nobody tested it live yet.

- The relay can read every message that it forwards. There is no end-to-end encryption.
- The relay can also send its own calls and replies to either side. Run the relay only on a host that you trust.
- The relay has no TLS. It binds only to loopback, unless you give `--allow-network`. Put it behind a TLS proxy for network use.
- The relay stores pair credentials as SHA-256 hashes and compares them in constant time.

## Supported versions

| Version | Security fixes |
| --- | --- |
| Latest release | Yes |
| Older releases | No |
