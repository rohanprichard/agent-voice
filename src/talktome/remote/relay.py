"""A self-hosted relay for two outbound bridge connections.

The relay pairs two fixed roles, laptop and agent, with separate credentials. It
forwards bounded protocol frames between those two authenticated members and
does nothing else: it does not run shell commands, inspect files, or forward
HTTP. Transport encryption ends here, so the relay can read forwarded text.
There is no end-to-end encryption in this release.

Administration runs on the relay host through the local CLI and edits one
private file. There is no public pair-creation endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ..config import data_dir
from . import RELAY_PATH, credentials, protocol
from .private import PrivateFileError, atomic_write_json, read_json

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 15.0
CONNECTION_TIMEOUT = 45.0
AUTH_TIMEOUT = 10.0
WATCH_INTERVAL = 1.0
SEND_TIMEOUT = 10.0
MAX_CONNECTIONS = 512

CLOSE_UNAUTHORIZED = 4401
CLOSE_REVOKED = 4403
CLOSE_OCCUPIED = 4409
CLOSE_STALE = 4408
CLOSE_PROTOCOL = 4400
CLOSE_CAPACITY = 4413

STORE_VERSION = 1

# Who may send what across the relay. An agent only makes requests; the laptop
# only answers or refuses them. Ping and pong are handled before this check.
ALLOWED_FRAMES = {
    credentials.AGENT_ROLE: frozenset({protocol.FRAME_REQUEST}),
    credentials.LAPTOP_ROLE: frozenset({protocol.FRAME_RESPONSE, protocol.FRAME_ERROR}),
}


class RelayStoreError(ValueError):
    """The relay metadata file is missing something it needs."""


def relay_file() -> Path:
    override = os.environ.get("TALKTOME_RELAY_FILE")
    if override:
        return Path(override).expanduser()
    return data_dir() / "relay" / "relay.json"


class RelayStore:
    """Pair metadata and credential hashes in one private file.

    Credentials are never stored whole; only their hashes are. Revocation marks
    a pair, so it survives a restart with no in-memory state to lose.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else relay_file()
        self.pairs: dict[str, dict] = {}
        self.revision = 0
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            self.pairs = {}
            self.revision = 0
            return
        document = read_json(self.path)
        if not isinstance(document, dict) or not isinstance(document.get("pairs"), dict):
            raise RelayStoreError(f"{self.path.name} is not a valid relay file.")
        pairs = {}
        for pair_id, entry in document["pairs"].items():
            if not isinstance(entry, dict):
                continue
            laptop_hash = entry.get("laptop_hash")
            agent_hash = entry.get("agent_hash")
            if not isinstance(laptop_hash, str) or not isinstance(agent_hash, str):
                continue
            pairs[str(pair_id)] = {
                "label": str(entry.get("label") or ""),
                "created_at": float(entry.get("created_at") or 0),
                "revoked": bool(entry.get("revoked")),
                "laptop_hash": laptop_hash,
                "agent_hash": agent_hash,
            }
        self.pairs = pairs
        self.revision = self._mtime()

    def _mtime(self) -> int:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return 0

    def reload_if_changed(self) -> bool:
        """Re-read the file when the admin command replaced it."""
        revision = self._mtime()
        if revision == self.revision:
            return False
        self.load()
        return True

    def save(self) -> None:
        document = {
            "version": STORE_VERSION,
            "pairs": {
                pair_id: {
                    "label": entry["label"],
                    "created_at": entry["created_at"],
                    "revoked": entry["revoked"],
                    "laptop_hash": entry["laptop_hash"],
                    "agent_hash": entry["agent_hash"],
                }
                for pair_id, entry in self.pairs.items()
            },
        }
        atomic_write_json(self.path, document)
        self.revision = self._mtime()

    def create_pair(self, label: str = "") -> dict:
        """Make one pair and return both credentials once.

        The agent credential is the long-lived pairing code. The laptop
        credential stays in the laptop configuration. Neither expires on its
        own; only a revocation retires them.
        """
        self.load()
        pair_id = credentials.new_pair_id()
        while pair_id in self.pairs:
            pair_id = credentials.new_pair_id()
        laptop_credential = credentials.new_laptop_credential()
        agent_credential = credentials.new_agent_credential()
        self.pairs[pair_id] = {
            "label": str(label or "").strip()[: credentials.MAX_CREDENTIAL],
            "created_at": time.time(),
            "revoked": False,
            "laptop_hash": credentials.hash_credential(laptop_credential),
            "agent_hash": credentials.hash_credential(agent_credential),
        }
        self.save()
        return {
            "pair": pair_id,
            "laptop_credential": laptop_credential,
            "agent_credential": agent_credential,
            "label": self.pairs[pair_id]["label"],
            "created_at": self.pairs[pair_id]["created_at"],
        }

    def revoke_pair(self, pair_id: str) -> bool:
        self.load()
        entry = self.pairs.get(pair_id)
        if entry is None:
            return False
        if entry["revoked"]:
            return True
        entry["revoked"] = True
        self.save()
        return True

    def list_pairs(self) -> list[dict]:
        self.load()
        return [
            {
                "pair": pair_id,
                "label": entry["label"],
                "created_at": entry["created_at"],
                "revoked": entry["revoked"],
            }
            for pair_id, entry in sorted(self.pairs.items())
        ]

    def authenticate(self, pair_id: str, role: str, credential: str) -> bool:
        """Verify one role's credential. A code for one role never fits another."""
        if role not in credentials.ROLES:
            return False
        entry = self.pairs.get(pair_id)
        if entry is None or entry["revoked"]:
            return False
        digest = entry[f"{role}_hash"]
        return credentials.verify_credential(credential, digest)

    def revoked(self, pair_id: str) -> bool:
        entry = self.pairs.get(pair_id)
        return entry is None or bool(entry["revoked"])


@dataclass
class Connection:
    websocket: WebSocket
    pair: str
    role: str
    last_seen: float = field(default_factory=time.monotonic)
    # Frames reach one socket from more than one task (the peer's forwarding loop
    # and the revocation watcher), and a WebSocket wants sends serialized.
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RelayHub:
    """Hold the two members of each pair and forward frames between them."""

    def __init__(self, store: RelayStore, *, timeout: float = CONNECTION_TIMEOUT):
        self.store = store
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._peers: dict[str, dict[str, Connection]] = {}
        self._connections = 0
        self._tasks: set[asyncio.Task] = set()

    def start(self) -> None:
        self._spawn(self._sweep())
        self._spawn(self._watch_revocations())

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for members in self._peers.values():
            for connection in members.values():
                with contextlib.suppress(Exception):
                    await connection.websocket.close(code=CLOSE_STALE)
        self._peers.clear()

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _peer(self, pair: str, role: str) -> Connection | None:
        other = "agent" if role == "laptop" else "laptop"
        return self._peers.get(pair, {}).get(other)

    async def _send(self, connection: Connection, frame: dict) -> bool:
        try:
            encoded = protocol.pack(frame)
        except protocol.ProtocolError:
            return False
        async with connection.send_lock:
            try:
                await asyncio.wait_for(
                    connection.websocket.send_text(encoded), SEND_TIMEOUT
                )
                return True
            except TimeoutError:
                # A write that will not complete is a peer that is not reading.
                with contextlib.suppress(Exception):
                    await connection.websocket.close(code=CLOSE_STALE)
                return False
            except Exception:  # noqa: BLE001 - a closed peer is not an error here.
                return False

    async def _fail(self, websocket: WebSocket, code: str, message: str, close_code: int) -> None:
        with contextlib.suppress(Exception):
            await websocket.send_text(protocol.pack(protocol.make_error(None, code, message)))
        with contextlib.suppress(Exception):
            await websocket.close(code=close_code)

    async def handle(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            at_capacity = self._connections >= MAX_CONNECTIONS
        if at_capacity:
            await self._fail(
                websocket,
                protocol.ERR_TOO_MANY,
                "The relay is at capacity. Try again later.",
                CLOSE_CAPACITY,
            )
            return
        connection = await self._authenticate(websocket)
        if connection is None:
            return
        occupied = False
        async with self._lock:
            members = self._peers.setdefault(connection.pair, {})
            if members.get(connection.role) is not None:
                occupied = True
            else:
                members[connection.role] = connection
                self._connections += 1
        if occupied:
            await self._fail(
                websocket,
                protocol.ERR_OCCUPIED,
                "That role is already connected. Wait for it to close.",
                CLOSE_OCCUPIED,
            )
            return
        try:
            await self._send(
                connection,
                protocol.make_welcome(
                    connection.pair, connection.role, self._peer(connection.pair, connection.role)
                    is not None,
                ),
            )
            await self._announce(connection, "connected")
            await self._serve(connection)
        finally:
            await self._remove(connection)
            await self._announce(connection, "disconnected")

    async def _authenticate(self, websocket: WebSocket) -> Connection | None:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT)
        except (TimeoutError, WebSocketDisconnect):
            await self._fail(
                websocket,
                protocol.ERR_UNAUTHORIZED,
                "The relay did not receive a hello frame in time.",
                CLOSE_UNAUTHORIZED,
            )
            return None
        try:
            frame = protocol.unpack(raw)
            if frame.get("type") != protocol.FRAME_HELLO:
                raise protocol.ProtocolError(protocol.ERR_INVALID, "Send a hello frame first.")
            pair = frame.get("pair")
            role = frame.get("role")
            credential = frame.get("credential")
            # Check the types before `pair` is used as a dict key: an unhashable
            # list or object would otherwise raise past the protocol error path.
            if not isinstance(pair, str) or not credentials.valid_pair_id(pair):
                raise protocol.ProtocolError(
                    protocol.ERR_UNAUTHORIZED, "The pair or credential is not valid."
                )
            if role not in credentials.ROLES:
                raise protocol.ProtocolError(protocol.ERR_INVALID, "Use the laptop or agent role.")
            if not isinstance(credential, str) or not credentials.valid_credential(credential):
                raise protocol.ProtocolError(protocol.ERR_UNAUTHORIZED, "Send a credential.")
            try:
                self.store.reload_if_changed()
            except RelayStoreError:
                # Keep the last good pairs rather than refusing every connection
                # because the file is momentarily mid-replacement.
                logger.warning("The relay file could not be reloaded during a hello.")
            if not self.store.authenticate(pair, role, credential):
                if self.store.pairs.get(pair, {}).get("revoked"):
                    raise protocol.ProtocolError(
                        protocol.ERR_REVOKED, "This pair was revoked."
                    )
                raise protocol.ProtocolError(
                    protocol.ERR_UNAUTHORIZED, "The pair or credential is not valid."
                )
        except protocol.ProtocolError as exc:
            close_code = (
                CLOSE_REVOKED if exc.code == protocol.ERR_REVOKED else CLOSE_UNAUTHORIZED
            )
            await self._fail(websocket, exc.code, exc.message, close_code)
            return None
        return Connection(websocket=websocket, pair=pair, role=role)

    async def _serve(self, connection: Connection) -> None:
        websocket = connection.websocket
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                return
            except Exception:  # noqa: BLE001 - a broken socket ends this connection.
                return
            # Revocation is enforced before anything is forwarded. The watcher is
            # the backstop; this closes the window between a write and the sweep.
            if self._revoked_now(connection):
                await self._revoke(connection)
                return
            connection.last_seen = time.monotonic()
            try:
                frame = protocol.unpack(raw)
            except protocol.ProtocolError as exc:
                await self._fail(websocket, exc.code, exc.message, CLOSE_PROTOCOL)
                return
            frame_type = frame["type"]
            if frame_type == protocol.FRAME_PING:
                await self._send(connection, protocol.make_pong())
                continue
            if frame_type == protocol.FRAME_PONG:
                continue
            if frame_type not in ALLOWED_FRAMES.get(connection.role, frozenset()):
                await self._send(
                    connection,
                    protocol.make_error(
                        frame.get("id"),
                        protocol.ERR_INVALID,
                        "The relay does not forward that frame from this role.",
                    ),
                )
                continue
            if frame_type == protocol.FRAME_REQUEST:
                try:
                    protocol.validate_request(frame)
                except protocol.ProtocolError as exc:
                    await self._send(
                        connection, protocol.make_error(frame.get("id"), exc.code, exc.message)
                    )
                    continue
                if frame.get("pair") != connection.pair:
                    await self._send(
                        connection,
                        protocol.make_error(
                            frame.get("id"),
                            protocol.ERR_UNAUTHORIZED,
                            "That request names another pair.",
                        ),
                    )
                    continue
            else:
                # A response or error must name its request with a plain string,
                # so the peer never has to use an unhashable value as a key.
                request_id = frame.get("id")
                if request_id is not None and (
                    not isinstance(request_id, str) or len(request_id) > protocol.MAX_ID
                ):
                    await self._send(
                        connection,
                        protocol.make_error(
                            None,
                            protocol.ERR_INVALID,
                            "Send a string request ID.",
                        ),
                    )
                    continue
            peer = self._peer(connection.pair, connection.role)
            if peer is None:
                if frame_type == protocol.FRAME_REQUEST:
                    await self._send(
                        connection,
                        protocol.make_error(
                            frame.get("id"),
                            protocol.ERR_UNAVAILABLE,
                            "The other side of this pair is not connected.",
                        ),
                    )
                continue
            delivered = await self._send(peer, frame)
            if not delivered and frame_type == protocol.FRAME_REQUEST:
                await self._send(
                    connection,
                    protocol.make_error(
                        frame.get("id"),
                        protocol.ERR_UNAVAILABLE,
                        "The other side of this pair is not reachable.",
                    ),
                )

    def _revoked_now(self, connection: Connection) -> bool:
        try:
            self.store.reload_if_changed()
        except RelayStoreError:
            # Keep the last good store rather than refusing every frame because
            # the file is momentarily mid-replacement.
            logger.warning("The relay file could not be reloaded while forwarding.")
        return self.store.revoked(connection.pair)

    async def _revoke(self, connection: Connection) -> None:
        await self._send(connection, protocol.make_revoked("This pair was revoked."))
        with contextlib.suppress(Exception):
            await connection.websocket.close(code=CLOSE_REVOKED)
        await self._remove(connection)
        await self._announce(connection, "disconnected")

    async def _announce(self, connection: Connection, state: str) -> None:
        peer = self._peer(connection.pair, connection.role)
        if peer is not None:
            await self._send(
                peer,
                protocol.make_peer(connection.pair, connection.role, state),
            )

    async def _remove(self, connection: Connection) -> None:
        async with self._lock:
            members = self._peers.get(connection.pair)
            if not members:
                return
            if members.get(connection.role) is connection:
                members.pop(connection.role, None)
                self._connections = max(0, self._connections - 1)
            if not members:
                self._peers.pop(connection.pair, None)

    def _all_connections(self) -> list[Connection]:
        return [connection for members in self._peers.values() for connection in members.values()]

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(WATCH_INTERVAL)
            now = time.monotonic()
            for connection in self._all_connections():
                idle = now - connection.last_seen
                if idle > self.timeout:
                    await self._fail(
                        connection.websocket,
                        protocol.ERR_UNAVAILABLE,
                        "The relay closed an idle connection.",
                        CLOSE_STALE,
                    )
                    await self._remove(connection)
                    await self._announce(connection, "disconnected")
                    continue
                if idle > HEARTBEAT_SECONDS:
                    # Ask for a pong so a dead peer is noticed before the timeout.
                    await self._send(connection, protocol.make_ping())

    async def _watch_revocations(self) -> None:
        while True:
            await asyncio.sleep(WATCH_INTERVAL)
            try:
                # Reload, but never skip the sweep when someone else reloaded
                # first: `_authenticate` may have already advanced the revision,
                # and the connected pair would then miss its revocation.
                self.store.reload_if_changed()
            except RelayStoreError:
                logger.exception("The relay file could not be reloaded.")
                continue
            for connection in self._all_connections():
                if self.store.revoked(connection.pair):
                    await self._revoke(connection)


def create_relay_app(store: RelayStore | None = None, *, timeout: float = CONNECTION_TIMEOUT):
    """Build the relay app. It exposes one WebSocket route and nothing else."""
    relay_store = store or RelayStore()
    hub = RelayHub(relay_store, timeout=timeout)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        hub.start()
        try:
            yield
        finally:
            await hub.close()

    app = FastAPI(title="TalkToMe relay", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store = relay_store
    app.state.hub = hub

    @app.websocket(RELAY_PATH)
    async def relay_socket(websocket: WebSocket):
        await hub.handle(websocket)

    return app


def serve_relay(
    host: str = "127.0.0.1",
    port: int = 8766,
    relay_path: Path | None = None,
    allow_network: bool = False,
) -> None:
    """Run the relay. It binds loopback by default, for use behind a TLS proxy.

    Binding a network address directly would serve plain ``ws`` to the network.
    The relay does not terminate TLS itself, so a network bind needs an explicit
    flag rather than a warning that is easy to miss.
    """
    import uvicorn

    if host not in {"127.0.0.1", "localhost", "::1"}:
        if not allow_network:
            raise ValueError(
                f"The relay serves plain ws and has no TLS. It does not bind {host} "
                "unless you pass --allow-network. Put it behind a TLS proxy instead."
            )
        logger.warning(
            "The relay is bound to %s without TLS. Put it behind a TLS proxy so "
            "clients connect with wss.",
            host,
        )
    store = RelayStore(relay_path)
    app = create_relay_app(store)
    # Bound the server's own frame buffer and send queue explicitly. The route
    # protocol already refuses oversized frames; this keeps a large or slow peer
    # from growing the transport queue without limit.
    uvicorn.run(
        app,
        host=host,
        port=port,
        access_log=False,
        ws_max_size=protocol.MAX_FRAME_BYTES,
        ws_max_queue=64,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="talktome-relay", description="Run the self-hosted remote bridge relay."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address. Loopback by default.")
    parser.add_argument("--port", type=int, default=8766, help="Bind port.")
    parser.add_argument("--relay-file", help="Override the private pair metadata file.")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Bind a non-loopback address. The relay has no TLS, so use a TLS proxy.",
    )
    args = parser.parse_args(argv)
    try:
        serve_relay(
            args.host,
            args.port,
            Path(args.relay_file) if args.relay_file else None,
            allow_network=args.allow_network,
        )
    except (RelayStoreError, PrivateFileError, OSError, ValueError) as exc:
        print(f"The relay could not start: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
