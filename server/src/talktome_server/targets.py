"""The projects a user can call into: recent Claude Code and Codex sessions on
this machine, and projects the user added by hand."""

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

LIMIT = 20
MAX_CODEX_READ = 400  # rollout files to read, newest first

# Sessions in these folders are throwaways, not projects.
TEMP_ROOTS = ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders"]


@dataclass
class Target:
    host: str  # "claude" or "codex"
    path: str
    last_active: float = 0.0
    session: str = ""  # the newest session in this project, if any
    joinable: bool = False
    project: str = ""
    id: str = field(default="")

    def __post_init__(self):
        self.id = self.id or target_id(self.host, self.path)
        self.project = self.project or Path(self.path).name

    def wire(self) -> dict:
        return {
            "target_id": self.id,
            "host": self.host,
            "project": self.project,
            "last_active": datetime.fromtimestamp(self.last_active, UTC).isoformat() if self.last_active else "",
            "joinable": self.joinable,
        }


def target_id(host: str, path: str) -> str:
    return "t_" + hashlib.sha256(f"{host}\0{path}".encode()).hexdigest()[:12]


def discover(home: Path, added: list[dict] | None = None) -> list[Target]:
    """The targets, newest first."""
    by_id: dict[str, Target] = {}

    def keep(t: Target) -> None:
        if not usable(t.path):
            return
        old = by_id.get(t.id)
        if old and t.last_active <= old.last_active:
            return
        by_id[t.id] = t

    for t in claude(home) + codex(home):
        keep(t)
    for a in added or []:
        path = os.path.abspath(os.path.expanduser(a["path"]))
        if target_id(a["host"], path) not in by_id:
            keep(Target(host=a["host"], path=path))
    found = sorted(by_id.values(), key=lambda t: (-t.last_active, t.id))
    return found[:LIMIT]


def usable(path: str) -> bool:
    if not path or any(path == root or path.startswith(root + "/") for root in TEMP_ROOTS):
        return False
    return os.path.isdir(path)


def claude(home: Path) -> list[Target]:
    """~/.claude/projects has one folder for each project, and each session file names its folder in `cwd`."""
    root = home / ".claude" / "projects"
    found = []
    try:
        folders = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return []
    for folder in folders:
        newest, modified = _newest(folder, ".jsonl")
        if not newest:
            continue
        cwd, session = _claude_session(newest)
        if cwd:
            found.append(Target(host="claude", path=cwd, session=session, last_active=modified))
    return found


def _claude_session(path: Path) -> tuple[str, str]:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(50), f):
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if isinstance(data, dict) and data.get("cwd"):
                    return data["cwd"], data.get("sessionId", "")
    except OSError:
        pass
    return "", ""


def codex(home: Path) -> list[Target]:
    """The first line of each rollout file in ~/.codex/sessions names its session and folder."""
    root = home / ".codex" / "sessions"
    files = [p for p in root.rglob("rollout-*.jsonl")] if root.is_dir() else []
    # Rollout names start with their date and time, so name order is time order.
    files.sort(key=lambda p: p.name, reverse=True)
    found = []
    for path in files[:MAX_CODEX_READ]:
        session, cwd = _codex_session(path)
        if cwd:
            try:
                found.append(Target(host="codex", path=cwd, session=session, last_active=path.stat().st_mtime))
            except OSError:
                continue
    return found


def _codex_session(path: Path) -> tuple[str, str]:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            first = json.loads(f.readline())
    except (OSError, ValueError):
        return "", ""
    if not isinstance(first, dict) or first.get("type") != "session_meta":
        return "", ""
    payload = first.get("payload") or {}
    return payload.get("id", ""), payload.get("cwd", "")


def _newest(folder: Path, suffix: str) -> tuple[Path | None, float]:
    newest, modified = None, 0.0
    try:
        for entry in folder.iterdir():
            if entry.is_file() and entry.name.endswith(suffix):
                mtime = entry.stat().st_mtime
                if mtime > modified:
                    newest, modified = entry, mtime
    except OSError:
        pass
    return newest, modified
