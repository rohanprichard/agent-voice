"""The server process: the link to the app, the local API, and the targets."""

import asyncio
import contextlib
import logging
import os
import platform
import socket
import sys
import time
from pathlib import Path

from . import __version__, paths
from .api import Api, Client
from .calls import Caller
from .inbound import Inbound

log = logging.getLogger("talktome")

TARGETS_EVERY = 60.0


async def take_over(path: Path) -> None:
    """Newest connection wins: ask a server that is already running to stop."""
    client = Client(path)
    if not client.running():
        return
    log.info("another talktome server is running; asking it to stop")
    # It may close the connection as it stops.
    with contextlib.suppress(Exception):
        await asyncio.to_thread(client.request, "POST", "/v1/quit", {}, 5)
    for _ in range(50):
        if not path.exists():
            return
        await asyncio.sleep(0.1)


async def serve(
    link, home: Path | None = None, socket_path: Path | None = None, new_runner=None, approver: str = ""
) -> None:
    home = home or Path.home()
    socket_path = socket_path or paths.socket_path()
    caller = Caller(link)
    extra = {"new_runner": new_runner} if new_runner else {}
    inbound = Inbound(link, home, approver or os.path.abspath(sys.argv[0]), **extra)
    name = socket.gethostname().removesuffix(".local")

    def status() -> dict:
        return {"name": name, "version": __version__, "connected": True}

    await take_over(socket_path)
    api = Api(caller, inbound, status)
    server = await api.serve(socket_path)
    await link.send("hello", name=name, version=__version__, platform=platform.system().lower())

    async def publish():
        sent = None
        next_scan = 0.0
        while True:
            now = time.monotonic()
            if inbound.changed.is_set() or now >= next_scan:
                inbound.changed.clear()
                found = [t.wire() for t in await asyncio.to_thread(inbound.discover)]
                if found != sent:
                    await link.send("targets", targets=found)
                    sent = found
                next_scan = now + TARGETS_EVERY
            try:
                await asyncio.wait_for(inbound.changed.wait(), max(next_scan - time.monotonic(), 0.1))
            except TimeoutError:
                pass

    async def read():
        async for frame in link.frames():
            if caller.owns(frame.get("call_id", "")):
                caller.dispatch(frame)
            else:
                inbound.dispatch(frame)

    publishing = asyncio.create_task(publish())
    reading = asyncio.create_task(read())
    quitting = asyncio.create_task(api.quit.wait())
    try:
        await asyncio.wait({reading, quitting}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (publishing, reading, quitting, *inbound.tasks):
            task.cancel()
        server.close()
        socket_path.unlink(missing_ok=True)
