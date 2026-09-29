"""The `talktome` command, as an agent sees it.

`talktome call` is the whole agent-facing surface: an agent that wants to be talked
to runs it, with its own session and its own opening line. The other commands are
for the desktop shell and for people debugging a setup.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import httpx

from . import inbox
from .config import announce_server, base_url, data_dir, get_token, server_up

# How long to wait for a sleeping app to wake up and answer. The app has to start
# Electron, spawn the server, and load the speech engine, so this is generous: the
# user is waiting for a call, not for a command to return.
WAKE_TIMEOUT = 25

# How long to wait for the app to answer a request. A call is not answered until
# the ring is, and a ring lasts about ten seconds, so this covers the wait at the
# far end as well as the round trip.
REQUEST_TIMEOUT = 40


def running(timeout=2):
    """Whether the app's server is answering on the loopback interface."""
    try:
        return httpx.get(f"{base_url()}/v1/health", timeout=timeout).status_code == 200
    except httpx.RequestError:
        return False


def wake(launcher=None, timeout=WAKE_TIMEOUT, sleep=time.sleep, check=running, up=server_up):
    """Start the app if it is closed, and say whether it is now up.

    Whether a command can *reach* the app is no longer the question. Inside a
    sandbox it never can, however plainly the app is running, so asking the
    network whether to start one produced a second copy and a port collision —
    which is what the user ended up reading about. What matters is whether a
    server process is alive, and that is a lock the process holds rather than a
    request it answers.

    The launcher is written into the command when the app installs it, because
    only the app knows whether it is a bundle or a checkout. It is started
    detached and without focus: the ring is what asks for attention, not the
    window.
    """
    if up():
        return True
    command = launcher or os.environ.get("TALKTOME_LAUNCH")
    if not command:
        return False
    try:
        subprocess.Popen(
            shlex.split(command),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ValueError):
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if up() or check():
            return True
        sleep(0.4)
    return False


def ask(
    command,
    payload=None,
    timeout=None,
    sleep=time.sleep,
    start=True,
    launcher=None,
):
    """Leave a request for the app and wait for its answer.

    The request is written *before* the app is started rather than after, because
    the app reads its inbox as it comes up. A command that has to wake a sleeping
    app then depends on nothing but the note being there, instead of winning a
    race against a health check it could not pass anyway.

    Where the note goes is decided by trying. An agent's commands run in a sandbox
    that allows writes to the workspace and the temporary folder and nowhere else,
    so the app's own folder is refused there and `/tmp` is not.
    """
    timeout = REQUEST_TIMEOUT if timeout is None else timeout
    request = inbox.ask(command, payload)
    try:
        if start and not wake(launcher):
            raise ValueError(
                "TalkToMe is not running, and this command could not start it. Open "
                "the desktop app, then try again."
            )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reply = inbox.reply_for(request)
            if reply is not None:
                if reply.get("ok"):
                    return reply.get("result") or {}
                raise ValueError(reply.get("error") or "TalkToMe refused that request.")
            sleep(0.2)
        # The note survived being read, so the app is up but not watching its
        # inbox: an older build, or one that stopped reading.
        raise ValueError(
            "TalkToMe is running but did not answer. Restart the desktop app so it "
            "picks up this version."
        )
    finally:
        inbox.collect(request)


def call(thread, greeting, cwd, name=None, wait=True, agent="codex", connection="auto"):
    """Ask the running app to ring on an existing session.

    The answer comes back with the request. The app is the one that can see
    whether the ring was taken, so it does the waiting and says which of the two
    happened; the command no longer polls for a state it cannot see.
    """
    return ask(
        "call",
        {
            "thread": thread,
            "cwd": cwd,
            "greeting": greeting,
            "name": name,
            "wait": wait,
            "agent": agent,
            "connection": connection,
        },
    )


def end():
    """End whatever call is live. Safe to run when none is.

    Nothing is started here. A call cannot exist without the app, so waking a
    sleeping app to end one would be theatre — this is the one request where
    doing nothing is the right answer.
    """
    if not server_up() and not running():
        return {"status": "idle"}
    return ask("end", {}, start=False)


# Remote-bridge commands route to `talktome.remote.cli`. They are kept out of the
# default path so a local call never imports the relay or WebSocket stack.
REMOTE_BRIDGE_COMMANDS = frozenset(
    {
        "remote-setup",
        "remote-status",
        "remote-remove",
        "remote-daemon",
        "connector-setup",
        "connector-status",
        "connector-remove",
        "relay-pair",
        "relay-list",
        "relay-revoke",
        "relay-serve",
        "remote-init",
        "remote-up",
        "remote-connect",
        "remote-service",
    }
)


def main():
    parser = argparse.ArgumentParser(prog="talktome", description="Start the local speech server.")
    parser.add_argument(
        "command",
        choices=[
            "serve",
            "token",
            "connection",
            "call",
            "end",
            "providers",
            "listen",
            "reply",
            "configure-agent",
            "skill",
            *sorted(REMOTE_BRIDGE_COMMANDS),
        ],
        default="serve",
        nargs="?",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="For remote-connect, the server as user@host. For remote-service, install, remove, or status.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--agent", choices=["codex", "claude", "hermes", "openclaw", "generic"], default="codex")
    parser.add_argument("--connection", choices=["auto", "cooperative"], default="auto")
    parser.add_argument("--after", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--call-id")
    parser.add_argument("--turn-id")
    parser.add_argument("--item-id")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text")
    source.add_argument("--text-file")
    parser.add_argument("--progress", action="store_true", help="Send a reply without ending the voice turn.")
    parser.add_argument("--host-url")
    parser.add_argument("--token-stdin", action="store_true", help="Read the host token from standard input.")
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Route call, listen, reply, and end through the remote bridge daemon.",
    )
    parser.add_argument("--relay", help="The relay WebSocket URL for remote setup.")
    parser.add_argument("--pair", help="The public pair identifier.")
    parser.add_argument("--label", help="An optional label for a pair.")
    parser.add_argument(
        "--code-stdin", action="store_true", help="Read the agent pairing code from standard input."
    )
    parser.add_argument(
        "--credential-stdin",
        action="store_true",
        help="Read the laptop credential from standard input.",
    )
    parser.add_argument(
        "--request-id",
        help="Reuse a request ID to retry one remote operation without running it twice.",
    )
    parser.add_argument("--relay-host", default="127.0.0.1", help="Relay bind address.")
    parser.add_argument("--relay-port", type=int, default=8766, help="Relay bind port.")
    parser.add_argument("--relay-file", help="Override the relay pair metadata file.")
    parser.add_argument(
        "--ssh-host",
        help="How the laptop reaches the server over SSH, as user@host, for remote-init and connector-setup.",
    )
    parser.add_argument("--ssh-port", type=int, help="The SSH port of the server, when it is not 22.")
    parser.add_argument(
        "--remote-command",
        help="How to run talktome on the server, for remote-connect. Defaults to talktome.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Revoke the server's old pair and make a new one, for remote-init and remote-connect.",
    )
    parser.add_argument(
        "--install-service",
        action="store_true",
        help="Also install the remote-up service on the server, for remote-connect.",
    )
    parser.add_argument("--json", action="store_true", help="Print one JSON line, for remote-init.")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Let the relay bind a non-loopback address. It has no TLS, so use a TLS proxy.",
    )
    parser.add_argument(
        "--thread",
        help="The host session ID, gateway session key, or cooperative connection ID.",
    )
    parser.add_argument(
        "--greeting",
        help="The first thing the user hears. Write it as speech, not as a summary.",
    )
    parser.add_argument(
        "--cwd",
        help="The project folder of the session. Defaults to the current folder.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Return as soon as it rings instead of waiting to see whether it is answered.",
    )
    parser.add_argument(
        "--name",
        help="What the user sees while the call is ringing. Defaults to the project folder name.",
    )
    args = parser.parse_args()
    if args.target and args.command not in {"remote-connect", "remote-service"}:
        parser.error(f"unrecognized arguments: {args.target}")

    if args.remote or args.command in REMOTE_BRIDGE_COMMANDS:
        from .remote.cli import run as remote_run

        raise SystemExit(remote_run(args, parser))

    if args.command == "skill":
        from .agents import skill_source

        print(skill_source().read_text(encoding="utf-8"))
    elif args.command == "token":
        print(get_token())
    elif args.command == "connection":
        print(json.dumps({"url": base_url(), "data_dir": str(data_dir())}, indent=2))
    elif args.command == "call":
        if not args.thread:
            print(
                "Supply --thread with the host session ID or a unique cooperative connection ID.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        try:
            result = call(
                args.thread,
                args.greeting,
                args.cwd or os.getcwd(),
                args.name,
                wait=not args.no_wait,
                agent=args.agent,
                connection=args.connection,
            )
        except ValueError as exc:
            # A skill tells the agent to report this in one sentence rather than
            # retry, so the message has to be readable and the exit code non-zero.
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, indent=2))
    elif args.command in {"providers", "listen", "reply", "configure-agent"}:
        payload = {}
        if args.command in {"listen", "reply"}:
            if not args.thread or len(args.thread) > 512:
                parser.error("Supply --thread with a session ID of at most 512 characters.")
            payload["thread"] = args.thread
        if args.command == "listen":
            if not 0 <= args.timeout <= 25 or args.after < 0:
                parser.error("Use --timeout from 0 to 25 and a non-negative --after value.")
            payload.update(after=args.after, timeout=args.timeout)
        elif args.command == "reply":
            if not all([args.call_id, args.turn_id, args.item_id]):
                parser.error("Supply --call-id, --turn-id, and --item-id.")
            if args.text is None and args.text_file is None:
                parser.error("Supply --text or --text-file.")
            try:
                text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else args.text
            except OSError as exc:
                parser.error(str(exc))
            if not text.strip() or len(text) > 16000 or len(args.item_id) > 128:
                parser.error("Use 1 to 16000 text characters and an item ID of at most 128 characters.")
            payload.update(call_id=args.call_id, turn_id=args.turn_id, item_id=args.item_id,
                           text=text, final=not args.progress)
        elif args.command == "configure-agent":
            if args.agent not in {"hermes", "openclaw"} or not args.host_url or not args.token_stdin:
                parser.error("Supply --agent hermes or openclaw, --host-url, and --token-stdin.")
            token = sys.stdin.read(8193).strip()
            if not token or len(token) > 8192:
                parser.error("Supply a host token of at most 8192 characters through standard input.")
            payload.update(agent=args.agent, url=args.host_url, token=token)
        try:
            result = ask(args.command, payload, timeout=max(REQUEST_TIMEOUT, args.timeout + 5))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, indent=2))
    elif args.command == "end":
        try:
            result = end()
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, indent=2))
    else:
        # TALKTOME_RELOAD=1 restarts the server when a Python file changes, so a
        # backend edit does not need a full app restart. Development only.
        import uvicorn

        reload_enabled = os.environ.get("TALKTOME_RELOAD") == "1"
        # Held for as long as this process is listening, so a command can tell the
        # app is up without asking the network — which, inside a sandbox, tells it
        # nothing. See `wake`.
        with announce_server():
            uvicorn.run(
                "talktome.app:create_app",
                factory=True,
                host="127.0.0.1",
                port=args.port,
                access_log=False,
                reload=reload_enabled,
                reload_dirs=[str(Path(__file__).resolve().parent)] if reload_enabled else None,
            )


if __name__ == "__main__":
    main()
