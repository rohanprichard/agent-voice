"""Calls from the user into this machine's projects.

A call either starts a host session (continue or new), or joins a Claude Code
or Codex session that is open and working. Open sessions report to the server
through the talktome plugin's hooks: the user's words reach the agent through
PostToolUse context during a task, and through a blocked Stop at the end of a
turn. The agent's last message at each Stop is spoken.
"""

import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import sessions, targets

log = logging.getLogger("talktome")

STILL_WORKING = "One moment."
PASSED_ON = "I'll pass that on."

PROGRESS_AFTER = 4.0  # seconds a turn runs before the user hears STILL_WORKING
PERMISSION_WAIT = 90.0
STOP_WAIT = 540.0  # the plugin gives the Stop hook 600 seconds

IDLE, BUSY, LISTENING = "idle", "busy", "listening"


@dataclass
class _CallState:
    host: str = ""
    reply_turn: str = ""  # the turn that gets the next reply: the user's latest
    ask: asyncio.Future | None = None  # a permission question that waits for the user


@dataclass
class _Live:
    host: str
    id: str
    cwd: str
    state: str = IDLE
    updated: float = field(default_factory=time.time)
    call_id: str = ""
    reply_turn: str = ""
    queue: list[str] = field(default_factory=list)
    ask: asyncio.Future | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)

    def signal(self) -> None:
        self.wake.set()
        self.wake = asyncio.Event()


class Inbound:
    def __init__(self, link, home: Path, approver: str, new_runner=sessions.new_runner, added=None):
        self.link = link
        self.home = home
        self.approver = approver  # this program, for Claude's permission tool
        self.new_runner = new_runner
        self.added = added or []
        self.targets: list[targets.Target] = []
        self.calls: dict[str, asyncio.Queue] = {}
        self.states: dict[str, _CallState] = {}
        self.live: dict[str, _Live] = {}
        self.changed = asyncio.Event()
        self.tasks: set[asyncio.Task] = set()

    # Targets

    def discover(self) -> list[targets.Target]:
        self.targets = self._live_targets() + targets.discover(self.home, self.added)
        return self.targets

    def _live_targets(self) -> list[targets.Target]:
        found = [
            targets.Target(
                id=live_target_id(s.host, s.id),
                host=s.host,
                path=s.cwd,
                project=Path(s.cwd).name + " (open session)",
                last_active=s.updated,
                joinable=s.state != IDLE,
                session=s.id,
            )
            for s in self.live.values()
        ]
        return sorted(found, key=lambda t: -t.last_active)

    def _target(self, target_id: str) -> targets.Target | None:
        for t in self.targets:
            if t.id == target_id:
                return t
        for t in self.discover():
            if t.id == target_id:
                return t
        return None

    def _live_for(self, target_id: str) -> _Live | None:
        return next((s for s in self.live.values() if live_target_id(s.host, s.id) == target_id), None)

    # Frames from the app

    def dispatch(self, frame: dict) -> None:
        call_id = frame.get("call_id", "")
        if frame["type"] == "call.incoming":
            queue: asyncio.Queue = asyncio.Queue()
            self.calls[call_id] = queue
            self._spawn(self._handle(call_id, frame.get("target_id", ""), frame.get("mode", "continue"), queue))
            return
        queue = self.calls.get(call_id)
        if queue:
            queue.put_nowait(frame)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def _handle(self, call_id: str, target_id: str, mode: str, frames: asyncio.Queue) -> None:
        st = self.states[call_id] = _CallState()
        try:
            t = self._target(target_id)
            if not t:
                await self.link.send(
                    "call.reject", call_id=call_id, reason="That project is not on this machine any more."
                )
                return
            st.host = t.host
            live = self._live_for(target_id)
            if live:
                if mode == "join" and self._claim(live, call_id):
                    await self.link.send("call.accept", call_id=call_id)
                    log.info("call %s joined open session %s", call_id, live.id)
                    await self._run_joined(live, call_id, frames)
                    return
                # An idle session cannot be woken, so the call works in a copy of it.
                if mode == "join":
                    mode = "continue"
            try:
                runner = self.new_runner(t.host, t.path, mode, t.session)
            except sessions.RunError as exc:
                await self.link.send("call.reject", call_id=call_id, reason=str(exc))
                return
            if hasattr(runner, "bind_call"):
                runner.bind_call(call_id, self.approver)
            await self.link.send("call.accept", call_id=call_id)
            log.info("call %s from the user: %s %s, %s", call_id, t.host, t.project, mode)
            await self._run_call(runner, st, call_id, frames)
        finally:
            self.calls.pop(call_id, None)
            self.states.pop(call_id, None)

    async def _run_call(self, runner, st: _CallState, call_id: str, frames: asyncio.Queue) -> None:
        running: asyncio.Task | None = None
        running_turn = ""
        try:
            while True:
                frame = await frames.get()
                kind = frame["type"]
                if kind == "call.ended":
                    return
                if kind == "turn.cancel" and frame.get("turn_id") == running_turn and running:
                    running.cancel()
                elif kind == "turn.user":
                    st.reply_turn = frame.get("turn_id", "")
                    if st.ask and not st.ask.done():
                        st.ask.set_result(is_yes(frame.get("text", "")))
                        continue
                    if running:
                        running.cancel()
                        await asyncio.gather(running, return_exceptions=True)
                    running_turn = frame.get("turn_id", "")
                    running = self._spawn(self._turn(runner, st, call_id, running_turn, frame.get("text", "")))
        finally:
            if running:
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)

    async def _turn(self, runner, st: _CallState, call_id: str, turn_id: str, text: str) -> None:
        async def still_working():
            await asyncio.sleep(PROGRESS_AFTER)
            await self.link.send(
                "turn.agent", call_id=call_id, turn_id=turn_id, item_id=turn_id + "-1", text=STILL_WORKING, final=False
            )

        progress = asyncio.create_task(still_working())
        try:
            reply = await runner.turn(text)
            spoken = sessions.speakable(reply)
        except sessions.RunError as exc:
            log.warning("turn failed in call %s: %s", call_id, exc)
            spoken = "Sorry, that did not work. " + sessions.speakable(str(exc))
        finally:
            progress.cancel()
        # A permission answer is a newer turn, and the answer goes there.
        reply_turn = st.reply_turn
        await self.link.send(
            "turn.agent",
            call_id=call_id,
            turn_id=reply_turn,
            item_id=reply_turn + "-final",
            text=spoken or "Done.",
            final=True,
        )

    # Permission for a call-in run, from Claude's permission tool

    async def ask_permission(self, call_id: str, tool: str, tool_input) -> tuple[bool, str]:
        st = self.states.get(call_id)
        if not st:
            return False, "There is no live call to ask the user in."
        if st.ask and not st.ask.done():
            return False, "Another question is already waiting for the user."
        answer = st.ask = asyncio.get_running_loop().create_future()
        turn = st.reply_turn
        question = f"{host_name(st.host)} wants to {describe(tool, tool_input)}. Should I allow it?"
        await self.link.send(
            "turn.agent",
            call_id=call_id,
            turn_id=turn,
            item_id=f"{turn}-ask-{secrets.token_hex(4)}",
            text=question,
            final=True,
        )
        try:
            allow = await asyncio.wait_for(answer, PERMISSION_WAIT)
        except TimeoutError:
            return False, "The user did not answer in the voice call."
        finally:
            if st.ask is answer:
                st.ask = None
        return (True, "") if allow else (False, "The user said no in the voice call.")

    # Open sessions, through the plugin's hooks

    async def hook(self, h: dict) -> dict:
        event, session_id = h.get("event", ""), h.get("session_id", "")
        s = self.live.get(session_id)
        if not s and event != "SessionEnd":
            s = self.live[session_id] = _Live(host=h.get("host") or "claude", id=session_id, cwd=h.get("cwd", ""))
        if s:
            s.updated = time.time()
            s.cwd = h.get("cwd") or s.cwd
        if event == "SessionEnd":
            self.live.pop(session_id, None)
            self.changed.set()
            if s and s.call_id:
                call_id, s.call_id = s.call_id, ""
                s.signal()
                await self.link.send("call.end", call_id=call_id, reason="The session ended.")
            return {}
        if event == "SessionStart":
            s.state = IDLE
            self.changed.set()
        elif event == "UserPromptSubmit":
            s.state = BUSY
            self.changed.set()
        elif event == "PostToolUse":
            if s.call_id and s.queue:
                context, s.queue = spoken_context(s.queue), []
                return {"context": context}
        elif event == "Stop":
            return await self._stop(s, h.get("last_assistant_message", ""))
        elif event == "PermissionRequest":
            return await self._ask_live(s, h.get("tool_name", ""), h.get("tool_input"))
        return {}

    async def _stop(self, s: _Live, last: str) -> dict:
        """Speak the agent's last message in the call, then wait for the user's
        next words and hand them to the agent, so the session keeps going."""
        call_id, turn = s.call_id, s.reply_turn
        if not call_id:
            s.state = IDLE
            self.changed.set()
            return {}
        text = sessions.speakable(last)
        if text and turn:
            await self.link.send(
                "turn.agent", call_id=call_id, turn_id=turn, item_id=turn + "-final", text=text, final=True
            )
        deadline = time.monotonic() + STOP_WAIT
        while True:
            if s.call_id != call_id:
                s.state = IDLE
                self.changed.set()
                return {}
            if s.queue:
                reason, s.queue = spoken_context(s.queue), []
                s.state = BUSY
                return {"block": reason}
            s.state = LISTENING
            left = deadline - time.monotonic()
            try:
                await asyncio.wait_for(s.wake.wait(), max(left, 0))
            except TimeoutError:
                s.state = IDLE
                await self.link.send(
                    "turn.agent",
                    call_id=call_id,
                    turn_id=turn,
                    item_id=turn + "-stopped",
                    text=f"{host_name(s.host)} stopped listening. Call again to continue.",
                    final=False,
                )
                return {}

    async def _ask_live(self, s: _Live, tool: str, tool_input) -> dict:
        """Ask in a joined call whether a tool may run. With no call, or no answer
        in time, the host asks in its own window as usual."""
        call_id, turn = s.call_id, s.reply_turn
        if not call_id or (s.ask and not s.ask.done()):
            return {}
        answer = s.ask = asyncio.get_running_loop().create_future()
        item = f"ask-{secrets.token_hex(4)}"
        if turn:
            item = f"{turn}-{item}"
        question = f"{host_name(s.host)} wants to {describe(tool, tool_input)}. Should I allow it?"
        await self.link.send("turn.agent", call_id=call_id, turn_id=turn, item_id=item, text=question, final=True)
        deadline = time.monotonic() + PERMISSION_WAIT
        try:
            while s.call_id == call_id:
                wake = asyncio.ensure_future(s.wake.wait())
                done, _ = await asyncio.wait(
                    {answer, wake}, timeout=deadline - time.monotonic(), return_when=asyncio.FIRST_COMPLETED
                )
                wake.cancel()
                if answer in done:
                    if answer.result():
                        return {"permission": "allow"}
                    return {"permission": "deny", "message": "The user said no in the voice call."}
                if not done:
                    return {}
            return {}
        finally:
            if s.ask is answer:
                s.ask = None

    def _claim(self, s: _Live, call_id: str) -> bool:
        if s.state == IDLE or s.call_id:
            return False
        s.call_id, s.reply_turn, s.queue = call_id, "", []
        return True

    async def _run_joined(self, s: _Live, call_id: str, frames: asyncio.Queue) -> None:
        """Carry a call into an open session. The user's words wait in the
        session's queue for the next PostToolUse or Stop hook."""
        try:
            while True:
                frame = await frames.get()
                if frame["type"] == "call.ended":
                    return
                if frame["type"] != "turn.user":
                    continue
                s.reply_turn = frame.get("turn_id", "")
                if s.ask and not s.ask.done():
                    s.ask.set_result(is_yes(frame.get("text", "")))
                    continue
                s.queue.append(frame.get("text", ""))
                busy = s.state == BUSY
                s.signal()
                if busy:
                    turn = s.reply_turn
                    await self.link.send(
                        "turn.agent",
                        call_id=call_id,
                        turn_id=turn,
                        item_id=turn + "-queued",
                        text=PASSED_ON,
                        final=False,
                    )
        finally:
            if s.call_id == call_id:
                s.call_id, s.queue = "", []
                s.signal()


def live_target_id(host: str, session: str) -> str:
    return targets.target_id(host + "-session", session)


def spoken_context(queue: list[str]) -> str:
    said = " ".join(queue)
    return (
        f"The user just said this on the talktome voice call: {json.dumps(said)}. The call is already connected, "
        "and talktome speaks your normal reply, so answer in plain text in one or two short sentences. "
        "Do not use the talktome call tools for this call. "
        "Then continue the task, unless the user asked you to stop or change it."
    )


_NO_WORDS = re.compile(r"\b(no|nope|not|don't|dont|deny|stop|cancel|never|wait)\b")
_YES_WORDS = re.compile(r"\b(yes|yeah|yep|sure|allow|okay|ok|approve|fine|go ahead|do it|go for it|please do)\b")


def is_yes(text: str) -> bool:
    """Read a spoken answer to a permission question. Anything unclear is no."""
    text = text.lower()
    return not _NO_WORDS.search(text) and bool(_YES_WORDS.search(text))


def host_name(host: str) -> str:
    return {"claude": "Claude", "codex": "Codex"}.get(host, "The agent")


def describe(tool: str, tool_input) -> str:
    """Say in a few words what a tool call will do."""
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            tool_input = {}
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool in ("Edit", "MultiEdit", "Write", "NotebookEdit") and tool_input.get("file_path"):
        return "change the file " + Path(tool_input["file_path"]).name
    if tool == "WebFetch":
        return "open a web page"
    if tool == "apply_patch":
        return "change files"
    if tool.startswith("mcp__"):
        # mcp__server__tool; the server name does not read well aloud.
        return "use the " + tool.rsplit("__", 1)[-1].replace("_", " ") + " tool"
    command = tool_input.get("command")
    if isinstance(command, list):
        command = " ".join(str(word) for word in command)
    command = " ".join(str(command or "").split())
    if command:
        if len(command) > 100:
            command = command[:100] + " and more"
        return "run the command: " + command
    return f"use the {tool} tool"
