"""A private file inbox between the remote CLI and its local daemon.

This is a second inbox, deliberately separate from the app's local one. A
remote command must never ring the laptop's ordinary local inbox, and the
daemon must never be reached over the network by a sandboxed agent command.

The same two-place trick as the local inbox is kept: the daemon's own folder
when a sandbox allows the write, and a private folder under ``/tmp`` when it
does not. Every file is validated for ownership, permissions, type, name, age,
and size before it is trusted, and a reply is checked for the same plus its ID
and version. Directory ownership is checked before anything in it is read or
removed, and every scan is bounded.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from . import private, protocol
from .config import data_root
from .private import PrivateFileError

POLL = 0.1
STALE = 120
REQUEST_SUFFIX = ".remote-request.json"
REPLY_SUFFIX = ".remote-reply.json"
MAX_REQUEST_BYTES = 64 * 1024
MAX_REPLY_BYTES = 64 * 1024
MAX_SCAN_FILES = 512
BODY_VERSION = 1

COMMANDS = frozenset({"call", "listen", "reply", "end"})


def folder(root=None) -> Path:
    return (root or data_root()) / "remote-requests"


def shared() -> Path:
    return Path("/tmp") / f"talktome-{os.getuid()}-remote" / "requests"


def places(root=None) -> list[Path]:
    found = []
    with contextlib.suppress(OSError):
        found.append(folder(root))
    found.append(shared())
    return found


def _owned_dir(place: Path) -> bool:
    try:
        private.check_private_dir(place)
    except PrivateFileError:
        return False
    return True


def prepare(place: Path) -> bool:
    """Create the folder privately, or say that it is not ours to use.

    The temporary half sits where another account can create directories, so
    ownership and mode are checked rather than assumed.
    """
    try:
        private.ensure_private_dir(place)
    except PrivateFileError:
        return False
    return True


@dataclass(frozen=True)
class Request:
    id: str
    place: Path
    command: str
    payload: dict

    @property
    def path(self) -> Path:
        return self.place / f"{self.id}{REQUEST_SUFFIX}"

    @property
    def reply_path(self) -> Path:
        return self.place / f"{self.id}{REPLY_SUFFIX}"


def _write_private(path: Path, payload: dict) -> None:
    private.atomic_write_json(path, payload)


def ask(command, payload=None, request_id=None, root=None) -> Request:
    """Leave one request where the daemon will find it."""
    if command not in COMMANDS:
        raise ValueError("The daemon accepts call, listen, reply, and end only.")
    identifier = request_id or protocol.make_request_id()
    if not protocol.valid_request_id(identifier):
        raise ValueError("Use a request ID made by this bridge.")
    body = {
        "version": BODY_VERSION,
        "id": identifier,
        "command": command,
        "payload": payload if isinstance(payload, dict) else {},
    }
    for place in places(root):
        if not prepare(place):
            continue
        request = Request(id=identifier, place=place, command=command, payload=body["payload"])
        try:
            _write_private(request.path, body)
        except (OSError, PrivateFileError):
            continue
        return request
    raise ValueError(
        "The remote command could not leave a request. It can write to neither the "
        "TalkToMe data folder nor /tmp. Run it where it can write a private file, or "
        "set TALKTOME_REMOTE_DIR to a writable private folder."
    )


def answer(request: Request, result=None, error=None) -> None:
    _write_private(
        request.reply_path,
        {
            "version": BODY_VERSION,
            "id": request.id,
            "ok": error is None,
            "result": result,
            "error": error,
        },
    )


def reply_for(request: Request):
    """The daemon's answer, checked for ownership, type, bounds, ID, and version."""
    if not _owned_dir(request.place):
        return None
    path = request.reply_path
    try:
        info = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REPLY_BYTES:
        return None
    try:
        raw = private.read_private_bytes(path, MAX_REPLY_BYTES)
        body = json.loads(raw.decode("utf-8"))
    except (PrivateFileError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    if body.get("id") != request.id or body.get("version") != BODY_VERSION:
        return None
    return body


def _read(place: Path, path: Path, stale: float, now: float) -> Request | None:
    identifier = path.name[: -len(REQUEST_SUFFIX)]
    if not protocol.valid_request_id(identifier):
        return None
    try:
        info = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        return None
    if info.st_mode & 0o077:
        return None
    if info.st_size > MAX_REQUEST_BYTES:
        return None
    if now - info.st_mtime > stale:
        return None
    try:
        raw = private.read_private_bytes(path, MAX_REQUEST_BYTES)
        body = json.loads(raw.decode("utf-8"))
    except (PrivateFileError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(body, dict) or body.get("id") != identifier:
        return None
    if body.get("version") != BODY_VERSION:
        return None
    command = body.get("command")
    if command not in COMMANDS:
        return None
    payload = body.get("payload")
    return Request(
        id=identifier,
        place=place,
        command=str(command),
        payload=payload if isinstance(payload, dict) else {},
    )


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _scan(place: Path, suffixes=(REQUEST_SUFFIX, REPLY_SUFFIX)) -> list[Path]:
    """Matching entries, capped so a flood cannot become unbounded work."""
    paths = []
    try:
        with os.scandir(place) as entries:
            for entry in entries:
                if any(entry.name.endswith(suffix) for suffix in suffixes):
                    paths.append(Path(entry.path))
                if len(paths) >= MAX_SCAN_FILES:
                    break
    except OSError:
        return []
    return paths


def pending(root=None, stale=STALE, now=None) -> list[Request]:
    """Requests waiting for the daemon, oldest first, validated before use."""
    now = time.time() if now is None else now
    found = []
    for place in places(root):
        if not _owned_dir(place):
            continue
        for path in sorted(_scan(place, (REQUEST_SUFFIX,)), key=_mtime):
            request = _read(place, path, stale, now)
            if request is not None:
                found.append(request)
    return found


def _target(request: Request, suffix: str) -> Path | None:
    if not _owned_dir(request.place):
        return None
    path = request.place / f"{request.id}{suffix}"
    if path.parent != request.place:
        return None
    return path


def retire(request: Request) -> None:
    path = _target(request, REQUEST_SUFFIX)
    if path is None:
        return
    with contextlib.suppress(OSError):
        path.unlink()


def collect(request: Request) -> None:
    for suffix in (REQUEST_SUFFIX, REPLY_SUFFIX):
        path = _target(request, suffix)
        if path is None:
            continue
        with contextlib.suppress(OSError):
            path.unlink()


def sweep(root=None, stale=STALE, now=None) -> None:
    cutoff = (time.time() if now is None else now) - stale
    for place in places(root):
        if not _owned_dir(place):
            continue
        for path in _scan(place):
            with contextlib.suppress(OSError):
                if path.stat().st_mtime < cutoff:
                    path.unlink()
