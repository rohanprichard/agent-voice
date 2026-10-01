import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from talktome_server import inbound, paths, targets
from talktome_server.api import Client
from talktome_server.link import Link
from talktome_server.server import serve


class FakeApp:
    """The app's side of the link: it reads what the server sends, and sends frames back."""

    def __init__(self):
        self.reader = asyncio.StreamReader()
        self.sent: asyncio.Queue = asyncio.Queue()
        self.link = Link(self.reader, self._receive)

    async def _receive(self, line: bytes) -> None:
        await self.sent.put(json.loads(line))

    def send(self, kind: str, **fields) -> None:
        self.reader.feed_data((json.dumps({"type": kind, **fields}) + "\n").encode())

    def close(self) -> None:
        self.reader.feed_eof()

    async def next(self, kind: str, timeout: float = 5) -> dict:
        async def find():
            while True:
                frame = await self.sent.get()
                if frame["type"] == kind:
                    return frame

        return await asyncio.wait_for(find(), timeout)


class World:
    def __init__(self, home: Path, socket_path: Path, app: FakeApp):
        self.home, self.socket_path, self.app = home, socket_path, app
        self.client = Client(socket_path)

    async def post(self, route: str, body: dict, timeout: float = 30) -> dict:
        return await asyncio.to_thread(self.client.request, "POST", route, body, timeout)


@pytest.fixture
async def world(monkeypatch, tmp_path):
    # A Unix socket path must be short, and pytest's tmp_path is not.
    short = Path(tempfile.mkdtemp(prefix="tt-", dir="/tmp"))
    monkeypatch.setenv("TALKTOME_DIR", str(short))
    monkeypatch.setattr(inbound, "PROGRESS_AFTER", 3600)
    monkeypatch.setattr(targets, "TEMP_ROOTS", [])
    home = tmp_path / "home"
    home.mkdir()
    app = FakeApp()
    runners = {}
    task = asyncio.create_task(
        serve(app.link, home=home, socket_path=paths.socket_path(), new_runner=lambda *a: runners["make"](*a))
    )
    w = World(home, paths.socket_path(), app)
    w.runners = runners
    await app.next("hello")
    yield w
    app.close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    shutil.rmtree(short, ignore_errors=True)
