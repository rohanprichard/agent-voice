"""Run an agent host for a call from the user: one process for each spoken
turn, in the project's folder, in one session."""

import asyncio
import json
import os
import re
import shutil
from pathlib import Path

VOICE_PROMPT = (
    "You are in a live voice call with the user through talktome. The user hears your "
    "reply as speech, and you hear the user as text. Answer in one or two short spoken sentences "
    "unless the user asks for detail. Do not use markdown, lists, code, file paths, or URLs. "
    "If a request needs more than about a minute of work, say what you will do, do it, and give "
    "the result in one or two sentences."
)

# Set for each host process a call runs. The talktome plugin's hooks see it and stay out of the way.
RUNNER_ENV = "TALKTOME_CALL_RUN"

PERMISSION_TOOL = "mcp__talktome_permission__approve"

# Where people install agent commands. A process started over SSH often has none of them on PATH.
USER_BIN_DIRS = ["~/.local/bin", "~/.npm-global/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin"]


class RunError(Exception):
    pass


def find(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for folder in USER_BIN_DIRS:
        path = Path(os.path.expanduser(folder)) / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise RunError(f"the {name} command was not found on this machine")


def new_runner(host: str, folder: str, mode: str, session: str):
    resume = "" if mode == "new" else session
    if host == "claude":
        return Claude(folder, resume)
    if host == "codex":
        return Codex(folder, resume)
    raise RunError(f"calls into {host} are not supported")


async def run(name: str, folder: str, args: list[str], stdin: str) -> bytes:
    path = find(name)
    proc = await asyncio.create_subprocess_exec(
        path,
        *args,
        cwd=folder,
        env={**os.environ, RUNNER_ENV: "1"},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await proc.communicate(stdin.encode())
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode != 0:
        lines = err.decode(errors="replace").strip().splitlines()
        raise RunError(f"{name} failed: {lines[-1] if lines else proc.returncode}")
    return out


class Claude:
    """Runs `claude -p` for each turn. The first turn of a call that continues a
    session forks it, so a terminal that has the session open is not disturbed."""

    def __init__(self, folder: str, resume: str = ""):
        self.folder = folder
        self.resume = resume
        self.session = ""
        self.call_id = ""
        self.approver = ""

    def bind_call(self, call_id: str, approver: str) -> None:
        """Ask the user in this call before a tool that needs permission runs."""
        self.call_id, self.approver = call_id, approver

    def permission_args(self) -> list[str]:
        if not self.call_id or not self.approver:
            return []
        config = {
            "mcpServers": {
                "talktome_permission": {
                    "command": self.approver,
                    "args": ["permission-mcp"],
                    "env": {"TALKTOME_CALL_ID": self.call_id},
                }
            }
        }
        return ["--permission-prompt-tool", PERMISSION_TOOL, "--mcp-config", json.dumps(config)]

    async def turn(self, text: str) -> str:
        args = ["-p", "--output-format", "json", "--append-system-prompt", VOICE_PROMPT, *self.permission_args()]
        if self.session:
            args += ["--resume", self.session]
        elif self.resume:
            args += ["--resume", self.resume, "--fork-session"]
        out = await run("claude", self.folder, args, text)
        try:
            result = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise RunError("Claude Code sent a reply that is not JSON") from None
        self.session = result.get("session_id") or self.session
        if result.get("is_error"):
            raise RunError(f"Claude Code failed: {result.get('result')}")
        return result.get("result", "")


class Codex:
    """Runs `codex exec` for each turn, and resumes its thread on later turns.
    Codex resumes a session in place; it has no fork for exec."""

    def __init__(self, folder: str, resume: str = ""):
        self.folder = folder
        self.resume = resume
        self.session = ""

    async def turn(self, text: str) -> str:
        thread = self.session or self.resume
        if thread:
            args = ["exec", "resume", thread, "--json", "--skip-git-repo-check", "-"]
        else:
            args = ["exec", "--json", "--skip-git-repo-check", "-"]
        if not self.session:
            text = VOICE_PROMPT + "\n\n" + text
        out = await run("codex", self.folder, args, text)
        reply = ""
        for line in out.decode(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type")
            item = event.get("item") or {}
            if kind == "thread.started" and event.get("thread_id"):
                self.session = event["thread_id"]
            elif kind == "item.completed" and item.get("type") == "agent_message":
                reply = item.get("text", "")
            elif kind in ("error", "turn.failed"):
                raise RunError(f"Codex failed: {event.get('message')}")
        self.session = self.session or thread
        if not reply:
            raise RunError("Codex gave no reply")
        return reply


_FENCE = re.compile(r"```.*?(```|$)", re.DOTALL)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|`)")


def speakable(text: str) -> str:
    """Text as it should sound. Markdown and code do not read aloud well."""
    text = _FENCE.sub(" ", text or "")
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("a link", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    text = _EMPHASIS.sub("", text)
    return " ".join(text.split())
