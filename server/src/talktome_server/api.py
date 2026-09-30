"""The server's API on this machine: HTTP over a Unix socket that only this
user can open. The MCP tools, the hook command, and the Hermes and OpenClaw
plugins use it. The routes are the same as the Go agent node's, so the host
plugins work with both."""

import asyncio
import http.client
import json
import logging
import os
import socket
from pathlib import Path

from .calls import CallIsLive, NoCall

MAX_BODY = 64 * 1024

log = logging.getLogger("talktome")


class Problem(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


class Api:
    def __init__(self, caller, inbound, status):
        self.caller = caller
        self.inbound = inbound
        self.status = status  # returns the status dict
        self.quit = asyncio.Event()

    async def route(self, method: str, path: str, body: dict) -> dict:
        c = self.caller
        if method == "GET" and path == "/v1/status":
            return self.status()
        if method != "POST":
            raise Problem(404, "not_found", "There is no such route.")
        if path == "/v1/call":
            return await c.call(
                body.get("reason", ""),
                question=body.get("question") or "",
                choices=body.get("choices") or None,
                greeting=body.get("greeting") or "",
                urgency=body.get("urgency") or "",
            )
        if path == "/v1/turn":
            return await c.turn(body.get("say", ""))
        if path == "/v1/progress":
            return {"spoken": await c.progress(body.get("say", ""))}
        if path == "/v1/end":
            await c.end(body.get("say", ""))
            return {"ended": True}
        if path == "/v1/notify":
            return {
                "delivered": await c.notify(body.get("reason", ""), body.get("message", ""), body.get("urgency", ""))
            }
        if path == "/v1/permission":
            allow, message = await self.inbound.ask_permission(
                body.get("call_id", ""), body.get("tool", ""), body.get("input")
            )
            return {"allow": allow, "message": message} if message else {"allow": allow}
        if path == "/v1/hook":
            return await self.inbound.hook(body)
        if path == "/v1/quit":
            self.quit.set()
            return {"quitting": True}
        raise Problem(404, "not_found", "There is no such route.")

    async def _serve_one(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status, result = 200, {}
        try:
            request = await reader.readline()
            method, path, _ = request.decode("latin-1").split(" ", 2)
            length = 0
            while (line := await reader.readline()) not in (b"\r\n", b"\n", b""):
                name, _, value = line.decode("latin-1").partition(":")
                if name.strip().lower() == "content-length":
                    length = int(value.strip())
            if length > MAX_BODY:
                raise Problem(413, "invalid", "The request is too large.")
            raw = await reader.readexactly(length) if length else b""
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                raise Problem(400, "invalid", "The request is not the expected JSON.") from None
            result = await self.route(method, path, body if isinstance(body, dict) else {})
        except Problem as exc:
            status, result = exc.status, {"code": exc.code, "message": str(exc)}
        except CallIsLive as exc:
            status, result = 409, {"code": "busy", "message": str(exc)}
        except NoCall as exc:
            status, result = 409, {"code": "no_call", "message": str(exc)}
        except (ValueError, asyncio.IncompleteReadError, ConnectionError):
            status, result = 400, {"code": "invalid", "message": "The request is not valid HTTP."}
        except Exception as exc:
            log.exception("local API request failed")
            status, result = 500, {"code": "failed", "message": str(exc) or type(exc).__name__}
        data = json.dumps(result).encode()
        reason = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            409: "Conflict",
            413: "Too Large",
            500: "Internal Server Error",
        }.get(status, "Error")
        try:
            writer.write(
                f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode()
                + data
            )
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def serve(self, path: Path) -> asyncio.AbstractServer:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(self._serve_one, path=str(path))
        os.chmod(path, 0o600)
        return server


class NotRunning(Exception):
    def __init__(self):
        super().__init__("The talktome server is not running on this machine. Connect to it from the talktome app.")


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("talktome-server", timeout=timeout)
        self._path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


class Client:
    """A blocking client of a running server, for the CLI commands."""

    def __init__(self, path: Path):
        self.path = str(path)

    def request(self, method: str, route: str, body: dict | None = None, timeout: float = 30) -> dict:
        conn = _UnixConnection(self.path, timeout)
        try:
            conn.request(
                method,
                route,
                json.dumps(body).encode() if body is not None else None,
                {"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            data = response.read()
        except (FileNotFoundError, ConnectionRefusedError):
            raise NotRunning() from None
        finally:
            conn.close()
        result = json.loads(data or b"{}")
        if response.status != 200:
            raise RuntimeError(result.get("message") or f"The talktome server failed ({response.status}).")
        return result

    def running(self) -> bool:
        try:
            self.request("GET", "/v1/status", timeout=2)
            return True
        except (NotRunning, OSError, RuntimeError):
            return False
