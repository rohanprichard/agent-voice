"""Command routing for the remote bridge.

Local behavior is untouched. Remote mode is selected with ``--remote`` and only
carries the four cooperative operations. Setup, status, and removal commands
are narrow and local to the machine they run on:

* ``remote-*`` configure the agent server and its daemon.
* ``connector-*`` configure the laptop's opt-in connector.
* ``relay-*`` administer the relay host's private pair file.

Credentials are read from standard input, never from a command argument, and a
setup command prints only a summary without the secret.
"""

from __future__ import annotations

import getpass
import json
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import config as remote_config
from . import inbox, protocol
from .credentials import MAX_CREDENTIAL
from .relay import RelayStore, serve_relay

REMOTE_COMMANDS = frozenset({"call", "listen", "reply", "end"})

WAIT_TIMEOUT = {"call": 60.0, "reply": 40.0, "end": 30.0}
WAIT_POLL = 0.1


def run(args, parser) -> int:
    if args.remote:
        return _remote_command(args, parser)
    handlers = {
        "remote-setup": _agent_setup,
        "remote-status": _agent_status,
        "remote-remove": _agent_remove,
        "remote-daemon": _agent_daemon,
        "connector-setup": _laptop_setup,
        "connector-status": _laptop_status,
        "connector-remove": _laptop_remove,
        "relay-pair": _relay_pair,
        "relay-list": _relay_list,
        "relay-revoke": _relay_revoke,
        "relay-serve": _relay_serve,
        "remote-init": _remote_init,
        "remote-up": _remote_up,
        "remote-connect": _remote_connect,
        "remote-service": _remote_service,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.error("Use --remote with call, listen, reply, or end.")
    return handler(args, parser)


def _remote_command(args, parser) -> int:
    if args.command not in REMOTE_COMMANDS:
        parser.error("Use --remote with call, listen, reply, or end.")
    payload = _payload(args, parser)
    if args.request_id:
        if not protocol.valid_request_id(args.request_id):
            parser.error("Use --request-id in the generated bridge format.")
        request_id = args.request_id
    else:
        request_id = protocol.make_request_id()
    try:
        request = inbox.ask(args.command, payload, request_id=request_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        reply = _wait_for_reply(request, _wait_timeout(args))
    finally:
        inbox.collect(request)
    if reply is None:
        print(
            "The remote daemon did not answer. Start it with `talktome remote-daemon` "
            "on the agent server.",
            file=sys.stderr,
        )
        return 1
    if not reply.get("ok"):
        print(str(reply.get("error") or "The bridge refused that request."), file=sys.stderr)
        return 1
    print(json.dumps(reply.get("result") or {}, indent=2, sort_keys=True))
    return 0


def _wait_for_reply(request, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = inbox.reply_for(request)
        if reply is not None:
            return reply
        time.sleep(WAIT_POLL)
    return None


def _wait_timeout(args) -> float:
    if args.command == "listen":
        return float(args.timeout) + 30.0
    return WAIT_TIMEOUT[args.command]


def _payload(args, parser) -> dict:
    if args.command == "end":
        return {}
    thread = (args.thread or "").strip()
    if not thread or len(thread) > protocol.MAX_THREAD:
        parser.error(f"Supply --thread with a connection ID of at most {protocol.MAX_THREAD} characters.")
    if args.command == "call":
        return {
            "thread": thread,
            "greeting": (args.greeting or "")[: protocol.MAX_GREETING],
            "name": (args.name or "")[: protocol.MAX_NAME],
            "agent": args.agent,
            "wait": not args.no_wait,
        }
    if args.command == "listen":
        if not 0 <= args.timeout <= protocol.MAX_LISTEN_TIMEOUT or args.after < 0:
            parser.error(
                f"Use --timeout from 0 to {protocol.MAX_LISTEN_TIMEOUT} and a non-negative --after."
            )
        return {"thread": thread, "after": args.after, "timeout": args.timeout}
    if args.command == "reply":
        if not all([args.call_id, args.turn_id, args.item_id]):
            parser.error("Supply --call-id, --turn-id, and --item-id.")
        if args.text is None and args.text_file is None:
            parser.error("Supply --text or --text-file.")
        try:
            text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else args.text
        except OSError as exc:
            parser.error(str(exc))
        if not text.strip() or len(text) > protocol.MAX_TEXT or len(args.item_id) > protocol.MAX_ITEM_ID:
            parser.error(
                f"Use 1 to {protocol.MAX_TEXT} text characters and an item ID of at most "
                f"{protocol.MAX_ITEM_ID} characters."
            )
        return {
            "thread": thread,
            "call_id": args.call_id,
            "turn_id": args.turn_id,
            "item_id": args.item_id,
            "text": text,
            "final": not args.progress,
        }
    parser.error("Use --remote with call, listen, reply, or end.")


def _read_secret(parser, provided: bool, flag: str, label: str, maximum: int) -> str:
    if not provided:
        parser.error(f"Pass {flag} and give the {label} on standard input.")
    # A person at a terminal pastes the secret at a hidden prompt, so it is not
    # echoed and does not land in the shell history as a printf command.
    if sys.stdin.isatty():
        value = getpass.getpass(f"Paste the {label}: ").strip()
    else:
        value = sys.stdin.read(maximum + 1).strip()
    if not value or len(value) > maximum:
        parser.error(f"Supply a {label} of at most {maximum} characters through standard input.")
    return value


def _agent_setup(args, parser) -> int:
    if not args.relay or not args.pair:
        parser.error("Supply --relay and --pair.")
    code = _read_secret(parser, args.code_stdin, "--code-stdin", "pairing code", MAX_CREDENTIAL)
    try:
        summary = remote_config.save_agent_config(args.relay, args.pair, code, args.label or "")
    except remote_config.RemoteConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(remote_config.json_text({**summary, "saved": True}))
    print("Start the bridge with `talktome remote-daemon`.", file=sys.stderr)
    return 0


def _agent_status(args, parser) -> int:
    try:
        config = remote_config.load_agent_config()
    except remote_config.RemoteConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(remote_config.json_text(remote_config.describe(config)))
    print(f"inbox: {inbox.folder()}", file=sys.stderr)
    print(f"fallback inbox: {inbox.shared()}", file=sys.stderr)
    return 0


def _agent_daemon(args, parser) -> int:
    from .daemon import run_daemon

    return run_daemon()


def _laptop_setup(args, parser) -> int:
    if not args.relay or not args.pair:
        parser.error("Supply --relay and --pair.")
    credential = _read_secret(
        parser, args.credential_stdin, "--credential-stdin", "laptop credential", MAX_CREDENTIAL
    )
    ssh = None
    if args.ssh_host:
        # The relay URL is the laptop end of the tunnel, and the relay uses the
        # same port on the server.
        port = urlsplit(args.relay).port
        ssh = {"target": args.ssh_host, "port": args.ssh_port, "remote_port": port}
    try:
        summary = remote_config.save_laptop_config(
            args.relay, args.pair, credential, args.label or "", ssh=ssh
        )
    except remote_config.RemoteConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(remote_config.json_text({**summary, "saved": True}))
    print("Restart the TalkToMe app so the connector reads the new configuration.", file=sys.stderr)
    return 0


def _laptop_status(args, parser) -> int:
    try:
        config = remote_config.load_laptop_config()
    except remote_config.RemoteConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    summary = remote_config.describe(config)
    if config:
        summary["connector"] = _running_connector()
    print(remote_config.json_text(summary))
    return 0


def _running_connector() -> dict:
    """What the connector in the running app reports, such as an SSH error."""
    import httpx

    from ..config import base_url, get_token

    try:
        response = httpx.get(
            f"{base_url()}/v1/remote",
            headers={"Authorization": f"Bearer {get_token()}"},
            timeout=3,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        return {"running": False, "note": "TalkToMe is not running, or it is an older version."}


def _laptop_remove(args, parser) -> int:
    removed = remote_config.remove_laptop_config()
    print(json.dumps({"removed": removed}, indent=2))
    print("Restart the TalkToMe app so the connector stops.", file=sys.stderr)
    return 0


def _store(args) -> RelayStore:
    path = Path(args.relay_file).expanduser() if args.relay_file else None
    return RelayStore(path)


def _relay_pair(args, parser) -> int:
    try:
        pair = _store(args).create_pair(args.label or "")
    except (OSError, ValueError) as exc:
        print(f"The pair could not be created: {exc}", file=sys.stderr)
        return 1
    print(remote_config.json_text(pair))
    print(
        "Copy the agent pairing code to the server and the laptop credential into the "
        "laptop connector. This is the only time either is shown.",
        file=sys.stderr,
    )
    return 0


def _relay_list(args, parser) -> int:
    try:
        pairs = _store(args).list_pairs()
    except (OSError, ValueError) as exc:
        print(f"The relay file could not be read: {exc}", file=sys.stderr)
        return 1
    print(remote_config.json_text({"pairs": pairs}))
    return 0


def _relay_revoke(args, parser) -> int:
    if not args.pair:
        parser.error("Supply --pair with the pair to revoke.")
    try:
        revoked = _store(args).revoke_pair(args.pair)
    except (OSError, ValueError) as exc:
        print(f"The pair could not be revoked: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"pair": args.pair, "revoked": revoked}, indent=2))
    return 0 if revoked else 1


def _relay_serve(args, parser) -> int:
    path = Path(args.relay_file).expanduser() if args.relay_file else None
    try:
        serve_relay(
            args.relay_host,
            args.relay_port,
            path,
            allow_network=getattr(args, "allow_network", False),
        )
    except (OSError, ValueError) as exc:
        print(f"The relay could not start: {exc}", file=sys.stderr)
        return 1
    return 0


# remote-init runs its own relay on this address. Other loopback forms, such as
# ::1, would make the relay, the daemon, and the SSH tunnel disagree.
MANAGED_RELAY_HOSTS = {"127.0.0.1", "localhost"}


def _init_relay_url(args) -> str:
    relay = remote_config.websocket_url(args.relay or f"ws://127.0.0.1:{args.relay_port}")
    url = urlsplit(relay)
    if url.scheme == "wss":
        return relay
    if url.hostname not in MANAGED_RELAY_HOSTS:
        raise remote_config.RemoteConfigError(
            "remote-init runs its relay on 127.0.0.1. Use ws://127.0.0.1:PORT or a wss:// URL."
        )
    return f"ws://127.0.0.1:{url.port or args.relay_port}{url.path}"


def _saved_pair() -> tuple[bool, str | None]:
    """Whether an agent configuration exists, and its pair, even when it does not load."""
    path = remote_config.agent_config_path()
    if not path.is_file():
        return False, None
    try:
        return True, remote_config.load_agent_config()["pair"]
    except (remote_config.RemoteConfigError, OSError, ValueError):
        pass
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True, None
    pair = document.get("pair") if isinstance(document, dict) else None
    return True, pair if isinstance(pair, str) else None


def _revoke_local(args, pair: str | None) -> bool:
    """Revoke a pair in this host's relay file, when this host is its relay."""
    if not pair:
        return False
    try:
        return _store(args).revoke_pair(pair)
    except (OSError, ValueError):
        return False


def _agent_remove(args, parser) -> int:
    _, pair = _saved_pair()
    # A removed configuration must not leave its laptop credential valid.
    revoked = _revoke_local(args, pair)
    removed = remote_config.remove_agent_config()
    print(json.dumps({"removed": removed, "pair": pair, "revoked": revoked}, indent=2))
    if pair and not revoked:
        print(
            f"The pair {pair} is not in this server's relay file. Run "
            f"`talktome relay-revoke --pair {pair}` on its relay host.",
            file=sys.stderr,
        )
    return 0


def _remote_init(args, parser) -> int:
    """Set up this server as both relay host and agent server, in one step.

    The relay binds loopback here, and the laptop reaches it through an SSH
    tunnel. SSH gives the encryption, so no TLS proxy is needed, and the relay
    is never open to the network.
    """
    exists, old_pair = _saved_pair()
    if exists and not args.replace:
        if args.json:
            print(json.dumps({"error": "configured", "pair": old_pair}))
        print(
            "This server already has a remote configuration"
            + (f" for pair {old_pair}" if old_pair else "")
            + ". Run `talktome remote-init --replace` to revoke that pair and make a new one.",
            file=sys.stderr,
        )
        return 1
    try:
        relay = _init_relay_url(args)
    except remote_config.RemoteConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if exists:
        if _revoke_local(args, old_pair):
            print(f"Revoked the old pair {old_pair}.", file=sys.stderr)
        elif old_pair:
            print(
                f"The old pair {old_pair} is not in this server's relay file. Revoke it on its relay host.",
                file=sys.stderr,
            )
        remote_config.remove_agent_config()
    try:
        pair = _store(args).create_pair(args.label or socket.gethostname())
        remote_config.save_agent_config(relay, pair["pair"], pair["agent_credential"], pair["label"])
    except (remote_config.RemoteConfigError, OSError, ValueError) as exc:
        print(f"The remote bridge could not be set up: {exc}", file=sys.stderr)
        return 1
    if args.json:
        # For remote-connect, which reads this over SSH. It is the only output.
        print(
            json.dumps(
                {
                    "pair": pair["pair"],
                    "relay": relay,
                    "label": pair["label"],
                    "laptop_credential": pair["laptop_credential"],
                }
            )
        )
        return 0
    ssh = args.ssh_host or f"{getpass.getuser()}@{socket.gethostname()}"
    url = urlsplit(relay)
    relay_option = f" --relay-file {shlex.quote(args.relay_file)}" if args.relay_file else ""
    lines = [f"This server is ready. Pair: {pair['pair']}", "", "On this server, keep this running:"]
    if url.scheme == "wss":
        lines += [
            (
                f"  talktome relay-serve --relay-port PORT{relay_option}"
                "   (behind the TLS proxy for this URL)"
            ),
            "  talktome remote-daemon",
        ]
        setup = f"talktome connector-setup --relay {relay} --pair {pair['pair']} --credential-stdin"
        restart = "Restart the TalkToMe app."
    else:
        lines += [
            (
                f"  talktome remote-up{relay_option}"
                f"   (or: talktome remote-service install{relay_option})"
            )
        ]
        setup = (
            f"talktome connector-setup --relay {relay} "
            f"--pair {pair['pair']} --ssh-host {ssh} --credential-stdin"
        )
        restart = "Restart the TalkToMe app. It opens the SSH tunnel to this server itself."
    lines += [
        "",
        "On your laptop:",
        "  1. Save the laptop credential. Paste it when the command asks:",
        f"     {setup}",
        "",
        "     Laptop credential (shown only once):",
        f"     {pair['laptop_credential']}",
        "",
        f"  2. {restart}",
        "",
        "Then an agent on this server can ring you with:",
        '  talktome --remote call --agent claude --thread SESSION_ID --greeting "Hey, what would you like to discuss?"',
    ]
    print("\n".join(lines))
    return 0


def _exit_on_signal(signum, frame):
    raise KeyboardInterrupt


class _Relay:
    """The relay child of remote-up. It starts again when it stops."""

    def __init__(self, command: list[str]):
        self.command = command
        self.process = None
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> bool:
        self.process = subprocess.Popen(self.command)
        # Give the relay a moment to bind before the daemon connects. The daemon
        # retries anyway, so this only avoids one noisy first attempt.
        time.sleep(1.5)
        if self.process.poll() is not None:
            return False
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return True

    def _watch(self) -> None:
        backoff = 1.0
        started = time.monotonic()
        while not self._stop.wait(1.0):
            code = self.process.poll()
            if code is None:
                continue
            if time.monotonic() - started > 60:
                backoff = 1.0
            print(f"The relay stopped with code {code}. It starts again in {backoff:.0f} s.", file=sys.stderr)
            if self._stop.wait(backoff):
                return
            started = time.monotonic()
            self.process = subprocess.Popen(self.command)
            backoff = min(backoff * 2, 30.0)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        process = self.process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _remote_up(args, parser) -> int:
    """Run the relay and the daemon together, when the relay lives on this server."""
    try:
        config = remote_config.load_agent_config()
    except remote_config.RemoteConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not config:
        print("Run `talktome remote-init` on this server first.", file=sys.stderr)
        return 1
    url = urlsplit(config["relay"])
    relay = None
    if url.scheme == "ws":
        if url.hostname not in MANAGED_RELAY_HOSTS or not url.port:
            print(
                f"remote-up runs the relay on 127.0.0.1 with a port, and {config['relay']} is not "
                "that. Run `talktome remote-init --replace`.",
                file=sys.stderr,
            )
            return 1
        command = [
            sys.executable, "-m", "talktome", "relay-serve",
            "--relay-host", "127.0.0.1", "--relay-port", str(url.port),
        ]
        if args.relay_file:
            command += ["--relay-file", args.relay_file]
        relay = _Relay(command)
    # A service manager stops this with SIGTERM, and a closed terminal sends
    # SIGHUP. Both must reach the finally block, or the relay child is orphaned.
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on_signal)
    try:
        if relay is not None and not relay.start():
            print("The relay did not start. Its error is above.", file=sys.stderr)
            return 1
        from .daemon import run_daemon

        return run_daemon()
    except KeyboardInterrupt:
        return 0
    finally:
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(signum, signal.SIG_IGN)
        if relay is not None:
            relay.stop()


def _ssh_command() -> str | None:
    from ..agents import find_command

    return find_command("ssh")


def _ssh_args(ssh: str, target: str, ssh_port: int | None, remote: str) -> list[str]:
    command = [ssh]
    if ssh_port:
        command += ["-p", str(ssh_port)]
    # A login shell, so the server's own PATH finds `talktome`. uv tool install
    # puts it in ~/.local/bin, which some login shells do not add.
    return command + ["--", target, "sh -lc " + shlex.quote('PATH="$HOME/.local/bin:$PATH"; ' + remote)]


def _last_json(text: str):
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                document = json.loads(line)
            except ValueError:
                continue
            if isinstance(document, dict):
                return document
    return None


def _remote_connect(args, parser) -> int:
    if not args.target:
        parser.error("Supply the server as user@host, for example: talktome remote-connect me@server")
    try:
        remote_config.ssh_settings(args.target, args.relay_port, args.ssh_port)
    except remote_config.RemoteConfigError as exc:
        parser.error(str(exc))
    ssh = _ssh_command()
    if ssh is None:
        print("The ssh command was not found.", file=sys.stderr)
        return 1
    program = args.remote_command or "talktome"
    label = shlex.quote(args.label or socket.gethostname())
    relay_option = f" --relay-file {shlex.quote(args.relay_file)}" if args.relay_file else ""
    init = f"{program} remote-init --json --relay-port {args.relay_port} --label {label}{relay_option}"
    if args.replace:
        init += " --replace"
    print(f"Setting up {args.target} over SSH.", file=sys.stderr)
    # Not BatchMode: the person may need to accept the host key or type a
    # password. Standard output holds the laptop credential, so it is captured
    # and never shown.
    try:
        result = subprocess.run(
            _ssh_args(ssh, args.target, args.ssh_port, init),
            stdout=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        print(f"ssh could not start: {exc}", file=sys.stderr)
        return 1
    document = _last_json(result.stdout or "")
    if document is not None and document.get("error") == "configured":
        old = document.get("pair") or "OLD_PAIR"
        print(
            f"\n{args.target} already has a remote configuration (pair {old}).\n"
            "To replace it, run this command again with --replace. That revokes the old pair "
            "and makes a new one.\n"
            "Or run this on the server, then run this command again:\n"
            f"  {program} remote-remove{relay_option}\n"
            f"  {program} relay-revoke --pair {shlex.quote(str(old))}{relay_option}"
            "   (only if remote-remove did not revoke it)",
            file=sys.stderr,
        )
        return 1
    if result.returncode != 0 or document is None:
        if result.returncode == 255:
            print(f"SSH could not connect to {args.target}.", file=sys.stderr)
        else:
            print(
                f"remote-init did not finish on {args.target}. Its message is above. If `talktome` "
                "is not on the server's PATH, pass --remote-command with its full path.",
                file=sys.stderr,
            )
        return 1
    try:
        relay = remote_config.websocket_url(str(document.get("relay") or ""))
        url = urlsplit(relay)
        if url.scheme != "ws" or not url.port:
            raise remote_config.RemoteConfigError("The server did not set up a loopback relay.")
        summary = remote_config.save_laptop_config(
            f"ws://127.0.0.1:{url.port}{url.path}",
            str(document.get("pair") or ""),
            str(document.get("laptop_credential") or ""),
            str(document.get("label") or ""),
            ssh={"target": args.target, "port": args.ssh_port, "remote_port": url.port},
        )
    except remote_config.RemoteConfigError as exc:
        print(f"The laptop configuration could not be saved: {exc}", file=sys.stderr)
        return 1
    service = True
    if args.install_service:
        command = f"{program} remote-service install{relay_option}"
        installed = subprocess.run(_ssh_args(ssh, args.target, args.ssh_port, command), check=False)
        service = installed.returncode == 0
        if not service:
            print("The service did not install. Its message is above.", file=sys.stderr)
    print(remote_config.json_text({**summary, "saved": True}))
    lines = ["", f"This laptop is paired with {args.target}. What is left:"]
    lines.append("  1. Restart TalkToMe. It opens the SSH tunnel to the server itself.")
    if args.install_service and service:
        lines.append("  2. Nothing on the server. A service keeps `talktome remote-up` running there.")
    else:
        lines.append(
            f"  2. Keep `{program} remote-up{relay_option}` running on the server, or run "
            f"`{program} remote-service install{relay_option}` there."
        )
        if args.replace:
            lines.append("     If `talktome remote-up` already runs there, restart it.")
    lines.append(
        "SSH must log in to the server with a key and no password prompt, because the app cannot type one."
    )
    print("\n".join(lines), file=sys.stderr)
    return 0 if service else 1


def _remote_service(args, parser) -> int:
    from . import service

    action = args.target or "status"
    if action not in {"install", "remove", "status"}:
        parser.error("Use remote-service install, remove, or status.")
    home = Path.home()
    try:
        if action == "install":
            if not remote_config.agent_config_path().is_file():
                print("Run `talktome remote-init` on this server first.", file=sys.stderr)
                return 1
            notes = service.install(
                service.service_command(args.relay_file),
                service.service_env(),
                home=home,
                log=remote_config.data_root() / "remote-up.log",
            )
            print("\n".join(notes))
        elif action == "remove":
            print(json.dumps({"removed": service.remove(home=home)}, indent=2))
        else:
            print(json.dumps(service.status(home=home), indent=2))
    except (service.ServiceError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
