"""Connect a live host session through explicit TalkToMe commands.

This adapter does not read public host output. The host must call ``listen`` to
get a user turn. It must call ``reply`` to send each public message.
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_TEXT = 16_000
MAX_ITEM_ID = 128
MAX_ITEMS = 64
MAX_EVENTS = 256
MAX_CANCELLED = 64
MAX_COMPLETED = 256
MAX_LISTEN_TIMEOUT = 25
# A host in a call runs `listen` at least every 25 seconds. This much silence
# with no listen and no reply means it left the call.
TURN_IDLE = 300


class CooperativeError(ValueError):
    """An invalid cooperative command."""


class CooperativeConflictError(CooperativeError):
    """A reply conflicts with an earlier item."""


class CooperativeCancelledError(CooperativeError):
    """A reply names a cancelled turn."""


@dataclass
class PendingTurn:
    event: dict[str, Any]
    text: str
    complete: asyncio.Future[None]
    emit: Callable[..., Awaitable[None]]
    items: dict[str, tuple[str, bool]] = field(default_factory=dict)
    emitting: dict[str, tuple[str, bool]] = field(default_factory=dict)
    final: bool = False


class CooperativeAdapter:
    """Wait for commands from an agent that owns the live host session."""

    def __init__(self, provider, session_id, cwd):
        self.provider = self._provider(provider)
        self.session_id = self._required(session_id, "Enter a session ID.")
        self.cwd = str(Path(cwd).expanduser().resolve())
        self.agent_name = self._agent_name(self.provider)
        self.changed = asyncio.Condition()
        self.reply_lock = asyncio.Lock()
        self.events = deque(maxlen=MAX_EVENTS)
        self.cancelled = deque(maxlen=MAX_CANCELLED)
        self.completed = OrderedDict()
        self.sequence = 0
        self.started = False
        self.closed = False
        self.bound: dict[str, Any] | None = None
        self.current: PendingTurn | None = None
        self.activity = 0.0

    @staticmethod
    def _required(value, message):
        if not isinstance(value, str) or not value.strip():
            raise CooperativeError(message)
        return value.strip()

    @staticmethod
    def _provider(value):
        provider = CooperativeAdapter._required(value, "Enter a provider name.").lower()
        provider = re.sub(r"[^a-z0-9]+", "-", provider).strip("-")
        if not provider or len(provider) > 48:
            raise CooperativeError("Use a provider name with 1 to 48 letters or numbers.")
        return provider

    @staticmethod
    def _agent_name(provider):
        if provider == "claude":
            return "Claude"
        if provider in {"agent", "generic"}:
            return "Agent"
        return " ".join(part.capitalize() for part in provider.split("-"))

    def capabilities(self):
        return {
            "cooperative": True,
            "supports_cancel_work": False,
            # The app stops its own playback and drops the queued speech. The host
            # keeps its work, which is what supports_cancel_work says.
            "supports_cancel_speech": True,
            "requires_explicit_listen": True,
            "requires_explicit_reply": True,
        }

    async def start(self):
        async with self.changed:
            self.started = True
            self.closed = False
            self.changed.notify_all()
        return self.capabilities()

    def begin_turn(self, event):
        """Bind the current room event before ``run`` starts its request."""
        if not isinstance(event, dict):
            raise CooperativeError("Send a room event.")
        call_id = self._required(event.get("call_id"), "The room event has no call ID.")
        turn_id = self._required(event.get("turn_id"), "The room event has no turn ID.")
        text = self._text(event.get("text"), "The room event has no text.")
        agent_text = self._text(event.get("agent_text", text), "The room event has no agent text.")
        if self.bound is not None or self.current is not None:
            raise CooperativeConflictError("A user turn is already pending.")
        self.bound = {
            **event,
            "call_id": call_id,
            "turn_id": turn_id,
            "text": text,
            "agent_text": agent_text,
        }

    @staticmethod
    def _text(value, message="Enter reply text."):
        if not isinstance(value, str):
            raise CooperativeError(message)
        if len(value) > MAX_TEXT:
            raise CooperativeError(f"The text exceeds {MAX_TEXT} characters.")
        return value

    def _item_id(self, value):
        item_id = self._required(value, "Enter an item ID.")
        if len(item_id) > MAX_ITEM_ID:
            raise CooperativeError(f"The item ID exceeds {MAX_ITEM_ID} characters.")
        return item_id

    def _event_locked(self, event_type, **data):
        self.sequence += 1
        event = {"seq": self.sequence, "type": event_type, **data}
        self.events.append(event)
        self.changed.notify_all()
        return event

    @staticmethod
    def _identity(event):
        return {
            "session_id": event["session_id"],
            "call_id": event["call_id"],
            "turn_id": event["turn_id"],
        }

    def _public_turn(self, turn):
        if turn is None:
            return None
        return {**self._identity(turn.event), "text": turn.text}

    async def run(self, text, emit, approve):
        """Offer one user turn and wait until the host sends its final reply."""
        del approve
        if not callable(emit):
            raise CooperativeError("Send an event function.")
        text = self._text(text)
        loop = asyncio.get_running_loop()
        try:
            async with self.changed:
                if not self.started:
                    raise CooperativeError("Start the cooperative session first.")
                if self.bound is None:
                    raise CooperativeError("Bind a room event before you run a user turn.")
                if self.current is not None:
                    raise CooperativeConflictError("A user turn is already pending.")
                if text != self.bound["agent_text"]:
                    raise CooperativeError("The user text does not match the room event.")
                event = {**self.bound, "session_id": self.session_id}
                complete = loop.create_future()
                turn = PendingTurn(event=event, text=text, complete=complete, emit=emit)
                self.current = turn
                self.activity = loop.time()
                self._event_locked("turn.request", **self._public_turn(turn))
        finally:
            # A bound event that failed its checks, or whose run was cancelled
            # while it waited for the lock, must not block every later turn.
            self.bound = None
        try:
            await emit("turn.accepted")
            while True:
                try:
                    await asyncio.wait_for(asyncio.shield(complete), TURN_IDLE)
                    break
                except TimeoutError:
                    if loop.time() - self.activity < TURN_IDLE:
                        continue
                    await self._cancel_turn(turn, "The agent stopped answering the call.")
                    raise RuntimeError(
                        "The agent stopped listening for the call. Ask it to call again."
                    ) from None
            complete.result()
        except asyncio.CancelledError:
            await self._cancel_turn(turn, "The TalkToMe turn ended.")
            raise
        finally:
            async with self.changed:
                if self.current is turn:
                    self.current = None
                    self.changed.notify_all()

    async def listen(self, after=None, timeout=MAX_LISTEN_TIMEOUT):
        """Return events after a sequence number and the current pending turn."""
        if after is None:
            after = 0
        if not isinstance(after, int) or after < 0:
            raise CooperativeError("Use a non-negative event sequence.")
        if not isinstance(timeout, (int, float)) or not 0 <= timeout <= MAX_LISTEN_TIMEOUT:
            raise CooperativeError(f"Use a timeout from 0 to {MAX_LISTEN_TIMEOUT} seconds.")
        async with self.changed:
            self.activity = asyncio.get_running_loop().time()
            # A sequence from an earlier call. Tell the host to start again at 0
            # rather than hide the new events behind a full wait.
            if after > self.sequence:
                return {
                    "events": list(self.events),
                    "seq": self.sequence,
                    "reset": True,
                    "pending": self._public_turn(self.current),
                    "closed": self.closed,
                    "capabilities": self.capabilities(),
                }
            if self.sequence <= after and not self.closed and timeout:
                try:
                    await asyncio.wait_for(
                        self.changed.wait_for(
                            lambda: self.sequence > after or self.closed
                        ),
                        timeout,
                    )
                except TimeoutError:
                    pass
            reset = bool(self.events and after < self.events[0]["seq"] - 1)
            return {
                "events": [event for event in self.events if event["seq"] > after],
                "seq": self.sequence,
                "reset": reset,
                "pending": self._public_turn(self.current),
                "closed": self.closed,
                "capabilities": self.capabilities(),
            }

    def _completed_key(self, session_id, call_id, turn_id, item_id):
        return (session_id, call_id, turn_id, item_id)

    def _completed_reply(self, session_id, call_id, turn_id, item_id, reply):
        key = self._completed_key(session_id, call_id, turn_id, item_id)
        earlier = self.completed.get(key)
        if earlier is None:
            return None
        if earlier != reply:
            raise CooperativeConflictError("This item ID has different reply text.")
        self.completed.move_to_end(key)
        return {"ok": True, "duplicate": True, "final": earlier[1]}

    def _remember_completed_locked(self, turn):
        identity = self._identity(turn.event)
        for item_id, reply in turn.items.items():
            key = self._completed_key(
                identity["session_id"], identity["call_id"], identity["turn_id"], item_id
            )
            self.completed[key] = reply
            self.completed.move_to_end(key)
        while len(self.completed) > MAX_COMPLETED:
            self.completed.popitem(last=False)

    async def reply(self, session_id, call_id, turn_id, item_id, text, final):
        """Accept one explicit host reply for the current user turn."""
        self.activity = asyncio.get_running_loop().time()
        async with self.reply_lock:
            return await self._reply(session_id, call_id, turn_id, item_id, text, final)

    async def _reply(self, session_id, call_id, turn_id, item_id, text, final):
        session_id = self._required(session_id, "Enter a session ID.")
        call_id = self._required(call_id, "Enter a call ID.")
        turn_id = self._required(turn_id, "Enter a turn ID.")
        item_id = self._item_id(item_id)
        text = self._text(text)
        if not isinstance(final, bool):
            raise CooperativeError("Set final to true or false.")
        reply = (text, final)
        async with self.changed:
            completed = self._completed_reply(session_id, call_id, turn_id, item_id, reply)
            if completed is not None:
                return completed
            turn = self.current
            if turn is None:
                if (session_id, call_id, turn_id) in self.cancelled:
                    raise CooperativeCancelledError("This user turn was cancelled.")
                raise CooperativeError("There is no pending user turn.")
            identity = self._identity(turn.event)
            if session_id != identity["session_id"]:
                raise CooperativeError("This session does not own the user turn.")
            if call_id != identity["call_id"] or turn_id != identity["turn_id"]:
                raise CooperativeError("This user turn is no longer current.")
            if turn.final:
                raise CooperativeConflictError("The user turn already has a final reply.")
            earlier = turn.items.get(item_id)
            if earlier is not None:
                if earlier == reply:
                    return {"ok": True, "duplicate": True, "final": turn.final}
                raise CooperativeConflictError("This item ID has different reply text.")
            pending = turn.emitting.get(item_id)
            if pending is not None:
                if pending == reply:
                    return {"ok": True, "duplicate": True, "final": False}
                raise CooperativeConflictError("This item ID has different reply text.")
            if len(turn.items) + len(turn.emitting) >= MAX_ITEMS:
                raise CooperativeError(f"The user turn has more than {MAX_ITEMS} reply items.")
            turn.emitting[item_id] = reply
        try:
            await turn.emit("message.done", item_id=item_id, text=text, kind="message")
        except BaseException:
            async with self.changed:
                if turn.emitting.get(item_id) == reply:
                    turn.emitting.pop(item_id)
            raise
        async with self.changed:
            if self.current is not turn:
                turn.emitting.pop(item_id, None)
                raise CooperativeCancelledError("This user turn was cancelled.")
            turn.emitting.pop(item_id, None)
            turn.items[item_id] = reply
            if final:
                turn.final = True
                self._remember_completed_locked(turn)
                if not turn.complete.done():
                    turn.complete.set_result(None)
            return {"ok": True, "duplicate": False, "final": final}

    async def _cancel_turn(self, turn, reason):
        async with self.changed:
            if self.current is not turn:
                return False
            self.current = None
            self.cancelled.append(
                (turn.event["session_id"], turn.event["call_id"], turn.event["turn_id"])
            )
            self._event_locked("turn.cancelled", **self._identity(turn.event), reason=reason)
            if not turn.complete.done():
                turn.complete.cancel()
            return True

    async def cancel(self, reason="The TalkToMe turn ended."):
        """Cancel the cooperative request without stopping the host session."""
        if not isinstance(reason, str) or not reason.strip():
            raise CooperativeError("Enter a cancellation reason.")
        turn = self.current
        if turn is None:
            return False
        return await self._cancel_turn(turn, reason.strip()[:MAX_TEXT])

    async def close(self):
        await self.cancel("The cooperative session closed.")
        async with self.changed:
            self.started = False
            self.closed = True
            self.bound = None
            self.changed.notify_all()
