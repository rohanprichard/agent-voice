import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .attach import AttachedAdapter, rollout_path
from .claude_resume import ClaudeResumeAdapter
from .external_adapters import create_external_adapter
from .managed import CODEX_SESSION_ID

logger = logging.getLogger(__name__)

MAX_CALLS = 500
# How many days a saved transcript is kept. Off saves none.
TRANSCRIPT_DAYS = {"off": 0, "7d": 7, "30d": 30}
PRUNE_EVERY = 24 * 60 * 60
CALLBACK_PREFIX = "[TalkToMe] The user called you back by voice. Reply by voice, briefly."
CODEX_CLOSED = "That Codex session is closed."
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def now():
    return datetime.now(UTC)


def write_private(path, text):
    for folder in (path.parent.parent, path.parent):
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def callback_reason(entry):
    """Why this call cannot be called back, or None when it can."""
    agent = entry.get("agent")
    session = entry.get("session_id") or ""
    if agent == "generic":
        return "A generic session gives TalkToMe no way to reach it."
    if agent == "codex" and not CODEX_SESSION_ID.fullmatch(session):
        return "This call has no Codex thread id."
    if agent == "claude" and not UUID.fullmatch(session):
        return "This call used a connection id, not a Claude Code session id."
    if agent not in {"codex", "claude", "hermes", "openclaw"} or not session:
        return "This call has no session to call back."
    return None


class CallHistory:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "calls.jsonl"
        self.transcripts = directory / "transcripts"
        self.settings_path = directory / "settings.json"
        self.records = []
        self.current = None
        self.mode = "off"
        self.load()

    def load(self):
        try:
            settings = json.loads(self.settings_path.read_text())
            if settings.get("transcripts") in TRANSCRIPT_DAYS:
                self.mode = settings["transcripts"]
        except (OSError, ValueError, AttributeError):
            pass
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines[-MAX_CALLS:]:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                continue
            # The app stopped while this call was still ringing.
            if entry.get("outcome") is None:
                entry["outcome"] = "missed"
            self.records.append(entry)
        self.prune()

    def save(self):
        write_private(self.path, "".join(json.dumps(entry) + "\n" for entry in self.records))

    def get(self, call_id):
        return next((entry for entry in self.records if entry["id"] == call_id), None)

    def list(self):
        return [
            {**entry, "callback_reason": callback_reason(entry)} for entry in reversed(self.records)
        ]

    def record(self, event, managed, options=None):
        # The history must never break a call.
        try:
            self._record(event, managed, options)
        except Exception:
            logger.exception("The call history could not be saved.")

    def _record(self, event, managed, options):
        stamp = now().isoformat()
        entry = self.get(self.current) if self.current else None
        if event in {"ringing", "callback", "failed"}:
            options = options or managed.options or {}
            session = options.get("thread_id")
            agent = options.get("agent") or "generic"
            entry = {
                "id": str(uuid4()),
                "agent": agent,
                "session_id": session,
                "name": (managed.ring or {}).get("name") or options.get("thread_name") or "A session",
                "cwd": options.get("cwd"),
                "started_at": stamp,
                "answered_at": None,
                "ended_at": None,
                "duration": None,
                "outcome": None,
                "callback": event == "callback",
                "call_id": None,
                "transcript": False,
            }
            if event == "failed":
                entry.update(outcome="failed", ended_at=stamp, error=managed.error)
            else:
                self.current = entry["id"]
            if event == "callback":
                entry.update(outcome="answered", answered_at=stamp, call_id=managed.room.call_id)
            self.records.append(entry)
            for old in self.records[:-MAX_CALLS]:
                self._drop_transcript(old)
            del self.records[:-MAX_CALLS]
        elif entry is None:
            return
        elif event == "answered":
            entry.update(outcome="answered", answered_at=stamp, ended_at=None, call_id=managed.room.call_id)
        elif event in {"declined", "missed"}:
            if entry["outcome"] is not None:
                return
            entry.update(outcome=event, ended_at=stamp)
            self.current = None
        elif event == "ended":
            self.current = None
            entry["ended_at"] = stamp
            if entry["outcome"] is None:
                entry["outcome"] = "missed"
            if entry["answered_at"]:
                started = datetime.fromisoformat(entry["answered_at"])
                entry["duration"] = round((now() - started).total_seconds())
                self._save_transcript(entry, managed.room.messages)
        self.save()

    def _save_transcript(self, entry, messages):
        if self.mode == "off" or not entry.get("call_id"):
            return
        lines = [
            {"role": item.get("role"), "name": item.get("name"), "text": item.get("text"), "time": item.get("time")}
            for item in messages
            if item.get("call_id") == entry["call_id"] and item.get("text")
        ]
        if lines:
            write_private(self.transcripts / f"{entry['id']}.json", json.dumps(lines))
            entry["transcript"] = True

    def _drop_transcript(self, entry):
        entry["transcript"] = False
        (self.transcripts / f"{entry['id']}.json").unlink(missing_ok=True)

    def transcript(self, call_id):
        entry = self.get(call_id)
        if not entry or not entry.get("transcript"):
            return None
        try:
            return json.loads((self.transcripts / f"{call_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def mark_closed(self, call_id, closed):
        entry = self.get(call_id)
        if entry and bool(entry.get("closed")) != closed:
            entry["closed"] = closed
            self.save()

    def delete(self, call_id):
        entry = self.get(call_id)
        if not entry:
            return False
        self._drop_transcript(entry)
        self.records.remove(entry)
        if self.current == call_id:
            self.current = None
        self.save()
        return True

    def clear(self):
        for entry in self.records:
            self._drop_transcript(entry)
        self.records.clear()
        self.current = None
        self.save()

    def set_mode(self, mode):
        if mode not in TRANSCRIPT_DAYS:
            raise HTTPException(400, "Select Off, 7 days, or 30 days.")
        self.mode = mode
        write_private(self.settings_path, json.dumps({"transcripts": mode}))
        self.prune()

    def prune(self):
        days = TRANSCRIPT_DAYS[self.mode]
        cutoff = now() - timedelta(days=days)
        kept = set()
        changed = False
        for entry in self.records:
            if not entry.get("transcript"):
                continue
            ended = entry.get("ended_at") or entry.get("started_at")
            if not days or not ended or datetime.fromisoformat(ended) < cutoff:
                self._drop_transcript(entry)
                changed = True
            else:
                kept.add(f"{entry['id']}.json")
        # A transcript whose call left the history is removed with it.
        if self.transcripts.is_dir():
            for path in self.transcripts.iterdir():
                if path.name not in kept:
                    path.unlink(missing_ok=True)
        if changed:
            self.save()

    async def prune_daily(self):
        while True:
            await asyncio.sleep(PRUNE_EVERY)
            try:
                self.prune()
            except OSError:
                logger.exception("Old call transcripts could not be removed.")


def prefix_first_turn(adapter, on_closed=None):
    """Tell the agent, on the first turn only, that the user called it."""
    original = adapter.run

    async def run(text, emit, approve):
        adapter.run = original
        try:
            return await original(f"{CALLBACK_PREFIX}\n\n{text}", emit, approve)
        except (ValueError, RuntimeError) as exc:
            if on_closed is None:
                raise
            on_closed()
            # `codex queue` refuses a thread with no owner, or queues the message
            # and no terminal ever reads it.
            message = (
                CODEX_CLOSED if isinstance(exc, ValueError) else f"{exc} The session may be closed."
            )
            raise RuntimeError(f"{message} Open it in Terminal from Calls.") from None

    adapter.run = run


async def call_back(managed, history, call_id):
    """Start a call the user placed. There is no ring: the user is already here."""
    entry = history.get(call_id)
    if not entry:
        raise HTTPException(404, "That call is not in the history.")
    reason = callback_reason(entry)
    if reason:
        raise HTTPException(409, reason)
    agent, session, name = entry["agent"], entry["session_id"], entry["name"]
    on_closed = None
    async with managed.lock:
        directory = managed._project(entry.get("cwd") or "")
        if agent == "codex":
            if await asyncio.to_thread(rollout_path, session) is None:
                history.mark_closed(call_id, True)
                raise HTTPException(409, {"message": CODEX_CLOSED, "action": "open_terminal"})
            adapter = AttachedAdapter(session, str(directory))

            def on_closed():
                history.mark_closed(call_id, True)
        elif agent == "claude":
            adapter = ClaudeResumeAdapter(session, str(directory))
        else:
            adapter = create_external_adapter(agent, session, str(directory))
        await managed._begin(
            adapter,
            getattr(adapter, "agent_name", "Agent"),
            {
                "provider": "attach",
                "agent": agent,
                "connection": "auto",
                "thread_id": session,
                "thread_name": name,
                "cwd": str(directory),
                "callback": True,
            },
        )
        history.mark_closed(call_id, False)
        await managed.room.start()
        history.record("callback", managed)
        prefix_first_turn(adapter, on_closed)
        await managed.greet(f"Calling {name}.")
        managed.status = "ready"
        await managed.changed()
        return managed.snapshot()


def terminal_argv(cwd, session):
    # AppleScript hands the string to a shell, so both parts are quoted.
    command = f"cd {shlex.quote(cwd)} && codex resume {shlex.quote(session)}"
    return [
        "/usr/bin/osascript",
        "-e", "on run argv",
        "-e", 'tell application "Terminal"',
        "-e", "activate",
        "-e", "do script (item 1 of argv)",
        "-e", "end tell",
        "-e", "end run",
        command,
    ]


def open_in_terminal(entry, run=subprocess.run):
    session = entry.get("session_id") or ""
    cwd = entry.get("cwd") or ""
    if entry.get("agent") != "codex" or not CODEX_SESSION_ID.fullmatch(session):
        raise HTTPException(409, "Only a Codex session opens in Terminal.")
    if not Path(cwd).is_dir():
        raise HTTPException(400, "The project folder of that session is gone.")
    try:
        run(terminal_argv(cwd, session), check=True, capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(500, f"Terminal did not open. {exc}") from None


class TranscriptSetting(BaseModel):
    transcripts: str


def call_routes(managed, history):
    router = APIRouter(prefix="/v1/calls")

    @router.get("")
    async def calls():
        return {"calls": history.list(), "transcripts": history.mode}

    @router.delete("")
    async def clear():
        history.clear()
        return {"ok": True}

    @router.post("/settings")
    async def settings(body: TranscriptSetting):
        history.set_mode(body.transcripts)
        return {"transcripts": history.mode}

    @router.delete("/{call_id}")
    async def delete(call_id: str):
        if not history.delete(call_id):
            raise HTTPException(404, "That call is not in the history.")
        return {"ok": True}

    @router.get("/{call_id}/transcript")
    async def transcript(call_id: str):
        messages = history.transcript(call_id)
        if messages is None:
            raise HTTPException(404, "That call has no saved transcript.")
        return {"messages": messages}

    @router.post("/{call_id}/callback")
    async def callback(call_id: str):
        return await call_back(managed, history, call_id)

    @router.post("/{call_id}/terminal")
    async def terminal(call_id: str):
        entry = history.get(call_id)
        if not entry:
            raise HTTPException(404, "That call is not in the history.")
        await asyncio.to_thread(open_in_terminal, entry)
        return {"ok": True}

    return router
