"""Private files for the remote bridge.

Credentials, relay metadata, the command journal, and the remote inbox all hold
secrets or identifiers a local user should not have to trust anyone else with.
Every file here is created whole, with mode ``0600``, and replaced atomically so
a reader never opens half a file.

A path in this module may be a user override, so nothing here trusts a
directory merely because it exists. The target is refused when it is a symlink
or belongs to another account, and the parent directory is never chmodded: an
override can point below ``/tmp`` or a user folder, and tightening a directory
this process does not own would be both a privilege error and a surprise.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import stat
from pathlib import Path

PRIVATE_FILE = 0o600
PRIVATE_DIR = 0o700

# Read in bounded chunks so an oversized file is refused before it is read whole.
READ_CHUNK = 64 * 1024
MAX_JSON_BYTES = 256 * 1024


class PrivateFileError(ValueError):
    """A private file is missing, unreadable, or not private enough."""


def _lstat(path: Path):
    try:
        return path.lstat()
    except OSError:
        return None


def ensure_private_dir(path: Path) -> None:
    """Create and verify a directory only the current user can enter.

    Only the target is created and checked. The parent is left exactly as it
    was, because a private-path override may sit in a shared location where this
    process has no business changing permissions.
    """
    path = Path(path)
    parent_info = _lstat(path.parent)
    if parent_info is not None and stat.S_ISLNK(parent_info.st_mode):
        raise PrivateFileError(f"{path.parent.name} is a symlink.")
    info = _lstat(path)
    if info is not None and stat.S_ISLNK(info.st_mode):
        raise PrivateFileError(f"{path.name} is a symlink.")
    if info is None:
        try:
            path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR)
        except OSError as exc:
            raise PrivateFileError(f"{path.name} could not be created.") from exc
        info = _lstat(path)
    parent_info = _lstat(path.parent)
    if (
        parent_info is None
        or stat.S_ISLNK(parent_info.st_mode)
        or not stat.S_ISDIR(parent_info.st_mode)
        or parent_info.st_uid != os.getuid()
    ):
        raise PrivateFileError(f"{path.parent.name} is not a usable directory.")
    if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PrivateFileError(f"{path.name} is not a directory.")
    if info.st_uid != os.getuid():
        raise PrivateFileError(f"{path.name} is owned by another account.")
    try:
        os.chmod(path, PRIVATE_DIR)
    except OSError as exc:
        raise PrivateFileError(f"{path.name} could not be made private.") from exc
    info = _lstat(path)
    if info is None or info.st_mode & 0o077:
        raise PrivateFileError(f"{path.name} is not private enough.")


def check_private_dir(path: Path) -> None:
    """Refuse a directory that is not ours and not private."""
    path = Path(path)
    info = _lstat(path)
    if info is None:
        raise PrivateFileError(f"{path.name} is not readable.")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PrivateFileError(f"{path.name} is not a private directory.")
    if info.st_uid != os.getuid():
        raise PrivateFileError(f"{path.name} is owned by another account.")
    if info.st_mode & 0o077:
        raise PrivateFileError(f"{path.name} is not private enough.")


def check_private_file(path: Path) -> None:
    """Refuse a private file another account can read.

    The file is written ``0600``; this is the check that notices when a copy, a
    backup tool, or a curious umask changed that after the fact.
    """
    path = Path(path)
    info = _lstat(path)
    if info is None:
        raise PrivateFileError(f"{path.name} is not readable.")
    if stat.S_ISLNK(info.st_mode):
        raise PrivateFileError(f"{path.name} is a symlink.")
    if not stat.S_ISREG(info.st_mode):
        raise PrivateFileError(f"{path.name} is not a regular file.")
    if info.st_uid != os.getuid():
        raise PrivateFileError(f"{path.name} is owned by another account.")
    if info.st_mode & 0o077:
        raise PrivateFileError(
            f"{path.name} is readable by other users. Run chmod 600 {path}."
        )


def read_private_bytes(path: Path, max_bytes: int) -> bytes:
    """Read one bounded private regular file without following a symlink.

    Ownership, type, and mode are checked on the open descriptor, so a path
    swapped between the check and the read cannot redirect it. The size is
    checked before the read, so an oversized file is refused, not swallowed.
    """
    path = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PrivateFileError(f"{path.name} is not readable.") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise PrivateFileError(f"{path.name} is not a regular file.")
        if info.st_uid != os.getuid():
            raise PrivateFileError(f"{path.name} is owned by another account.")
        if info.st_mode & 0o077:
            raise PrivateFileError(
                f"{path.name} is readable by other users. Run chmod 600 {path}."
            )
        if info.st_size > max_bytes:
            raise PrivateFileError(f"{path.name} is too large.")
        data = bytearray()
        while True:
            chunk = os.read(descriptor, min(READ_CHUNK, max_bytes + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                raise PrivateFileError(f"{path.name} is too large.")
        return bytes(data)
    finally:
        os.close(descriptor)


def read_private_json(path: Path, *, max_bytes: int = MAX_JSON_BYTES):
    """Read one bounded private JSON document, or raise for any problem."""
    raw = read_private_bytes(path, max_bytes)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PrivateFileError(f"{path.name} is not valid JSON.") from exc


def read_json(path: Path, default=None):
    """Read a private JSON document, or hand back the default when it is not one."""
    try:
        return read_private_json(path)
    except PrivateFileError:
        return default


def _fsync_dir(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Some platforms refuse fsync on a directory. The rename is still atomic,
        # so this is a durability improvement, not a correctness requirement.
        pass
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace a file with a complete private payload.

    The temporary name is unique and created with ``O_EXCL``, so two writers
    cannot share it and a planted file cannot be followed. The file is fsynced,
    renamed into place, and its containing directory is fsynced so the
    replacement survives a crash.
    """
    path = Path(path)
    ensure_private_dir(path.parent)
    descriptor = None
    temporary = None
    for _ in range(16):
        candidate = path.parent / f".{path.name}.{secrets.token_hex(12)}.tmp"
        try:
            descriptor = os.open(
                candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE
            )
        except FileExistsError:
            continue
        except OSError as exc:
            raise PrivateFileError(f"{path.name} could not be written.") from exc
        temporary = candidate
        break
    if descriptor is None or temporary is None:
        raise PrivateFileError(f"{path.name} could not be written.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), PRIVATE_FILE)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def atomic_write_json(path: Path, payload) -> None:
    """Replace a file with a private, complete JSON document."""
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    atomic_write_bytes(path, encoded)
