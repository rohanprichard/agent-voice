"""The SSH tunnel the laptop connector opens to a relay on the server.

The relay binds loopback on the server and serves plain ``ws``. SSH carries
that connection and encrypts it, so the relay needs no TLS and is never open to
the network. The tunnel is a child of the app server: it starts with the
connector, restarts when ssh exits, and stops with the app.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import signal
import socket
import time
from collections import deque

logger = logging.getLogger(__name__)

MIN_BACKOFF = 1.0
MAX_BACKOFF = 60.0
STABLE_AFTER = 30.0
READY_TIMEOUT = 30.0
STOP_TIMEOUT = 5.0

# ssh runs under a small sh watchdog that holds a pipe from this process. If
# this process dies, even by SIGKILL, the pipe closes and the watchdog stops
# ssh, so a killed app never leaves a tunnel behind.
WATCHDOG = """
exec 3<&0
"$@" </dev/null 3<&- &
child=$!
( read -r _ <&3; kill -TERM "$child" 2>/dev/null ) &
watch=$!
trap 'kill -TERM "$child" 2>/dev/null' TERM INT HUP
wait "$child"
status=$?
wait "$child" 2>/dev/null
kill -TERM "$watch" 2>/dev/null
exit "$status"
"""


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # ssh binds its listener with SO_REUSEADDR too, so a port with only
        # closed connections in TIME_WAIT still counts as free.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def explain(target: str, lines) -> str:
    """Turn the last ssh error lines into one sentence a person can act on."""
    text = "\n".join(lines)
    if "Permission denied" in text or "Too many authentication failures" in text:
        return (
            f"SSH could not log in to {target} with a key. Make sure `ssh {target}` "
            "works in a terminal without a password prompt."
        )
    if "Host key verification failed" in text:
        return (
            f"SSH does not know the host key of {target}. Run `ssh {target}` once in "
            "a terminal and accept the key."
        )
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in text:
        return f"The host key of {target} changed. Examine it before you trust it again."
    last = next((line for line in reversed(lines) if line.strip()), "")
    return f"The SSH tunnel to {target} stopped: {last}" if last else f"The SSH tunnel to {target} stopped."


class SSHTunnel:
    def __init__(
        self,
        target: str,
        remote_port: int,
        local_port: int,
        ssh_port: int | None = None,
        ssh: str | None = None,
    ):
        self.target = target
        self.remote_port = remote_port
        self.wanted_port = local_port
        self.local_port = local_port
        self.ssh_port = ssh_port
        self.ssh = ssh
        self.ready = asyncio.Event()
        self.state = "starting"
        self.error: str | None = None
        self.starts = 0
        self._process = None
        self._stopped = False
        self._stderr: deque[str] = deque(maxlen=20)

    def status(self) -> dict:
        return {
            "target": self.target,
            "state": self.state,
            "local_port": self.local_port,
            "remote_port": self.remote_port,
            "starts": self.starts,
            "error": self.error,
        }

    def command(self) -> list[str]:
        command = [
            self.ssh or "ssh",
            "-N",
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-L", f"127.0.0.1:{self.local_port}:127.0.0.1:{self.remote_port}",
        ]
        if self.ssh_port:
            command += ["-p", str(self.ssh_port)]
        return command + ["--", self.target]

    async def run(self) -> None:
        backoff = MIN_BACKOFF
        try:
            while not self._stopped:
                started = time.monotonic()
                await self._run_once()
                if self._stopped:
                    break
                if time.monotonic() - started >= STABLE_AFTER:
                    backoff = MIN_BACKOFF
                await asyncio.sleep(backoff * (0.8 + random.random() * 0.4))
                backoff = min(backoff * 2, MAX_BACKOFF)
        finally:
            await self.stop()

    async def _run_once(self) -> None:
        if self.ssh is None:
            from ..agents import find_command

            self.ssh = await asyncio.to_thread(find_command, "ssh")
            if self.ssh is None:
                self._fail("The ssh command was not found on this Mac.")
                return
        if not port_free(self.local_port):
            # Another program took the port. Any free port works, because the
            # connector reads the port from this tunnel and nothing else does.
            chosen = self.wanted_port if port_free(self.wanted_port) else free_port()
            logger.warning("Local port %s is busy, so the SSH tunnel uses port %s.", self.local_port, chosen)
            self.local_port = chosen
        self.starts += 1
        self.state = "starting"
        self._stderr.clear()
        logger.info("Starting the SSH tunnel to %s on local port %s.", self.target, self.local_port)
        try:
            self._process = await asyncio.create_subprocess_exec(
                "/bin/sh", "-c", WATCHDOG, "talktome-tunnel", *self.command(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            self._fail(f"The SSH tunnel could not start: {exc}")
            return
        process = self._process
        reader = asyncio.create_task(self._read_stderr(process))
        timed_out = False
        try:
            ready = await self._wait_ready(process)
            if ready is None:
                timed_out = True
                await self._terminate(process)
            elif ready:
                self.state = "up"
                self.error = None
                self.ready.set()
                logger.info("The SSH tunnel to %s is up.", self.target)
            await process.wait()
        finally:
            self.ready.clear()
            # On a cancel, ssh still runs and holds its stderr open, so the
            # reader ends only after ssh stops.
            await self._terminate(process)
            await asyncio.gather(reader, return_exceptions=True)
        if self._stopped:
            return
        if timed_out:
            self._fail(f"SSH to {self.target} did not open the tunnel in {READY_TIMEOUT:.0f} seconds.")
        else:
            self._fail(explain(self.target, list(self._stderr)))

    async def _wait_ready(self, process) -> bool | None:
        """True when the local port answers, False when ssh exits, None on timeout."""
        deadline = time.monotonic() + READY_TIMEOUT
        while process.returncode is None and time.monotonic() < deadline:
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", self.local_port)
            except OSError:
                await asyncio.sleep(0.2)
                continue
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return process.returncode is None
        return None if process.returncode is None else False

    async def _read_stderr(self, process) -> None:
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                self._stderr.append(text)
                logger.info("ssh: %s", text)

    def _fail(self, message: str) -> None:
        self.state = "down"
        self.error = message
        logger.warning(message)

    async def _terminate(self, process) -> None:
        if process.returncode is not None:
            return
        if process.stdin is not None:
            process.stdin.close()
        # The watchdog leads its own process group, so one signal reaches it,
        # ssh, and the pipe watcher together.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), STOP_TIMEOUT)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()

    async def stop(self) -> None:
        self._stopped = True
        self.ready.clear()
        self.state = "stopped"
        if self._process is not None:
            await self._terminate(self._process)
