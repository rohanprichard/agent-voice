# talktome-server

The agent side of talktome voice calls. Install it on each machine where your coding agents run. The talktome app starts it: on your own computer as a child process, and on a server over SSH. Nothing listens on the network.

```sh
uv tool install talktome-server
talktome-server plugin install --host claude   # or codex, hermes, openclaw
```

## What it does

- It rings you when an agent calls `call_user`, and shows a notice for `notify_user`.
- It lets you call into a project: it continues the newest Claude Code or Codex session there, or starts a new one.
- It lets you join an open Claude Code or Codex session while it works. Your words reach the agent after its next tool call, or when it stops.
- It asks you in the call before the agent runs a tool that needs permission.

## Commands

| Command | What it does |
| --- | --- |
| `talktome-server` | Serve the talktome app on stdin and stdout. The app runs this. |
| `talktome-server status` | Show whether a server runs on this machine. |
| `talktome-server hosts` | List the agent hosts here, and the state of their plugins. |
| `talktome-server plugin install --host HOST` | Add the plugin to `claude`, `codex`, `hermes`, or `openclaw`. |
| `talktome-server mcp` | Serve the call tools over MCP. The plugins run this. |

Codex runs a plugin's hooks only after you trust them. After you install the Codex plugin, open `/hooks` in a new Codex session and trust the talktome hooks.

## How it talks to the app

The app and the server exchange one JSON object per line on stdin and stdout. The message names are the same as in the talktome relay protocol. Agents, hooks, and plugins reach the server through a Unix socket with mode `0600`.
