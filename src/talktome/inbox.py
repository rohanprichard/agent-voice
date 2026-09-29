"""A way in that is a file rather than a connection.

Codex runs the commands an agent issues inside a sandbox. That sandbox blocks
connections to 127.0.0.1, so a command that can only speak HTTP cannot reach an app
that is plainly running: it concluded the app was closed, started a second copy, and
the second copy found the port taken and said so. The port message was the symptom;
asking over the network was the cause.

A file is not a connection. So the request became a file the app watches — and the
sandbox blocked that too, because it allows writes to the workspace and to the
temporary folder and to nothing else, so the app's own folder is refused outright.

Both refusals are the same mistake: choosing a meeting place without asking what the
sandbox permits. So the request is left where a sandboxed command can write and the
app is certain to look — the app's own folder when that is writable, and otherwise a
folder under `/tmp` named for the user. The app watches both, and answers beside
whichever one the request arrived in, because reading is not restricted and the
answer therefore always gets home.

`/tmp` rather than `$TMPDIR`, which the sandbox also allows, because it is one path
both sides agree on without having to agree on anything. A rendezvous that depends
on two processes having been started with the same environment is the same class of
bug as the one this replaces.
"""

import contextlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .config import data_dir

# How often the app looks for a new note. Short enough that a request feels
# immediate, long enough that an idle app is not spinning.
POLL = 0.15

# How long a note is worth honouring. Starting a sleeping app takes twenty
# seconds, and a command writes its request before it starts one, so this has to
# comfortably outlast that. What it removes is a note nobody is waiting for any
# more: left behind, it would ring the user the next time the app opened, for a
# command that finished long ago.
STALE = 180

REQUEST = ".request.json"
REPLY = ".reply.json"


def folder(root=None) -> Path:
    """The app's own folder for requests. Private, and not always writable."""
    return (root or data_dir()) / "requests"


def shared() -> Path:
    """A folder under `/tmp` that a sandboxed command is allowed to write.

    Named for the user so two accounts cannot collide, and checked by `prepare`,
    which refuses the folder outright if it turns out to belong to somebody else.
    """
    return Path("/tmp") / f"talktome-{os.getuid()}" / "requests"


def places(root=None) -> list[Path]:
    """Everywhere a request may be left, best first, and everywhere the app looks.

    The private half is skipped rather than fatal when it cannot even be named: an
    app that has never run here has no folder, and a sandboxed command cannot make
    one. That is precisely the case the other half exists for.
    """
    found = []
    with contextlib.suppress(OSError):
        found.append(folder(root))
    found.append(shared())
    return found


def prepare(place: Path) -> bool:
    """Create the folder privately, or report that it is not ours to use.

    The temporary half sits in a directory anyone can write to, so the check
    matters: `chmod` fails on a folder another account owns, and that failure is
    the answer. Everything else about this folder is unremarkable.
    """
    # Another account can make `/tmp/talktome-<uid>` a symlink to a folder of
    # ours. Refuse it before any chmod, and never follow a link when changing a
    # mode, so the change cannot land on the target.
    if _foreign(place.parent) or _foreign(place):
        return False
    try:
        place.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(place.parent, 0o700, follow_symlinks=False)
        os.chmod(place, 0o700, follow_symlinks=False)
    except (OSError, NotImplementedError):
        return False
    return owned(place)


def _foreign(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid()


def ready(root=None) -> list[Path]:
    """The folders that can actually be used, made ready to be watched."""
    return [place for place in places(root) if prepare(place)]


def owned(place: Path) -> bool:
    """Whether only this account can write the folder and the one above it.

    Checked on every pass, not once: under `/tmp`, another account can create
    the folder first, or replace it later, and plant a request or a symlink.
    """
    for path in (place.parent, place):
        try:
            info = path.lstat()
        except OSError:
            return False
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            return False
        if info.st_mode & 0o022:
            return False
    return True


@dataclass(frozen=True)
class Request:
    """One note, and the folder it was found in.

    The folder travels with the request because the answer has to go back beside
    it, and only that folder is known to be one the caller can read.
    """

    id: str
    place: Path
    command: str
    payload: dict

    @property
    def path(self) -> Path:
        return self.place / f"{self.id}{REQUEST}"

    @property
    def reply_path(self) -> Path:
        return self.place / f"{self.id}{REPLY}"


def _write(path: Path, payload):
    """Write a file whole, so a reader never opens half of one.

    A reply caught mid-write would read as a broken one, and the command would
    report a failure that did not happen.
    """
    # A new name, never followed: a planted symlink must not redirect the write.
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(json.dumps(payload))
    os.replace(temporary, path)


def ask(command, payload=None, root=None) -> Request:
    """Leave a request where the app will find it, and say where that is.

    Tried in order rather than chosen, because which one works depends on whether a
    sandbox is in the way, and nothing here can know that in advance. The app
    watches both, so the first folder that accepts the write is one the request
    will be found in.
    """
    for place in places(root):
        if not prepare(place):
            continue
        request = Request(id=uuid4().hex, place=place, command=command, payload=payload or {})
        try:
            _write(
                request.path,
                {"id": request.id, "command": request.command, "payload": request.payload},
            )
        except OSError:
            continue
        return request
    raise ValueError(
        "TalkToMe could not leave a request. This command can write to neither the "
        "app's folder nor /tmp, so it is running in a read-only sandbox. Run it "
        "with write access."
    )


def answer(request: Request, result=None, error=None):
    """Write the app's reply where the request came from.

    A refusal travels back the same way as a result: the command has no other way
    to hear about it.
    """
    _write(
        request.reply_path,
        {"id": request.id, "ok": error is None, "result": result, "error": error},
    )


def reply_for(request: Request):
    """The app's answer, or None while there is not one yet."""
    try:
        return json.loads(request.reply_path.read_text())
    except (OSError, ValueError):
        return None


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _read(place, path) -> Request | None:
    """One note, or None if it is not one. The name is trusted; the body is not."""
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict) or not body.get("command"):
        return None
    payload = body.get("payload")
    return Request(
        id=path.name[: -len(REQUEST)],
        place=place,
        command=str(body["command"]),
        payload=payload if isinstance(payload, dict) else {},
    )


def pending(root=None) -> list[Request]:
    """Requests waiting to be handled, oldest first."""
    found = []
    for place in places(root):
        if not owned(place):
            continue
        try:
            paths = list(place.glob(f"*{REQUEST}"))
        except OSError:
            continue
        for path in sorted(paths, key=_mtime):
            request = _read(place, path)
            if request is not None:
                found.append(request)
    return found


def retire(request: Request):
    """Remove a request, keeping the answer for whoever asked for it."""
    with contextlib.suppress(OSError):
        request.path.unlink()


def collect(request: Request):
    """Remove a request and its answer. For the side finished with both."""
    for suffix in (REQUEST, REPLY):
        with contextlib.suppress(OSError):
            (request.place / f"{request.id}{suffix}").unlink()


def sweep(root=None, stale=STALE, now=None):
    """Clear out anything left behind by a run that is long over.

    The app does this as it starts, so a note written for an app that never came up
    cannot ring the user later, and a command does it after giving up so a failed
    call leaves nothing in the folder.
    """
    cutoff = (now if now is not None else time.time()) - stale
    for place in places(root):
        if not owned(place):
            continue
        with contextlib.suppress(OSError):
            for path in place.iterdir():
                with contextlib.suppress(OSError):
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
