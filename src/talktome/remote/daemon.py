"""The agent-side remote daemon.

The daemon owns the one network connection. A sandboxed `talktome --remote`
command only ever writes a private local file; the daemon turns that file into a
protocol request and writes the response beside it. That keeps file-only access
for sandboxed agent commands and keeps the pairing code out of command
arguments and transcripts.

The daemon reconnects with bounded backoff. It never silently reissues a
mutating request after an uncertain delivery: a request that was written to the
socket and then lost returns an explicit unknown result.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import random
import sys
import time

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from . import inbox, protocol
from .config import RemoteConfigError, load_agent_config

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 15.0
HEARTBEAT_TIMEOUT = 45.0
AUTH_TIMEOUT = 10.0
CONNECT_WAIT = 5.0
MIN_BACKOFF = 0.5
MAX_BACKOFF = 30.0
STABLE_AFTER = 10.0
MAX_PENDING = 64
MAX_REQUEST_TASKS = 64

# ManagedSession.ANSWER_WAIT is 15 seconds. The remote daemon must not import
# the speech pipeline, so the value is repeated here and the call timeout leaves
# room for the ring wait plus the relay round trip.
ANSWER_WAIT = 15.0
CALL_TIMEOUT = ANSWER_WAIT + 30.0

OPERATION_TIMEOUT = {
    "call": CALL_TIMEOUT,
    "reply": 20.0,
    "end": 15.0,
}


class DaemonError(ValueError):
    """A daemon problem with a protocol error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Revoked(DaemonError):
    def __init__(self, message: str = "This pair was revoked."):
        super().__init__(protocol.ERR_REVOKED, message)


class RemoteDaemon:
    def __init__(self, config: dict):
        self.pair = config["pair"]
        self.url = config["relay"]
        self.credential = config["code"]
        self._ws = None
        self._last_rx = 0.0
        self._connected = asyncio.Event()
        self._pending: dict[str, tuple[asyncio.Future, str]] = {}
        self._stopped = False
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def run(self) -> None:
        inbox.sweep()
        watcher = asyncio.create_task(self._watch())
        backoff = MIN_BACKOFF
        try:
            while not self._stopped:
                started = time.monotonic()
                try:
                    await self._connect_once()
                except Revoked:
                    logger.warning("The relay revoked this pair. The daemon stopped.")
                    self._stopped = True
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - every failure retries on a timer.
                    logger.warning("The relay connection failed: %s", exc)
                if time.monotonic() - started >= STABLE_AFTER:
                    backoff = MIN_BACKOFF
                await self._sleep_backoff(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            await self._close()

    async def _sleep_backoff(self, backoff: float) -> None:
        if self._stopped:
            return
        # A little jitter keeps two daemons from reconnecting in lockstep.
        await asyncio.sleep(backoff * (0.8 + random.random() * 0.4))

    async def _connect_once(self) -> None:
        try:
            socket = await websockets.connect(
                self.url,
                max_size=protocol.MAX_FRAME_BYTES,
                ping_interval=None,
                close_timeout=5,
            )
        except (OSError, WebSocketException) as exc:
            raise DaemonError(protocol.ERR_NOT_CONNECTED, f"The relay is unreachable: {exc}") from exc
        try:
            await self._handshake(socket)
            self._ws = socket
            self._last_rx = time.monotonic()
            self._connected.set()
            reader = asyncio.create_task(self._read(socket))
            beat = asyncio.create_task(self._heartbeat(socket))
            try:
                await reader
            finally:
                beat.cancel()
                await asyncio.gather(beat, return_exceptions=True)
        finally:
            self._ws = None
            self._connected.clear()
            self._fail_pending()
            await socket.close()

    async def _handshake(self, socket) -> None:
        await socket.send(protocol.pack(protocol.make_hello("agent", self.pair, self.credential)))
        try:
            raw = await asyncio.wait_for(socket.recv(), AUTH_TIMEOUT)
        except TimeoutError as exc:
            raise DaemonError(protocol.ERR_NOT_CONNECTED, "The relay did not answer the hello.") from exc
        frame = protocol.unpack(raw)
        if frame.get("type") == protocol.FRAME_ERROR:
            code = str(frame.get("code") or protocol.ERR_UNAUTHORIZED)
            if code == protocol.ERR_REVOKED:
                raise Revoked(str(frame.get("message") or "This pair was revoked."))
            raise DaemonError(
                code,
                str(frame.get("message") or "The relay refused this pair."),
            )
        if frame.get("type") != protocol.FRAME_WELCOME:
            raise DaemonError(protocol.ERR_INVALID, "The relay sent an unexpected hello reply.")

    async def _heartbeat(self, socket) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if self._ws is not socket:
                return
            if time.monotonic() - self._last_rx > HEARTBEAT_TIMEOUT:
                # The relay stopped answering. Close so the reader ends and the
                # reconnect loop can take over.
                with contextlib.suppress(Exception):
                    await socket.close()
                return
            try:
                await socket.send(protocol.pack(protocol.make_ping()))
            except Exception:  # noqa: BLE001 - a dead socket is closed by the reader.
                return

    async def _read(self, socket) -> None:
        try:
            async for raw in socket:
                self._last_rx = time.monotonic()
                if self._ws is not socket:
                    return
                await self._receive(raw)
        except Revoked:
            raise
        except ConnectionClosed as exc:
            if getattr(exc, "code", None) == protocol.CLOSE_REVOKED:
                raise Revoked() from None
            return
        except WebSocketException:
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("The relay connection stopped.")

    async def _receive(self, raw) -> None:
        try:
            frame = protocol.unpack(raw)
        except protocol.ProtocolError:
            logger.warning("The relay sent a frame this build does not understand.")
            return
        frame_type = frame["type"]
        if frame_type == protocol.FRAME_PING:
            socket = self._ws
            if socket is not None:
                with contextlib.suppress(Exception):
                    await socket.send(protocol.pack(protocol.make_pong()))
            return
        if frame_type == protocol.FRAME_REVOKED:
            raise Revoked(str(frame.get("reason") or "This pair was revoked."))
        if frame_type == protocol.FRAME_RESPONSE:
            self._resolve(frame)
            return
        if frame_type == protocol.FRAME_ERROR:
            self._resolve(frame)
            return
        if frame_type == protocol.FRAME_PEER:
            return
        # Events are not used by this release; requests flow the other way.

    def _resolve(self, frame: dict) -> None:
        request_id = frame.get("id")
        if not isinstance(request_id, str):
            # A response without a string ID cannot name a pending request.
            return
        entry = self._pending.pop(request_id, None)
        if entry is None:
            return
        future, _ = entry
        if future.done():
            return
        if frame.get("type") == protocol.FRAME_RESPONSE and frame.get("ok"):
            result = frame.get("result")
            future.set_result(result if isinstance(result, dict) else {})
            return
        # A refused request is an answer, not an unknown delivery.
        code = str(frame.get("code") or protocol.ERR_INVALID)
        message = str(frame.get("message") or "The bridge refused the request.")
        future.set_exception(DaemonError(code, message))

    def _fail_pending(self) -> None:
        for request_id, (future, op) in list(self._pending.items()):
            self._pending.pop(request_id, None)
            if future.done():
                continue
            if op in protocol.MUTATING_OPS:
                future.set_exception(
                    DaemonError(
                        protocol.ERR_UNKNOWN_DELIVERY,
                        "The connection closed after this request was sent. Do not resend it.",
                    )
                )
            else:
                future.set_exception(
                    DaemonError(protocol.ERR_NOT_CONNECTED, "The bridge lost the relay connection.")
                )

    async def request(self, op: str, payload: dict, request_id: str):
        """Send one request and wait for its answer. Never resend a mutation."""
        if len(self._pending) >= MAX_PENDING:
            raise DaemonError(protocol.ERR_TOO_MANY, "Too many requests are already pending.")
        if request_id in self._pending:
            raise DaemonError(protocol.ERR_TOO_MANY, "This request ID is already in flight.")
        socket = self._ws
        if socket is None:
            # Nothing was sent, so this is certain non-delivery rather than the
            # unknown delivery a raised send can mean.
            raise DaemonError(
                protocol.ERR_NOT_CONNECTED, "The bridge is not connected to the relay."
            )
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = (future, op)
        frame = protocol.make_request(op, payload, self.pair, request_id)
        try:
            await socket.send(protocol.pack(frame))
        except Exception as exc:
            self._pending.pop(request_id, None)
            if op in protocol.MUTATING_OPS:
                # A send that raised may still have delivered part of the frame.
                # The daemon must not call that certain non-delivery.
                raise DaemonError(
                    protocol.ERR_UNKNOWN_DELIVERY,
                    "The bridge could not confirm the send. The delivery of this request "
                    "is unknown. Do not resend it.",
                ) from exc
            raise DaemonError(
                protocol.ERR_NOT_CONNECTED, "The bridge could not send the request."
            ) from exc
        timeout = self._timeout(op, payload)
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            if op in protocol.MUTATING_OPS:
                raise DaemonError(
                    protocol.ERR_UNKNOWN_DELIVERY,
                    "The bridge did not hear back. The delivery of this request is unknown. "
                    "Do not resend it.",
                ) from exc
            raise DaemonError(
                protocol.ERR_NOT_CONNECTED, "The bridge did not hear back in time."
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    @staticmethod
    def _timeout(op: str, payload: dict) -> float:
        if op == "listen":
            return float(payload.get("timeout", 25)) + 15.0
        return OPERATION_TIMEOUT[op]

    async def _watch(self) -> None:
        while not self._stopped:
            for request in inbox.pending():
                inbox.retire(request)
                if len(self._tasks) >= MAX_REQUEST_TASKS:
                    inbox.answer(
                        request,
                        error="The bridge is handling too many remote requests. Try again.",
                    )
                    continue
                self._spawn(self._handle(request))
            await asyncio.sleep(inbox.POLL)

    async def _handle(self, request: inbox.Request) -> None:
        try:
            payload = protocol.validate_payload(request.command, request.payload)
        except protocol.ProtocolError as exc:
            inbox.answer(request, error=f"{exc.message} ({exc.code})")
            return
        try:
            await asyncio.wait_for(self._connected.wait(), CONNECT_WAIT)
        except TimeoutError:
            inbox.answer(
                request,
                error="The bridge is not connected to the relay. Start the remote daemon.",
            )
            return
        try:
            result = await self.request(request.command, payload, request.id)
        except DaemonError as exc:
            inbox.answer(request, error=f"{exc.message} ({exc.code})")
            return
        except Exception as exc:
            logger.exception("A remote request failed.")
            inbox.answer(request, error=str(exc) or "The bridge could not take that request.")
            return
        inbox.answer(request, result=result)

    async def _close(self) -> None:
        self._stopped = True
        self._connected.clear()
        self._fail_pending()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()


def run_daemon() -> int:
    try:
        config = load_agent_config()
    except RemoteConfigError as exc:
        print(f"The remote daemon has no usable configuration: {exc}", file=sys.stderr)
        return 1
    if not config:
        print(
            "No remote configuration. Run `talktome remote-setup --relay URL --pair PAIR "
            "--code-stdin` on this server first.",
            file=sys.stderr,
        )
        return 1
    try:
        asyncio.run(RemoteDaemon(config).run())
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="talktome-remote", description="Run the TalkToMe remote bridge daemon."
    )
    parser.parse_args(argv)
    return run_daemon()


if __name__ == "__main__":
    raise SystemExit(main())
