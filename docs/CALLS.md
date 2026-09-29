# Call history

TalkToMe keeps a short record of each call on this Mac. It does not send the history anywhere.

## What the app stores

Each call has one record with these fields:

- The agent type: `codex`, `claude`, `hermes`, `openclaw`, `generic`, or `remote`.
- The session or thread ID, the caller name, and the project folder.
- The times when the ring started, when you answered, and when the call ended.
- The duration and the outcome: `answered`, `missed`, `declined`, or `failed`.

The app keeps the last 500 calls. It removes the oldest record when a new call starts.

Transcripts are off by default. When transcripts are off, the app does not save what you or the agent said.
In Settings, **Save call transcripts** can keep each transcript for 7 or 30 days.
The app removes old transcripts when it starts and once a day.
If you select **Off**, the app deletes all saved transcripts.

## Where the app stores it

The files are in `calls/` in the data directory. The default data directory is `~/Library/Application Support/talktome`.

| File | Contents |
| --- | --- |
| `calls.jsonl` | One call record on each line |
| `settings.json` | The transcript setting |
| `transcripts/<call id>.json` | The transcript of one call, when transcripts are on |

The folders have mode `0700` and the files have mode `0600`. Only your account can read them.

## How to delete it

- In the Calls window, select **Delete** on a call. This also deletes its transcript.
- In the Calls window, select **Clear history**. This deletes all records and all transcripts.
- Quit TalkToMe, then delete the `calls/` folder.

## Call back

**Call back** starts a call to the same session with no ring, because you started the call.
The app says "Calling <name>." with the current voice.
Your first sentence goes to the agent after this line: `[TalkToMe] The user called you back by voice. Reply by voice, briefly.`

- **Codex:** The app joins the thread through `codex queue`, as a ring does. A terminal must hold the thread.
  If the thread has no rollout file, or no terminal reads the message, the app shows "That Codex session is closed."
  **Open in Terminal** opens Terminal.app in the project folder and runs `codex resume <id>`.
- **Claude Code:** For each turn, the app runs `claude -p --resume <id> --output-format stream-json --verbose --include-partial-messages` in the project folder.
  Claude runs without a terminal, so it denies a tool that needs permission, unless your Claude settings allow that tool.
  The session ID must be a real Claude Code session ID, not a connection ID.
- **Hermes and OpenClaw:** The app opens the saved session through the configured host.
- **Generic and remote calls:** Call back is not available. TalkToMe has no way to reach these sessions.

Only one call can be live. Call back does not start when another call is live or ringing.

## Routes

All routes need the local token.

| Route | Purpose |
| --- | --- |
| `GET /v1/calls` | The calls, newest first, and the transcript setting |
| `DELETE /v1/calls/{id}` | Delete one call and its transcript |
| `DELETE /v1/calls` | Delete all calls and transcripts |
| `GET /v1/calls/{id}/transcript` | The saved transcript of one call |
| `POST /v1/calls/{id}/callback` | Call back |
| `POST /v1/calls/{id}/terminal` | Open a closed Codex session in Terminal |
| `POST /v1/calls/settings` | Set `transcripts` to `off`, `7d`, or `30d` |
