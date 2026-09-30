"""The link to the talktome app: one JSON object per line on stdin and stdout.

The messages use the relay protocol's names, seen from the agent's side. The
app is the hub, so there are no sessions, acknowledgements, or resends: when
the link breaks, the server stops, and the app starts it again.
"""

import asyncio
import json
import sys


class Link:
    def __init__(self, reader: asyncio.StreamReader, write):
        self._reader = reader
        self._write = write  # takes one line of bytes
        self._lock = asyncio.Lock()

    async def send(self, kind: str, **fields) -> None:
        line = json.dumps({"type": kind, **fields}, separators=(",", ":")) + "\n"
        async with self._lock:
            await self._write(line.encode())

    async def frames(self):
        while True:
            line = await self._reader.readline()
            if not line:
                return
            try:
                frame = json.loads(line)
            except ValueError:
                continue
            if isinstance(frame, dict) and isinstance(frame.get("type"), str):
                yield frame


async def stdio_link() -> Link:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=1 << 20)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    transport, protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
    writer = asyncio.StreamWriter(transport, protocol, None, loop)

    async def write(data: bytes) -> None:
        writer.write(data)
        await writer.drain()

    return Link(reader, write)
