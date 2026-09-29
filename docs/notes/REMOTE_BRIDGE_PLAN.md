# Remote bridge plan

Date: September 28, 2026.
Status: Approved for implementation.

## User decision

The pairing code has no automatic expiration. It remains valid until the user revokes or replaces it.
Generate at least 256 random bits for the code. Use a copyable text value, not a short numeric code.
Treat this code as a credential. Keep it out of URLs, normal logs, command arguments, and transcripts.

## First release

Connect one laptop to one remote agent bridge through a relay.
Both devices open outbound WebSocket connections.
The laptop retains the microphone, Smart Turn, transcription, speech generation, playback, and call controls.
The remote agent retains its existing session, tools, and files.
Only text and call events cross the relay. Do not send microphone audio through it.

Use cooperative `call`, `listen`, `reply`, and `end` commands for the first release.
Support Hermes, OpenClaw, Claude, Codex, and generic hosts through this same explicit command path.
Do not attach a second writer to a terminal session.
Automatic remote host adapters remain a later step.

## Components

```text
Remote agent CLI -> private local inbox -> bridge daemon
                                            |
                                    outbound WSS
                                            |
                                          relay
                                            |
                                    outbound WSS
                                            |
Laptop connector -> cooperative adapter -> existing voice pipeline
```

### Relay

Add a separate Python entry point for a self-hosted relay.
Use existing FastAPI, uvicorn, and WebSocket dependencies where suitable.
Keep the existing local JSON Lines bridge intact. It serves a different purpose.

The relay pairs two fixed roles: laptop and agent.
Use separate credentials for these roles. The agent code must not authorize the laptop role.
The relay forwards bounded protocol frames only between the two authenticated members of one pair.
It must not run shell commands, inspect files, or forward arbitrary HTTP requests.
Reject a second connection for an occupied role until the existing connection closes.
Use heartbeat timeouts to remove disconnected peers.

A relay administration command creates a pair and returns its public identifier and two credentials once.
The remote credential is the long-lived pairing code that the user copies to the server.
The laptop credential stays in the laptop configuration.
Administration runs on the relay host. Do not create a public unauthenticated pair-creation endpoint.
Store credential hashes and pair metadata in a private relay file with atomic replacement.
An administration command revokes a pair. The running relay must close revoked connections promptly.
Revocation must remain effective after a restart.

Require secure WebSockets (`wss`) for network hosts. Permit plain `ws` only for loopback development.
Keep certificate checks enabled. Bind the relay to loopback by default for use behind a TLS proxy.
Document the required TLS proxy or server certificate setup. Do not deploy a public relay during this task.
Transport encryption terminates at the relay. State that the relay can read forwarded text.
End-to-end encryption is outside this first release. Do not claim it exists.

### Remote daemon and commands

Add remote configuration and daemon commands without changing the default local CLI behavior.
Accept credentials through standard input or a private file. Save them with mode `0600`.
Use a clearly selected remote mode, such as `talktome --remote call ...`.
Document the final command names exactly as implemented.

The selected remote CLI writes to a private local inbox that the daemon watches.
Use a separate inbox from the local app. Do not send remote commands to the ordinary local inbox.
The daemon owns the network connection. This preserves file-only access for sandboxed agent commands.
Support a private temporary-directory inbox when the sandbox cannot write to the user data directory.
Check directory ownership, file permissions, filenames, request age, and input bounds.
Do not start Electron or the local voice server from remote mode.
Do not require speech models or macOS frameworks just to run the remote daemon.

The daemon reconnects with bounded backoff and sends clear connection errors to waiting commands.
It does not silently reissue a mutating command after uncertain delivery.
The agent must use `listen` and `reply` throughout the call. Ordinary host text is not automatically spoken.

### Laptop connector

Add an opt-in connector to the app lifespan. Keep existing local calls unchanged when it is not configured.
Read a private laptop configuration. Permit setup, status, and removal through narrow CLI commands initially.
Do not add a new onboarding flow or change the approved notch and call surfaces in this task.
Configuration changes can require an app restart if the documentation states that condition.

Validate remote requests before they enter the app.
Allow only call, listen, reply, and end operations.
Force cooperative mode. Ignore remote working-directory paths and use a valid local directory internally.
Namespace the connection identifier with the authenticated pair identifier.
Bind the pair to its own ringing or active call before any asynchronous wait for an answer.
Remote peers must not read, reply to, or end a local call or another pair's call.
Validate call, turn, item, and playback identifiers through the existing cooperative adapter.
Do not expose local settings, credentials, files, shell execution, or provider configuration through this transport.

Remote calls use the existing ring and explicit user answer.
An offline laptop must return an unavailable result. Do not save a ring for later automatic delivery.
Interruptions stop local playback immediately and use the existing conservative playback report.
Cancellation of remote work remains a host capability. Do not imply that stopping speech stops all work.

## Protocol and recovery

Use a versioned JSON envelope with pair-bound request IDs, operation names, and typed payloads.
Responses must match the request ID. Use bounded frame sizes, pending requests, and queues.
Multiplex requests. A 25-second listen request must not block end or cancellation messages.
Use explicit errors for unsupported versions, invalid requests, occupied roles, and unavailable peers.

Use stable item IDs for reply retries. Preserve the cooperative adapter's idempotency rules.
Prevent duplicate rings and submissions when a connection fails after delivery.
Keep a bounded private command journal at the laptop for mutating request IDs and payload hashes.
Write a claim before a mutation. A repeated ID with a different payload must fail.
After a process restart, an unfinished claim has unknown delivery and must not run again automatically.
Do not promise exactly-once execution across crashes.
Keep journal retention and the retry window consistent, so expired requests cannot become new operations.
Document the private journal contents and limits. Avoid storing transcript text unless required for a bounded reply cache.

On a network reconnect within the same process, preserve the existing call identity and event sequence when possible.
After a laptop restart, the old call is ended. Reject old turn replies and require a new explicit call request.
Do not create a new host model session during reconnection.
On pair revocation, end only that pair's call and discard its queued commands.

## Implementation steps

1. Add credential, configuration, and protocol helpers.
2. Add the relay and its local administration commands.
3. Add the remote daemon and its isolated file inbox.
4. Add explicit remote CLI routing for cooperative commands.
5. Add the laptop connector and call ownership checks.
6. Update packaged module discovery if required. Do not build the app.
7. Update the call skill with separate local and remote procedures.
8. Write setup, revocation, reconnect, and recovery documentation.
9. Run static syntax, lint, and whitespace checks only.

## Acceptance criteria for source review

- The code has no automatic pairing expiration.
- Laptop and remote credentials have different roles.
- Revocation closes the pair and remains effective after restart.
- A remote peer cannot control a local call.
- Reconnect does not produce another ring or repeat a submitted reply.
- A long listen request does not block an end request.
- Lost delivery produces an explicit unknown result instead of an automatic resend.
- Stale turn replies cannot play in a later call.
- Remote commands can use files while only the daemon uses the network.
- Local calls retain their existing behavior.
- Source and documentation state which live checks remain.
