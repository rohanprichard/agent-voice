"""Run the talktome command for the Hermes plugin.

This file has no Hermes imports, so the TalkToMe tests can load it directly. The
plugin runs in Hermes's own Python, which cannot import the talktome package, so
every call goes through the command. The command already knows whether this
computer is the Mac or a server paired with it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from pathlib import Path

LISTEN_TIMEOUT = 25
# A ring lasts 30 seconds, and a remote call waits up to 60 for the laptop.
CALL_TIMEOUT = 100
REPLY_TIMEOUT = 60


class TalkToMeError(RuntimeError):
    pass


def speech_seconds(text: str) -> float:
    """About how long the Mac takes to say this, with time to start the audio.

    Ending a call stops playback at once, so a goodbye needs this much time
    before the hang-up. Speech runs at about 14 characters a second.
    """
    return min(20.0, 1.5 + len(text) / 14)


def find_command(env=os.environ) -> str | None:
    configured = (env.get("TALKTOME_COMMAND") or "").strip()
    if configured:
        return configured
    found = shutil.which("talktome")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "talktome"
    return str(local) if local.is_file() else None


def first_json(output: str) -> dict:
    """The first JSON object in the output. remote-status also prints inbox lines."""
    start = output.find("{")
    if start < 0:
        raise TalkToMeError("talktome printed no result.")
    try:
        value, _ = json.JSONDecoder().raw_decode(output[start:])
    except ValueError as exc:
        raise TalkToMeError("talktome printed a result that is not JSON.") from exc
    if not isinstance(value, dict):
        raise TalkToMeError("talktome printed a result that is not an object.")
    return value


def remote_setting(value: str | None) -> bool | None:
    value = (value or "auto").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


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


class TalkToMeClient:
    def __init__(self, command: str, remote: bool):
        self.command = command
        self.remote = remote

    @classmethod
    async def discover(cls, env=os.environ) -> TalkToMeClient:
        command = find_command(env)
        if not command:
            raise TalkToMeError(
                "The talktome command is not installed on this computer. "
                "Install it with `uv tool install git+https://github.com/rohanprichard/talktome`."
            )
        remote = remote_setting(env.get("TALKTOME_REMOTE"))
        if remote is None:
            status = first_json(await run(command, ["remote-status"], timeout=15))
            remote = bool(status.get("configured")) and status.get("role") == "agent"
        return cls(command, remote)

    def _args(self, *args: str) -> list[str]:
        return ["--remote", *args] if self.remote else list(args)

    async def _json(self, args: list[str], timeout: float) -> dict:
        return first_json(await run(self.command, self._args(*args), timeout=timeout))

    async def call(self, thread: str, greeting: str, name: str | None) -> dict:
        args = ["call", "--agent", "hermes", "--thread", thread, f"--greeting={greeting}"]
        if not self.remote:
            args += ["--connection", "cooperative"]
        if name:
            args.append(f"--name={name}")
        return await self._json(args, CALL_TIMEOUT)

    async def listen(self, thread: str, after: int) -> dict:
        args = ["listen", "--thread", thread, "--after", str(after), "--timeout", str(LISTEN_TIMEOUT)]
        return await self._json(args, LISTEN_TIMEOUT + 45)

    async def reply(self, thread, call_id, turn_id, item_id, text, final) -> dict:
        args = [
            "reply",
            "--thread", thread,
            "--call-id", call_id,
            "--turn-id", turn_id,
            "--item-id", item_id,
            f"--text={text}",
        ]
        if not final:
            args.append("--progress")
        return await self._json(args, REPLY_TIMEOUT)

    async def end(self) -> dict:
        return await self._json(["end"], REPLY_TIMEOUT)


async def run(command: str, args: list[str], timeout: float) -> str:
    process = await asyncio.create_subprocess_exec(
        command,
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    name = next((arg for arg in args if not arg.startswith("-")), "command")
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException as exc:
        process.kill()
        await process.wait()
        if isinstance(exc, TimeoutError):
            raise TalkToMeError(f"talktome {name} did not answer in {timeout:g} seconds.") from None
        raise
    if process.returncode:
        message = err.decode(errors="replace").strip().splitlines()
        raise TalkToMeError(message[-1] if message else f"talktome {name} failed.")
    return out.decode(errors="replace")
