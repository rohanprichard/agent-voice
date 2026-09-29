"""Join an agent session that is already running somewhere else.

Codex allows one writer per thread. When a terminal owns the thread, that terminal
is the writer, and a second process can neither start a turn nor ask the owner to
stop one. Two things still work, and they are the whole of this module:

* `codex queue --thread <id> --message <text>` delivers a message into a held
  thread without becoming its writer.
* The thread's rollout file is append-only JSON Lines. It is the only public view
  of a thread another process owns, and a byte offset is enough to read only what
  is new.

This is why an attached call cannot interrupt the agent's work the way a managed
call can: there is no way to ask a thread's owner to stop. It can only stop
speaking, and wait for the queued message to be picked up.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import select
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

from .agents import find_command
from .codex_queue import CodexQueueTransport, QueueTransportUnsupported

SESSIONS = Path(".codex") / "sessions"


def session_name(thread_id: str, root: Path | None = None) -> str | None:
    """Get a Codex session name from its local database, if it exists."""
    directory = root or Path.home() / ".codex"
    databases = sorted(directory.glob("state_*.sqlite"), reverse=True)
    for path in databases:
        try:
            with contextlib.closing(
                sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
            ) as database:
                row = database.execute(
                    "SELECT name, title FROM threads WHERE id = ?", (thread_id,)
                ).fetchone()
        except sqlite3.Error:
            continue
        if row:
            name = " ".join((row[0] or "").split())
            title = " ".join((row[1] or "").split())
            return (name or title)[:80] or None
    return None


def rollout_path(thread_id: str, root: Path | None = None) -> Path | None:
    """The newest rollout file for a thread, or None if it has none yet."""
    directory = root or Path.home() / SESSIONS
    if not directory.is_dir():
        return None
    matches = sorted(directory.rglob(f"*{thread_id}*.jsonl"))
    return matches[-1] if matches else None


class Rollout:
    """Read a thread's rollout file as new records arrive.

    A byte offset rather than a line count, because the file grows while it is
    being read and a partly written last line must not be parsed.
    """

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0

    @classmethod
    def open(cls, thread_id: str, root: Path | None = None) -> Rollout | None:
        path = rollout_path(thread_id, root)
        return cls(path) if path else None

    def skip_history(self) -> None:
        """Start from the end, so a call does not replay the whole conversation."""
        try:
            self.offset = self.path.stat().st_size
        except OSError:
            self.offset = 0

    def read_new(self) -> list[dict]:
        """Every complete record written since the last read."""
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                data = handle.read()
        except OSError:
            return []
        if not data:
            return []
        # Only advance past whole lines: a record still being written would parse
        # as a truncated JSON object.
        complete = data.rfind(b"\n")
        if complete < 0:
            return []
        self.offset += complete + 1
        records = []
        for line in data[:complete].decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                # A record this version does not understand is not a reason to
                # stop following the thread.
                continue
        return records


class RolloutWakeup:
    """Wake the reader on a file write. Keep polling as a fallback."""

    def __init__(self):
        self.event = asyncio.Event()
        self.queue = None
        self.descriptor = None
        self.loop = None

    def start(self, path):
        if not hasattr(select, "kqueue"):
            return
        self.loop = asyncio.get_running_loop()
        try:
            self.descriptor = os.open(path, os.O_RDONLY)
            self.queue = select.kqueue()
            self.queue.control([
                select.kevent(
                    self.descriptor, filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                    fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND
                    | select.KQ_NOTE_RENAME | select.KQ_NOTE_DELETE,
                ),
            ], 0, 0)
            self.loop.add_reader(self.queue.fileno(), self._ready)
        except (OSError, ValueError, NotImplementedError):
            self.close()

    def _ready(self):
        try:
            events = self.queue.control(None, 8, 0)
            if any(event.fflags & (select.KQ_NOTE_RENAME | select.KQ_NOTE_DELETE) for event in events):
                self.close()
        except (OSError, ValueError):
            self.close()
        self.event.set()

    async def wait(self, timeout):
        if self.queue is None:
            await asyncio.sleep(timeout)
            return
        try:
            await asyncio.wait_for(self.event.wait(), timeout)
        except TimeoutError:
            pass
        self.event.clear()

    def close(self):
        if self.queue is not None:
            if self.loop:
                self.loop.remove_reader(self.queue.fileno())
            self.queue.close()
            self.queue = None
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None


def completed_item(record: dict) -> dict | None:
    """The item a rollout record reports as completed, if it reports one."""
    payload = record.get("payload") or {}
    if record.get("type") != "event_msg" or payload.get("type") != "item_completed":
        return None
    item = payload.get("item")
    return item if isinstance(item, dict) else None


def spoken_message(record: dict) -> dict | None:
    """The speakable message in a record, or None.

    Only agent messages are spoken. Reasoning, command output, and file changes are
    in the same stream and are none of them things to read aloud.
    """
    item = completed_item(record)
    if not item or item.get("type") != "AgentMessage":
        return None
    text = "".join(
        part.get("text", "")
        for part in item.get("content") or []
        if isinstance(part, dict) and part.get("type") in {"Text", "text", "output_text"}
    ).strip()
    if not text:
        return None
    return {
        "id": item.get("id") or "",
        "text": text,
        "kind": item.get("phase") or "message",
    }


def user_message_text(record: dict) -> str | None:
    """Get the user's text from a completed message."""
    item = completed_item(record)
    if not item or item.get("type") != "UserMessage":
        return None
    return "".join(
        part.get("text", "")
        for part in item.get("content") or []
        if isinstance(part, dict) and part.get("type") in {"Text", "text"}
    ).strip()


def tool_activity(record: dict) -> dict | None:
    """What the agent is doing with a tool, as one short phrase for the interface."""
    item = completed_item(record)
    if not item:
        return None
    kind = item.get("type")
    if kind == "CommandExecution":
        parsed = item.get("parsed_cmd")
        if isinstance(parsed, str):
            command = parsed.strip()
        elif isinstance(parsed, list):
            command = " · ".join(
                entry["cmd"].strip()
                for entry in parsed
                if isinstance(entry, dict)
                and isinstance(entry.get("cmd"), str)
                and entry["cmd"].strip()
            )
        else:
            command = ""
        if not command:
            raw = item.get("command")
            if isinstance(raw, str):
                command = raw.strip()
            elif isinstance(raw, list):
                command = " ".join(
                    part.strip() for part in raw if isinstance(part, str) and part.strip()
                )
        if not command:
            return None
        return {"id": item.get("id") or "", "status": "done", "text": f"Ran {command}"}
    if kind == "FileChange":
        changes = item.get("changes") or {}
        count = len(changes) if isinstance(changes, dict) else 0
        return {
            "id": item.get("id") or "",
            "status": "done",
            "text": f"Edited {count} file{'s' if count != 1 else ''}",
        }
    return None


def turn_finished(record: dict) -> dict | None:
    """The finished turn's id and final message, when a turn just completed."""
    payload = record.get("payload") or {}
    if record.get("type") != "event_msg" or payload.get("type") != "task_complete":
        return None
    return {
        "turn_id": payload.get("turn_id") or "",
        "last_message": (payload.get("last_agent_message") or "").strip(),
    }


def queue_argv(binary: str, thread_id: str, message: str) -> list[str]:
    """The command that delivers a message without becoming the thread's writer."""
    # One argument, so a message that starts with "-" is not read as a flag.
    return [binary, "queue", "--thread", thread_id, f"--message={message}"]


def queue_message(thread_id: str, message: str, cwd: str | None = None, run=subprocess.run):
    """Deliver a message into a thread this process does not own."""
    # Asked of the user's login shell, not of this process: a packaged app has
    # launchd's PATH and would report Codex as missing while the user is looking
    # straight at a Codex session.
    binary = find_command("codex")
    if not binary:
        raise ValueError(
            "Codex could not be found, so there is no session to join. If it is "
            "installed, quit and reopen TalkToMe so it can see your shell's PATH."
        )

    try:
        result = run(
            queue_argv(binary, thread_id, message),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Codex took too long to accept the message.") from None
    except OSError as exc:
        raise ValueError(f"Codex could not run. {exc}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise ValueError(
            f"Codex would not accept the message for this session. "
            f"{detail[-1].strip() if detail else ''}".strip()
        )
    return result


# Wait for the terminal to write the user's message to the file.
# `codex queue` can return before the terminal reads that message.
ACK_TIMEOUT = 20

# How often to look at the rollout while waiting for the agent to answer.
POLL = 0.1

# A terminal session can be busy with something long. This is how long the app
# waits for the queued message to be picked up before it tells the user.
TURN_TIMEOUT = 180


class AttachedAdapter:
    """Follow a thread a terminal owns, wearing the managed adapter's interface.

    `start`, `run`, and `close` are what `ManagedSession` knows how to drive, so the
    speech pipeline, the transcript, and the call surface are all unchanged. What
    this cannot do is interrupt: only a thread's writer can stop its turn, and that
    writer is the terminal. The app can stop speaking, and that is all.
    """

    agent_name = "Codex"

    def __init__(self, thread_id, cwd=None):
        self.session_id = thread_id
        self.cwd = cwd
        self.rollout = None
        self.poll = POLL
        self.timeout = TURN_TIMEOUT
        self.ack_timeout = ACK_TIMEOUT
        # Injectable so the whole turn can be tested without Codex or a thread.
        self.deliver = queue_message
        self.reader = None
        self.queue_transport = CodexQueueTransport()
        self.queue_fallback = False
        self.wakeup = RolloutWakeup()

    async def start(self):
        # Find the terminal command before the user speaks. A packaged app can
        # need a login shell for this, which delays the first queued message.
        await asyncio.to_thread(find_command, "codex")
        rollout = await asyncio.to_thread(Rollout.open, self.session_id)
        if rollout is None:
            raise ValueError(
                "That session has no transcript yet. Send it one message in the "
                "terminal, then start the call again."
            )
        # Everything before the call is history, not conversation.
        await asyncio.to_thread(rollout.skip_history)
        self.rollout = rollout
        self.wakeup.start(rollout.path)
        try:
            await self.queue_transport.start(self.cwd)
        except (TimeoutError, OSError, ValueError):
            # No user message exists during initialization.
            await self.queue_transport.close()
            self.queue_fallback = True

    async def run(self, text, emit, approve):
        # The call command can finish after the app starts to read the file.
        # Clear that turn before the app sends the user's question.
        await asyncio.to_thread(self.rollout.read_new)
        await emit("turn.queue_start")
        if self.deliver is not queue_message or self.queue_fallback:
            await asyncio.to_thread(self.deliver, self.session_id, text, self.cwd)
        else:
            if self.queue_transport.closed:
                self.queue_transport = CodexQueueTransport()
            try:
                await self.queue_transport.send(self.session_id, text, self.cwd)
            except QueueTransportUnsupported:
                self.queue_fallback = True
                await asyncio.to_thread(self.deliver, self.session_id, text, self.cwd)
        await emit("turn.queued")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        acknowledgement = loop.time() + self.ack_timeout
        reply_turn = None
        while loop.time() < deadline:
            records = await asyncio.to_thread(self.rollout.read_new)
            for record in records:
                payload = record.get("payload") or {}
                if reply_turn is None:
                    if user_message_text(record) != text.strip():
                        continue
                    reply_turn = payload.get("turn_id")
                    acknowledgement = None
                    await emit("turn.accepted")
                    continue
                if payload.get("turn_id") != reply_turn:
                    continue
                message = spoken_message(record)
                if message:
                    await emit(
                        "message.done",
                        item_id=message["id"] or f"msg-{uuid4()}",
                        text=message["text"],
                        kind=message["kind"],
                    )
                activity = tool_activity(record)
                if activity:
                    await emit("tool.status", text=activity["text"], status="done")
                finished = turn_finished(record)
                if finished:
                    # The final message is already emitted above, with its phase.
                    return
            if loop.time() >= deadline:
                break
            if acknowledgement and loop.time() > acknowledgement:
                raise RuntimeError(
                    "The terminal did not read that message. It may be busy or waiting for your input."
                )
            await self.wakeup.wait(self.poll)
        raise RuntimeError("The session did not answer. It may still be working on something else.")

    async def close(self):
        self.wakeup.close()
        await self.queue_transport.close()
        self.rollout = None
