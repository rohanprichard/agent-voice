"""Talk to the talktome server for the Hermes plugin.

The server runs on this machine while the talktome app is connected to it.
Its local API is HTTP over a Unix socket that only this user can open. This
file has no Hermes imports, so the tests can load it directly.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import re
import socket
import sys
from pathlib import Path

# A call rings for up to 45 seconds and then waits up to 90 for the answer.
CALL_TIMEOUT = 240
TURN_TIMEOUT = 150
SHORT_TIMEOUT = 30


class TalkToMeError(RuntimeError):
    pass


def data_dir(env=os.environ) -> Path:
    """The server's folder. talktome-server uses the same rule."""
    configured = env.get("TALKTOME_DIR")
    if configured:
        return Path(configured)
    home = Path(env.get("HOME") or Path.home())
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "talktome-server"
    base = env.get("XDG_CONFIG_HOME")
    return (Path(base) if base else home / ".config") / "talktome-server"


def socket_path(env=os.environ) -> Path:
    return data_dir(env) / "server.sock"


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("talktome-server", timeout=timeout)
        self._path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


NOT_RUNNING = "The talktome server is not running on this machine. Connect to it from the talktome app."


class LocalClient:
    def __init__(self, path: str | os.PathLike):
        self.path = str(path)

    @classmethod
    def default(cls) -> LocalClient:
        return cls(socket_path())

    def available(self) -> bool:
        return Path(self.path).exists()

    def _request(self, method: str, route: str, body: dict | None, timeout: float) -> dict:
        conn = _UnixConnection(self.path, timeout)
        try:
            data = json.dumps(body).encode() if body is not None else None
            conn.request(method, route, body=data, headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            raw = response.read()
        except (FileNotFoundError, ConnectionRefusedError):
            raise TalkToMeError(NOT_RUNNING) from None
        except OSError as exc:
            raise TalkToMeError(f"The talktome server did not answer: {exc}") from None
        finally:
            conn.close()
        try:
            result = json.loads(raw or b"{}")
        except ValueError:
            raise TalkToMeError("The talktome server sent a reply that is not JSON.") from None
        if response.status != 200:
            raise TalkToMeError(result.get("message") or f"The talktome server failed ({response.status}).")
        return result

    async def _post(self, route: str, body: dict, timeout: float) -> dict:
        return await asyncio.to_thread(self._request, "POST", route, body, timeout)

    async def status(self) -> dict:
        return await asyncio.to_thread(self._request, "GET", "/v1/status", None, SHORT_TIMEOUT)

    async def call(self, reason: str, greeting: str = "", question: str = "", choices=None) -> dict:
        body = {"reason": reason, "greeting": greeting, "question": question, "choices": choices or []}
        return await self._post("/v1/call", body, CALL_TIMEOUT)

    async def turn(self, say: str) -> dict:
        return await self._post("/v1/turn", {"say": say}, TURN_TIMEOUT)

    async def progress(self, say: str) -> bool:
        return bool((await self._post("/v1/progress", {"say": say}, SHORT_TIMEOUT)).get("spoken"))

    async def end(self, say: str = "") -> dict:
        return await self._post("/v1/end", {"say": say}, SHORT_TIMEOUT)

    async def notify(self, reason: str, message: str, urgency: str = "") -> int:
        body = {"reason": reason, "message": message, "urgency": urgency}
        return int((await self._post("/v1/notify", body, SHORT_TIMEOUT)).get("delivered") or 0)


_FENCE = re.compile(r"```.*?(```|$)", re.DOTALL)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_EMPHASIS = re.compile(r"(\*\*|__|\*|`)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)


def speakable(text: str) -> str:
    """Text as it should sound. Markdown and code do not read aloud well."""
    text = _FENCE.sub(" ", text or "")
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("a link", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    text = _EMPHASIS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()
