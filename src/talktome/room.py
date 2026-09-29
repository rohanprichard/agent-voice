import asyncio
import time
from collections import deque
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException

from .playback import PlaybackLedger, interruption_context
from .timing import TimingHistory


class Room:
    """Keep one call and its events in memory."""

    def __init__(self, timing_history: TimingHistory | None = None):
        self.call_id = None
        self.started_at = None
        self.turn_id = None
        self.answered = False
        self.revision = 0
        self.agent = None
        self.sequence = 0
        self.events = deque(maxlen=512)
        self.messages = deque(maxlen=200)
        self.timing = None
        self.timing_history = timing_history
        self.changed = asyncio.Condition()
        self.playback = PlaybackLedger()
        self.pending_interruption = None
        self.last_interruption = None

    async def emit(self, event_type, **data):
        async with self.changed:
            self.sequence += 1
            event = {
                "seq": self.sequence,
                "type": event_type,
                "call_id": self.call_id,
                "time": datetime.now(UTC).isoformat(),
                **data,
            }
            self.events.append(event)
            self.changed.notify_all()
        return event

    def snapshot(self):
        return {
            "call_id": self.call_id,
            "started_at": self.started_at,
            "turn_id": self.turn_id,
            "answered": self.answered,
            "agent": {"name": self.agent["name"]} if self.agent else None,
            "messages": list(self.messages),
            "timing": dict(self.timing) if self.timing else None,
            "seq": self.sequence,
            "playback_epoch": self.revision,
            "last_interruption": self.last_interruption,
        }

    async def start(self):
        if self.call_id:
            return self.snapshot()
        self.call_id = str(uuid4())
        self.revision += 1
        self.started_at = datetime.now(UTC).isoformat()
        self.turn_id = None
        self.answered = False
        self.messages.clear()
        self.playback.clear()
        self.pending_interruption = None
        self.last_interruption = None
        self.timing = None
        await self.emit("call.started")
        return self.snapshot()

    def require_call(self, call_id):
        if not self.call_id or call_id != self.call_id:
            raise HTTPException(409, "This call ended. Start a new call.")

    async def end(self, call_id):
        self.require_call(call_id)
        self.revision += 1
        await self.emit("call.ended")
        self.call_id = None
        self.turn_id = None
        self.started_at = None
        self.timing = None
        if self.timing_history:
            await self.timing_history.flush()
        return self.snapshot()

    async def interrupt(self, call_id, receipts=None, expected_epoch=None):
        self.require_call(call_id)
        if expected_epoch is not None and expected_epoch != self.revision:
            return {"status": "stale", "playback_epoch": self.revision}
        interrupted_turn = self.turn_id
        record = self.playback.capture(call_id, self.revision, receipts or [])
        record.update(turn_id=interrupted_turn, playback_epoch=self.revision)
        self.last_interruption = record
        self.pending_interruption = record
        self.revision += 1
        self.turn_id = None
        self.answered = False
        return await self.emit("agent.interrupted", **record, next_epoch=self.revision)

    async def utterance(self, call_id, text, timing=None, mode="direct"):
        self.require_call(call_id)
        self.revision += 1
        self.turn_id = str(uuid4())
        self.answered = False
        self.timing = {"turn_id": self.turn_id, **(timing or {})}
        if self.timing_history:
            self.timing_history.add(call_id, self.turn_id, self.timing, mode)
        event = await self.emit("user.utterance", text=text, turn_id=self.turn_id)
        self.messages.append({**event, "role": "user"})
        if self.pending_interruption:
            event["agent_text"] = interruption_context(self.pending_interruption) + "\n\n" + text
            self.pending_interruption = None
        self.mark_timing(self.turn_id, "room_message_ms", time.time_ns() / 1_000_000)
        return event

    async def audio(
        self, audio_id, audio, *, turn_id, text="", alignment=None,
        expected_call_id=None, expected_epoch=None, **data,
    ):
        call_id = self.call_id if expected_call_id is None else expected_call_id
        epoch = self.revision if expected_epoch is None else expected_epoch
        if call_id != self.call_id or epoch != self.revision:
            return None
        self.playback.register(
            audio_id, call_id=call_id, turn_id=turn_id, epoch=epoch,
            audio=audio, text=text, alignment=alignment,
        )
        return await self.emit(
            "agent.audio", audio_id=audio_id, turn_id=turn_id,
            call_id=call_id, playback_epoch=epoch, **data,
        )

    def mark_timing(self, turn_id, stage, at_ms, call_id=None):
        target_call_id = call_id or self.call_id
        changed = False
        if target_call_id == self.call_id and turn_id == self.turn_id and self.timing and stage not in self.timing:
            self.timing[stage] = at_ms
            changed = True
        if self.timing_history and target_call_id:
            changed = self.timing_history.mark(target_call_id, turn_id, stage, at_ms) or changed
        return changed

    async def connect(self, name):
        if self.agent is not None:
            raise HTTPException(409, "Another agent is connected. Disconnect that agent first.")
        self.agent = {"name": name, "client_id": str(uuid4())}
        await self.emit("agent.connected", name=name)
        return {**self.agent, "seq": self.sequence, "room": self.snapshot()}

    async def disconnect(self):
        self.agent = None
        await self.emit("agent.disconnected")
        return {"ok": True}

    async def poll(self, after, timeout=25):
        async with self.changed:
            if self.sequence <= after:
                try:
                    await asyncio.wait_for(
                        self.changed.wait_for(lambda: self.sequence > after), timeout=timeout
                    )
                except TimeoutError:
                    pass
            gap = bool(self.events and after < self.events[0]["seq"] - 1)
            return {
                "events": [event for event in self.events if event["seq"] > after],
                "seq": self.sequence,
                "reset": gap,
                "room": self.snapshot(),
            }
