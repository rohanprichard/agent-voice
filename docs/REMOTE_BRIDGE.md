# Remote bridge

Date: September 28, 2026.
Status: Implemented. The SSH path passed a live test on one Mac with a stand-in for ssh.

## What this is

The remote bridge connects one laptop to one remote agent server through a
self-hosted relay. Both devices open outbound WebSocket connections to the
relay. Only bounded text and call-event frames cross it. In the main setup, the relay
runs on the agent server, and the laptop reaches it through an SSH tunnel.

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

The laptop keeps the microphone, Smart Turn, transcription, speech generation,
playback, and call controls. The remote server keeps its existing session,
tools, and files. Microphone audio never crosses the relay. The first release
carries the four cooperative commands `call`, `listen`, `reply`, and `end`, and
works for Hermes, OpenClaw, Claude, Codex, and generic hosts through that same
explicit command path.

The local file inbox is unchanged. This adds a second, separate path.

## Security and privacy

- The pairing code is a credential. It has no automatic expiration and stays
  valid until the pair is revoked. It is generated from at least 256 random
  bits and is a copyable text value, not a short number.
- Laptop and agent credentials are different. The agent pairing code cannot
  authorize the laptop role, and the laptop credential cannot authorize the
  agent role.
- Credentials are read from standard input. They are never command arguments,
  never printed by setup, and never written to logs or transcripts.
- Credential hashes and pair metadata live in a private relay file with mode
  `0600`, replaced atomically. Whole credentials are never stored there.
- The relay can read every forwarded frame. Transport encryption ends at the
  relay. There is no end-to-end encryption in this release, and none is
  claimed.
- The relay can also send its own frames to either member. A relay operator can
  thus start calls and send replies. Run the relay only on a host that you trust.
- Network relay URLs must use `wss`. Plain `ws` is allowed only on loopback for
  development. Certificate checks stay enabled on both clients.
- The relay binds loopback by default and does not terminate TLS itself. Put it
  behind a TLS proxy, or give it a server certificate, before any network use.
- In the SSH setup, the relay binds only loopback on the server, and SSH
  encrypts the connection from the laptop. The relay is never open to the
  network, and it needs no TLS certificate.
- In the SSH setup, the laptop credential goes from the server to the laptop
  only inside the SSH output of `remote-connect`. It is never printed on the
  laptop, never written to a log, and never put in a command argument.
- The app runs `ssh` with `BatchMode=yes`. It never asks for a password and never
  accepts a new host key by itself. You accept the host key once, during
  `remote-connect`.
- A relay administration command runs on the relay host and edits the private
  file directly. There is no public unauthenticated pair-creation endpoint.

## Setup

The main setup uses SSH. The relay runs on the agent server and binds only
loopback. The laptop reaches it through an SSH tunnel that the app opens itself.
You need an SSH login from the laptop to the server.

### 1. Install talktome on the server

Install [uv](https://docs.astral.sh/uv/), then install the `talktome` command:

```sh
uv tool install git+https://github.com/rohanprichard/talktome
```

This installs the package's console scripts, which include `talktome`. uv puts
them in `~/.local/bin`. The package also includes the speech libraries, so the
install is large. To install from a checkout instead, run
`uv tool install /path/to/talktome`.

### 2. Pair from the laptop

On the laptop, run:

```sh
talktome remote-connect user@server --install-service
```

This command does these steps:

1. It runs `talktome remote-init --json` on the server over SSH. That command
   makes a pair in the server's relay file and saves the agent credential on
   the server.
2. It reads the laptop credential from the SSH output and saves it on the
   laptop with mode `0600`. It saves the SSH target and the relay port too.
3. With `--install-service`, it runs `talktome remote-service install` on the
   server. The service keeps `talktome remote-up` running.
4. It prints what is left to do.

This SSH session is interactive. If SSH asks you to accept the host key or to
type a password, answer it.

Options:

- `--ssh-port PORT` for an SSH server that does not listen on port 22.
- `--relay-port PORT` for the relay port on the server. The default is 8766.
- `--remote-command CMD` when `talktome` is not on the server's login `PATH`.
  For example, `--remote-command ~/.local/bin/talktome`.
- `--replace` when the server already has a pairing. See
  [Replace a pairing](#replace-a-pairing).

Without `--install-service`, keep `talktome remote-up` running on the server
yourself, for example in tmux.

### 3. Restart TalkToMe

Restart the app on the laptop. The connector starts when the app starts. It
opens the SSH tunnel, then connects to the relay through it.

To see the state of the connector and the tunnel, run:

```sh
talktome connector-status
```

The `connector` field shows the connection, the tunnel state, and the last
error, such as an SSH login failure.

### SSH keys

The app runs `ssh` with `BatchMode=yes`, so it never waits at a password
prompt. The tunnel needs a login that works without a prompt:

- A key in `~/.ssh` that the server accepts, with no passphrase, or
- A key with a passphrase that is loaded in the macOS SSH agent, for example
  with `ssh-add --apple-use-keychain`.

To make sure that the login works, run `ssh user@server true` in a terminal. It
must finish without a prompt. The app uses your own `~/.ssh/config`, so a host
alias from that file also works as the target.

If the login fails, the connector keeps trying, with a wait of up to 60 seconds
between tries. `connector-status` shows the reason, for example
`SSH could not log in to user@server with a key`.

### When the laptop sleeps

When the laptop sleeps or changes network, SSH stops. The server alive checks
end a dead session after about 45 seconds. The app then starts SSH again, with a
wait that starts at 1 second and increases to 60 seconds. When the tunnel is up
again, the connector connects again. A call that was live stays live in the
app, and the next agent command continues it.

If the local relay port is busy on the laptop, the tunnel uses a free port.

When the app quits, the tunnel stops. The `ssh` process runs under a small
watchdog. If the app server stops in any way, even with `SIGKILL`, the watchdog
stops `ssh` too.

### Replace a pairing

`remote-init` refuses to run on a server that already has a pairing. Then
`remote-connect` stops and tells you what to do. To replace the pairing, run:

```sh
talktome remote-connect user@server --replace --install-service
```

`--replace` revokes the old pair in the server's relay file, removes the old
agent configuration, and makes a new pair. The old laptop credential then stops
working. The service install starts `remote-up` again with the new pair. If you
run `remote-up` yourself, start it again.

To remove a pairing, run `talktome remote-remove` on the server. It also
revokes the pair when the pair is in the server's relay file. Then run
`talktome connector-remove` on the laptop, and restart the app.

### Server service

`talktome remote-service install` writes a user service that runs
`talktome remote-up`, and starts it. The service runs this install's Python
interpreter by its absolute path. It keeps `TALKTOME_DATA_DIR`,
`TALKTOME_REMOTE_DIR`, and `TALKTOME_RELAY_FILE` when they are set.

- On Linux, it writes `~/.config/systemd/user/talktome-remote.service` and
  enables it. A user service stops at logout unless linger is on. If linger is
  off, the command prints `sudo loginctl enable-linger USER`.
- On macOS, it writes
  `~/Library/LaunchAgents/com.rohanprichard.talktome.remote.plist`. A launchd
  agent runs while the user is logged in, and starts again at login.

The service starts `remote-up` again when it stops. `remote-up` also starts its
relay child again when the relay stops. Logs go to the journal on Linux, and to
`remote-up.log` in the data folder on macOS.

```sh
talktome remote-service install
talktome remote-service status
talktome remote-service remove
```

### Commands

On the laptop:

```sh
talktome remote-connect USER@HOST [--install-service] [--replace] [--ssh-port PORT] [--relay-port PORT] [--remote-command CMD]
talktome connector-status
talktome connector-remove
```

On the server:

```sh
talktome remote-init [--replace] [--relay-port PORT] [--json]
talktome remote-up
talktome remote-service install|status|remove
talktome remote-status
talktome remote-remove
```

`remote-init` without `--json` prints the laptop steps for a manual setup. The
steps use `connector-setup --ssh-host USER@HOST`, so the app still opens the
tunnel itself.

## Advanced: a relay with TLS

Use this setup when the relay runs on a different host, or when the laptop
cannot use SSH to reach the server. The relay then sits behind a TLS proxy, and
both ends connect with `wss://`. No SSH tunnel is used.

### Relay host setup

On the relay host, create one pair:

```sh
talktome relay-pair --label "office laptop"
```

The command prints the public pair identifier and two credentials once:

```json
{
  "pair": "pair_...",
  "laptop_credential": "ttlaptop_...",
  "agent_credential": "ttagent_...",
  "label": "office laptop"
}
```

Copy the agent pairing code to the server and the laptop credential into the
laptop connector. This is the only time either is shown. The pair metadata
defaults to `<data dir>/relay/relay.json`. To change it, use `--relay-file` or
`TALKTOME_RELAY_FILE`.

Run the relay behind a TLS proxy:

```sh
talktome relay-serve --relay-host 127.0.0.1 --relay-port 8766
```

The equivalent console entry point is `talktome-relay`. The relay serves plain
`ws`. It refuses a non-loopback bind address unless you add `--allow-network`.
The proxy must end TLS and forward the WebSocket route `/v1/relay`.

The local relay administration commands are:

```sh
talktome relay-pair [--label LABEL]
talktome relay-list
talktome relay-revoke --pair PAIR_ID
talktome relay-serve [--relay-host HOST] [--relay-port PORT] [--relay-file FILE]
```

### Revocation

```sh
talktome relay-revoke --pair PAIR_ID
```

Revocation is written to the private relay file and survives a restart. A
running relay re-reads the file every second and examines every connected pair,
not only the pairs that changed since the last request. It enforces revocation
before forwarding a frame, sends a `revoked` frame, and closes both connections
with a close code distinct from a bad credential. The laptop connector then
ends only that pair's call and discards its queued commands. If the laptop was
offline when the pair was revoked, the next rejected hello ends the retained
call and the connector stops retrying. Re-running the command on an
already-revoked pair is safe.

### Service supervision

Both long-lived processes should run under a supervisor that restarts them and
keeps their environment and private files on a writable volume:

- Run `talktome-relay` on the relay host under a systemd unit or launchd agent
  with `Restart=on-failure` (`KeepAlive` on launchd), bound to loopback behind
  the TLS proxy. Give the service its own user and point `TALKTOME_RELAY_FILE`
  at a private path that user can write.
- Run `talktome-remote` on the agent server under the same user that runs the
  agent's shell commands, so both see the same remote inbox. `Restart=on-failure`
  (or launchd `KeepAlive`) covers a relay outage. The daemon also reconnects on
  its own with bounded backoff.
- The connector starts inside the app lifespan, so supervising the desktop app
  supervises the connector. It stops with the app.
- Logs may name the pair and relay URL but never a credential. Do not put a code
  in the unit file, the environment, or the command line.

### Agent server setup

On the server that runs the agent session, save the pairing code. Read it from
standard input so it never appears in a command argument:

```sh
printf '%s' "$PAIRING_CODE" | talktome remote-setup \
  --relay wss://relay.example.com --pair PAIR_ID --code-stdin
```

Start the daemon:

```sh
talktome remote-daemon
```

The equivalent console entry point is `talktome-remote`. The daemon owns the one
network connection and watches a private inbox. A command writes only a local
file, so an agent's sandbox may still block loopback connections. The daemon
does not load speech models or macOS frameworks. Run it as the same user that
runs the agent's shell commands, so both sides see the same inbox.

The agent server commands are:

```sh
talktome remote-setup --relay URL --pair PAIR_ID --code-stdin [--label LABEL]
talktome remote-status
talktome remote-remove
talktome remote-daemon
```

`remote-status` prints the saved URL and pair without the credential, and names
the inbox and its `/tmp` fallback. If the sandbox cannot write the user data
directory, the daemon also watches a private folder under
`/tmp/talktome-<uid>-remote/requests`. Set `TALKTOME_REMOTE_DIR` to choose a
different private root.

### Laptop setup

On the laptop, save the laptop credential:

```sh
printf '%s' "$LAPTOP_CREDENTIAL" | talktome connector-setup \
  --relay wss://relay.example.com --pair PAIR_ID --credential-stdin
```

Restart the TalkToMe app. The connector starts only when a laptop configuration
exists, so local calls keep their existing behavior when it does not. The
connector needs no new onboarding flow and changes no call surface.

The laptop commands are:

```sh
talktome connector-setup --relay URL --pair PAIR_ID --credential-stdin [--ssh-host USER@HOST] [--ssh-port PORT] [--label LABEL]
talktome connector-status
talktome connector-remove
```

With `--ssh-host`, the relay URL must be `ws://127.0.0.1:PORT`, and the app
opens an SSH tunnel to the same port on that host. `connector-remove` requires
an app restart so the running connector stops. A configuration change also
requires a restart.

## Remote call commands

These run on the agent server and are the only operations the bridge carries:

```sh
talktome --remote call --agent claude --thread CONNECTION_ID --greeting "Hey, what would you like to discuss?"
talktome --remote listen --thread CONNECTION_ID --after 0 --timeout 25
talktome --remote reply --thread CONNECTION_ID --call-id CALL_ID --turn-id TURN_ID --item-id ITEM_ID --text-file /tmp/voice-reply.txt
talktome --remote end
```

Use the same listen-and-reply procedure as a local cooperative call. A reply
without `--progress` ends the voice turn. Add `--progress` for a message that is
not final. Reuse the same `--item-id` only to retry that exact reply. Pass
`--request-id` only to retry the same operation; reusing a request ID with a
different payload fails. Without `--request-id`, a retry is a new operation.

The connector rewrites the remote connection ID as `<pair>:<thread>` before it
enters the app, so a remote peer cannot read, answer, or end a local call or
another pair's call. Remote calls use the ordinary ring and the user's explicit
answer. An offline laptop returns an unavailable result; the ring is not saved
for later. Local playback interruption and its conservative playback report are
unchanged.

## Protocol, delivery, and recovery

Frames are versioned JSON envelopes with a request ID, the pair it belongs to,
an operation name, and a typed payload. A response names the request it
answers. Frame size, request IDs, pending requests, and listen payloads are
bounded. Requests multiplex, so a 25-second `listen` does not block `end`.
Unsupported versions, invalid requests, occupied roles, and unavailable peers
return explicit errors.

Delivery rules:

- The daemon reconnects with bounded backoff. It does not silently reissue a
  mutating command after an uncertain delivery.
- Once a mutating request is written to the socket and the connection is lost,
  the command returns an explicit unknown result. A send that raises is
  reported as unknown too, because a partial write may have been delivered.
  Do not resend it.
- A remote command makes a request ID that carries the time it was made. The
  laptop keeps a bounded private command journal for mutating request IDs and
  payload hashes. It writes a claim before the mutation. A repeat with the same
  ID and payload returns the original result instead of a second ring or a
  second spoken message. A repeat with a different payload fails.
- A request ID older than the 24-hour acceptance window is refused even after
  its claim was pruned, so an expired entry cannot quietly become a new
  operation. A claim that survives a restart is marked unknown and is never run
  again on its own. Exactly-once execution across crashes is not promised.
- The journal is scoped to the pair, capped at 2,048 live entries, and refuses
  a new claim when it is full instead of evicting an unexpired one. An
  unreadable or corrupt journal file stops the connector rather than starting
  empty. The journal stores identifiers, a payload hash, a small result, and
  timing. It does not store transcript or greeting text: a reply result holds
  only its status flags, and a call result holds only its status and ring
  identifiers.

Reconnect rules:

- A network reconnect within the same process keeps the call identity and event
  sequence. The connector does not end the call on a transient disconnect.
- Requests are bound to the socket they arrived on. A response from an old
  socket is never sent on a replacement one, and a transport loss cancels the
  waiting requests without giving up the call the pair still owns.
- After a laptop restart, the old call is over. Old turn replies are rejected
  and a new call must be requested explicitly.
- Reconnection never creates a new host model session; the cooperative adapter
  only waits for commands in the session the host already owns.
- On revocation, only that pair's call ends and its queued commands are
  discarded. A pair revoked while the laptop was offline ends its retained call
  when it next authenticates, and then stops reconnecting.

## What the live test covered

A live test on one Mac used a stand-in for `ssh`. The stand-in ran the server
commands locally, and it forwarded the tunnel port with a small Python
forwarder. The test showed these results:

- `remote-connect` paired the laptop. The credential was not in its output.
- The app opened the tunnel, and the connector connected through it.
- A remote call rang, was answered, and carried `listen` and `reply` text.
- After the tunnel process was killed during the call, the app started it
  again, and the connector connected again. The call continued.
- `--remote end` ended the call.
- After `SIGTERM`, the app left no `ssh` process, and `remote-up` left no relay
  process.

These items still need a live check:

- A real `sshd`, with a real key, a host key prompt, and a key that fails.
- A real laptop sleep and a network change.
- A real systemd user service on Linux, and linger.
- A real wss connection that verifies the proxy certificate.
- Revocation that closes both connections and survives a relay restart.
- A dropped connection after a `call` or `reply` returns unknown and does not
  ring or speak twice on a retry.

## Related

- [Agent support](AGENT_SUPPORT.md)
- [Current context](notes/CONTEXT.md)
- [Call skill](../skills/talktome/SKILL.md)
