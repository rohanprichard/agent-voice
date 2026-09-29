"""The laptop side of the remote bridge.

The connector lives in the app's lifespan, so it speaks to the same voice
pipeline a local call uses. It accepts only the four cooperative operations,
forces cooperative mode, and refuses to read, answer, or end a call this pair
does not own. A remote request never sees local settings, files, credentials,
or provider configuration.

Each request is handled by a task bound to the socket it arrived on. A response
from an old socket is never sent on a replacement one, and a transport loss
cancels the waiting requests without giving up the call this pair still owns.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import websockets
from fastapi import HTTPException
from websockets.exceptions import ConnectionClosed, WebSocketException

from ..config import data_dir
from ..cooperative import CooperativeAdapter
from . import protocol
from .config import RemoteConfigError, load_laptop_config
from .journal import (
    STATE_DONE,
    CommandJournal,
    JournalConflict,
    JournalError,
    JournalExpired,
    JournalFull,
    JournalPending,
    JournalUnknown,
)
from .tunnel import SSHTunnel

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 15.0
HEARTBEAT_TIMEOUT = 45.0
AUTH_TIMEOUT = 10.0
MIN_BACKOFF = 1.0
MAX_BACKOFF = 30.0
STABLE_AFTER = 20.0
JOURNAL_FILE = "remote-journal.json"

# A listen request is allowed to wait; requests still multiplex, but a flood of
# them must not become unbounded tasks.
MAX_REQUEST_TASKS = 16


class ConnectorError(ValueError):
    """A request this pair must not act on."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Revoked(ValueError):
    """The relay revoked this pair."""


@dataclass
class PairCall:
    """What this pair owns right now, if anything.

    The adapter object is the identity. A later call is a different object even
    when it reuses the same thread name, so an old wait or an old end can tell
    that the live call is no longer the one it bound.
    """

    thread: str | None = None
    namespaced: str | None = None
    ring_id: str | None = None
    call_id: str | None = None
    adapter: CooperativeAdapter | None = None


def _journal_result(op: str, result) -> dict:
    """The part of a result worth persisting, without greeting or transcript text."""
    if not isinstance(result, dict):
        return {}
    if op == "call":
        clean = {}
        if "answered" in result:
            clean["answered"] = bool(result.get("answered"))
        ring = result.get("ring")
        if isinstance(ring, dict):
            clean["ring"] = {"id": ring.get("id"), "name": ring.get("name")}
        if result.get("status") is not None:
            clean["status"] = result["status"]
        return clean
    if op == "reply":
        return {
            "ok": bool(result.get("ok")),
            "duplicate": bool(result.get("duplicate")),
            "final": bool(result.get("final")),
        }
    if op == "end":
        return {"status": str(result.get("status") or "idle")}
    return {}


class RemoteConnector:
    def __init__(self, managed, config: dict, *, journal_path: Path | None = None):
        self.managed = managed
        self.pair = config["pair"]
        self.configured_url = config["relay"]
        self.credential = config["credential"]
        self.tunnel = None
        if config.get("ssh"):
            ssh = config["ssh"]
            self.tunnel = SSHTunnel(
                ssh["target"],
                ssh["remote_port"],
                urlsplit(self.configured_url).port or ssh["remote_port"],
                ssh.get("port"),
            )
        self.connection = "connecting"
        self.error: str | None = None
        self.journal = CommandJournal(journal_path or (data_dir() / JOURNAL_FILE), self.pair)
        self.state = PairCall()
        self._state_lock = asyncio.Lock()
        self._generation = 0
        self._ws = None
        self._last_rx = 0.0
        self._stopped = False
        self._request_tasks: set[asyncio.Task] = set()

    @property
    def url(self) -> str:
        if self.tunnel is None:
            return self.configured_url
        # The tunnel can move to another local port when the saved one is busy.
        path = urlsplit(self.configured_url).path
        return f"ws://127.0.0.1:{self.tunnel.local_port}{path}"

    def status(self) -> dict:
        report = {
            "pair": self.pair,
            "relay": self.url,
            "connection": self.connection,
            "error": self.error,
        }
        if self.tunnel is not None:
            report["tunnel"] = self.tunnel.status()
        return report

    def _spawn_request(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._request_tasks.add(task)
        task.add_done_callback(self._request_tasks.discard)

    async def run(self) -> None:
        backoff = MIN_BACKOFF
        tunnel = asyncio.create_task(self.tunnel.run()) if self.tunnel is not None else None
        try:
            while not self._stopped:
                if self.tunnel is not None and not self.tunnel.ready.is_set():
                    self.connection = "waiting for tunnel"
                    await self.tunnel.ready.wait()
                started = time.monotonic()
                self.connection = "connecting"
                try:
                    await self._connect_once()
                    self.connection = "disconnected"
                except Revoked:
                    logger.info("The relay revoked this pair; the connector stopped.")
                    self.connection = "revoked"
                    self.error = "The relay revoked this pair."
                    await self._release_pair()
                    self._stopped = True
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - every failure retries on a timer.
                    self.connection = "disconnected"
                    self.error = str(exc)
                    logger.warning("The remote relay connection failed: %s", exc)
                if time.monotonic() - started >= STABLE_AFTER:
                    backoff = MIN_BACKOFF
                if self._stopped:
                    break
                await asyncio.sleep(backoff * (0.8 + random.random() * 0.4))
                backoff = min(backoff * 2, MAX_BACKOFF)
        finally:
            await self._close()
            if tunnel is not None:
                tunnel.cancel()
                await asyncio.gather(tunnel, return_exceptions=True)
                await self.tunnel.stop()

    async def _connect_once(self) -> None:
        try:
            socket = await websockets.connect(
                self.url,
                max_size=protocol.MAX_FRAME_BYTES,
                ping_interval=None,
                close_timeout=5,
            )
        except (OSError, WebSocketException) as exc:
            raise ConnectorError(protocol.ERR_NOT_CONNECTED, f"The relay is unreachable: {exc}")
        try:
            await self._handshake(socket)
            self._ws = socket
            self.connection = "connected"
            self.error = None
            self._last_rx = time.monotonic()
            reader = asyncio.create_task(self._read(socket))
            beat = asyncio.create_task(self._heartbeat(socket))
            try:
                await reader
            finally:
                beat.cancel()
                await asyncio.gather(beat, return_exceptions=True)
        finally:
            # Requests belong to this socket. Drop their tasks, but keep the call
            # this pair owns so a reconnect can carry it on.
            self._ws = None
            await self._cancel_requests()
            # A response that never left is an unknown delivery for every claim
            # still in flight. The mutation may have happened; a retry must not.
            self.journal.mark_pending_unknown()
            with contextlib.suppress(Exception):
                await socket.close()

    async def _handshake(self, socket) -> None:
        await socket.send(
            protocol.pack(protocol.make_hello("laptop", self.pair, self.credential))
        )
        try:
            raw = await asyncio.wait_for(socket.recv(), AUTH_TIMEOUT)
        except TimeoutError as exc:
            raise ConnectorError(protocol.ERR_NOT_CONNECTED, "The relay did not answer the hello.") from exc
        frame = protocol.unpack(raw)
        if frame.get("type") == protocol.FRAME_ERROR:
            code = str(frame.get("code") or protocol.ERR_UNAUTHORIZED)
            if code == protocol.ERR_REVOKED:
                raise Revoked()
            raise ConnectorError(
                code,
                str(frame.get("message") or "The relay refused this pair."),
            )
        if frame.get("type") != protocol.FRAME_WELCOME:
            raise ConnectorError(protocol.ERR_INVALID, "The relay sent an unexpected hello reply.")

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
            except Exception:  # noqa: BLE001 - a dead socket ends this connection.
                return

    async def _read(self, socket) -> None:
        try:
            async for raw in socket:
                self._last_rx = time.monotonic()
                if self._ws is not socket:
                    return
                await self._receive(socket, raw)
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
            logger.exception("The remote relay connection stopped.")

    async def _receive(self, socket, raw) -> None:
        try:
            frame = protocol.unpack(raw)
        except protocol.ProtocolError:
            logger.warning("The relay sent a frame this build does not understand.")
            return
        frame_type = frame["type"]
        if frame_type == protocol.FRAME_PING:
            await self._send_on(socket, protocol.make_pong())
            return
        if frame_type == protocol.FRAME_REVOKED:
            raise Revoked()
        if frame_type == protocol.FRAME_REQUEST:
            if len(self._request_tasks) >= MAX_REQUEST_TASKS:
                await self._send_on(
                    socket,
                    protocol.make_error(
                        frame.get("id"),
                        protocol.ERR_TOO_MANY,
                        "The laptop is handling too many remote requests.",
                    ),
                )
                return
            self._spawn_request(self._handle(socket, frame))
            return
        # Responses and peer notices are not used by the laptop in this release.

    async def _send_on(self, socket, frame: dict) -> bool:
        """Send one frame only while it is still the current socket."""
        if socket is None or self._ws is not socket:
            return False
        try:
            encoded = protocol.pack(frame)
        except protocol.ProtocolError:
            return False
        try:
            await socket.send(encoded)
            return True
        except Exception:  # noqa: BLE001 - a closed peer is not this task's failure.
            return False

    async def _send_result(self, socket, request_id: str, result: dict) -> None:
        try:
            frame = protocol.make_response(request_id, result)
            encoded = protocol.pack(frame)
        except protocol.ProtocolError:
            await self._send_on(
                socket,
                protocol.make_error(request_id, protocol.ERR_FRAME, "The result is too large."),
            )
            return
        if socket is None or self._ws is not socket:
            return
        with contextlib.suppress(Exception):
            await socket.send(encoded)

    async def _send_error(self, socket, request_id, code: str, message: str) -> None:
        await self._send_on(socket, protocol.make_error(request_id, code, message))

    async def _handle(self, socket, frame: dict) -> None:
        try:
            request_id, payload = protocol.validate_request(frame)
        except protocol.ProtocolError as exc:
            await self._send_error(socket, frame.get("id"), exc.code, exc.message)
            return
        if frame.get("pair") != self.pair:
            await self._send_error(
                socket, request_id, protocol.ERR_UNAUTHORIZED, "That frame names another pair."
            )
            return
        op = frame["op"]
        claim = None
        if op in protocol.MUTATING_OPS:
            try:
                claim = self.journal.claim(request_id, op, payload)
            except JournalConflict as exc:
                await self._send_error(socket, request_id, protocol.ERR_INVALID, str(exc))
                return
            except JournalPending as exc:
                await self._send_error(socket, request_id, protocol.ERR_TOO_MANY, str(exc))
                return
            except JournalExpired as exc:
                await self._send_error(socket, request_id, protocol.ERR_INVALID, str(exc))
                return
            except JournalFull as exc:
                await self._send_error(socket, request_id, protocol.ERR_TOO_MANY, str(exc))
                return
            except JournalUnknown as exc:
                await self._send_error(socket, request_id, protocol.ERR_UNKNOWN_DELIVERY, str(exc))
                return
            except JournalError as exc:
                await self._send_error(socket, request_id, protocol.ERR_INTERNAL, str(exc))
                return
            if claim.state == STATE_DONE:
                await self._send_result(socket, request_id, claim.result or {})
                return
        try:
            result = await self._dispatch(op, payload)
        except ConnectorError as exc:
            if claim is not None:
                self.journal.fail_unknown(request_id, exc.message)
            await self._send_error(socket, request_id, exc.code, exc.message)
            return
        except HTTPException as exc:
            message = str(exc.detail)
            if claim is not None:
                self.journal.fail_unknown(request_id, message)
            await self._send_error(socket, request_id, protocol.ERR_INVALID, message)
            return
        except asyncio.CancelledError:
            # The transport ended under this request. The claim stays in flight;
            # the reconnect marks it unknown rather than resending it.
            raise
        except Exception as exc:
            logger.exception("A remote request failed.")
            if claim is not None:
                self.journal.fail_unknown(request_id, str(exc))
            await self._send_error(
                socket, request_id, protocol.ERR_INTERNAL, str(exc) or "The laptop could not take that request."
            )
            return
        if claim is not None:
            self.journal.complete(request_id, _journal_result(op, result))
        await self._send_result(socket, request_id, result)

    async def _dispatch(self, op: str, payload: dict) -> dict:
        if op == "call":
            return await self._call(payload)
        if op == "listen":
            return await self._listen(payload)
        if op == "reply":
            return await self._reply(payload)
        if op == "end":
            return await self._end()
        raise ConnectorError(protocol.ERR_INVALID, "Use call, listen, reply, or end.")

    def _namespaced(self, thread: str) -> str:
        return f"{self.pair}:{thread}"

    def _local_dir(self) -> Path:
        directory = data_dir()
        if not directory.is_dir():
            raise ConnectorError(protocol.ERR_INTERNAL, "The laptop has no data directory.")
        return directory

    def _adapter(self, thread: str) -> CooperativeAdapter:
        adapter = self.managed.adapter
        if not isinstance(adapter, CooperativeAdapter):
            raise ConnectorError(protocol.ERR_UNAVAILABLE, "No cooperative remote call is active.")
        if adapter.session_id != self._namespaced(thread):
            raise ConnectorError(protocol.ERR_UNAVAILABLE, "This pair does not own that call.")
        return adapter

    async def _call(self, payload: dict) -> dict:
        async with self._state_lock:
            if self.managed.adapter is not None or self.managed.ring is not None or self.managed.room.call_id:
                raise ConnectorError(
                    protocol.ERR_UNAVAILABLE,
                    "The laptop is already in a call or ringing. Try again after it ends.",
                )
            namespaced = self._namespaced(payload["thread"])
            result = await self.managed.attach(
                namespaced,
                str(self._local_dir()),
                payload["greeting"],
                payload["name"] or None,
                payload["agent"],
                "cooperative",
            )
            adapter = self.managed.adapter
            ring = result.get("ring") or {}
            ring_id = ring.get("id")
            # Bind before the wait below, so an `end` that arrives while the ring
            # is pending ends this pair's ring and not a local one.
            self.state = PairCall(
                thread=payload["thread"],
                namespaced=namespaced,
                ring_id=ring_id,
                adapter=adapter,
            )
            self._generation += 1
            generation = self._generation
        if not (payload["wait"] and ring_id):
            return result
        result["answered"] = await self.managed.answered(ring_id)
        async with self._state_lock:
            if self._generation != generation or self.state.adapter is not adapter:
                # A later call or an end replaced this state. Do not write over it.
                return result
            if result["answered"]:
                self.state.call_id = self.managed.room.call_id
            else:
                self.state = PairCall()
        return result

    async def _listen(self, payload: dict) -> dict:
        adapter = self._adapter(payload["thread"])
        return await adapter.listen(payload["after"], payload["timeout"])

    async def _reply(self, payload: dict) -> dict:
        adapter = self._adapter(payload["thread"])
        return await adapter.reply(
            adapter.session_id,
            payload["call_id"],
            payload["turn_id"],
            payload["item_id"],
            payload["text"],
            payload["final"],
        )

    async def _end_state(self, state: PairCall) -> bool:
        """End exactly the call this state bound, using the adapter identity."""
        adapter = state.adapter
        if adapter is not None and self.managed.adapter is not adapter:
            return False
        ring = self.managed.ring
        if state.ring_id is not None and ring and ring.get("id") == state.ring_id:
            try:
                await self.managed.decline(state.ring_id)
                return True
            except HTTPException:
                return False
        if adapter is not None and self.managed.adapter is adapter:
            call_id = self.managed.room.call_id
            if call_id:
                try:
                    await self.managed.hangup(
                        expected_call_id=call_id, expected_adapter=adapter
                    )
                    return True
                except HTTPException:
                    return False
        return False

    async def _end(self) -> dict:
        async with self._state_lock:
            state = self.state
            self.state = PairCall()
            self._generation += 1
        ended = await self._end_state(state)
        return {"status": "ended" if ended else "idle"}

    async def _release_pair(self) -> None:
        """Revocation: end only this pair's call and discard its queued work."""
        async with self._state_lock:
            state = self.state
            self.state = PairCall()
            self._generation += 1
        await self._cancel_requests()
        self.journal.mark_pending_unknown()
        await self._end_state(state)

    async def _cancel_requests(self) -> None:
        tasks = list(self._request_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._request_tasks.clear()

    async def _close(self) -> None:
        self._stopped = True
        await self._cancel_requests()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()


def start_connector(managed) -> RemoteConnector | None:
    """Build the connector when — and only when — the laptop is configured."""
    try:
        config = load_laptop_config()
    except RemoteConfigError as exc:
        logger.error("The remote connector configuration is unusable: %s", exc)
        return None
    if not config:
        return None
    try:
        return RemoteConnector(managed, config)
    except JournalError as exc:
        logger.error("The remote command journal is unusable; not starting: %s", exc)
        return None
