"""Store bounded call timing records."""

import asyncio
import json
import logging
import os
import threading
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_RECORDS = 200
TIMING_FIELDS = frozenset(
    {
        "speech_end_ms",
        "capture_end_ms",
        "commit_sent_ms",
        "committed_ms",
        "transcribed_ms",
        "room_message_ms",
        "cancel_start_ms",
        "cancel_end_ms",
        "queue_start_ms",
        "queued_ms",
        "accepted_ms",
        "first_message_ms",
        "tts_ready_ms",
        "first_tts_text_ms",
        "first_audio_received_ms",
        "first_audio_scheduled_ms",
        "first_audio_ms",
    }
)
MODE_FIELDS = frozenset({"mode", "turn_reason", "turn_probability", "turn_check_ms"})


class TimingHistory:
    """Keep private timing records outside the room transcript."""

    def __init__(self, path: Path, maximum=MAX_RECORDS):
        self.path = path
        self.maximum = maximum
        self.records = deque(maxlen=maximum)
        self.lock = threading.Lock()
        self.write_task = None
        self.dirty = False

    async def load(self):
        records = await asyncio.to_thread(self._read)
        with self.lock:
            if not self.records:
                self.records.extend(records)

    def _read(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [record for record in data[-self.maximum :] if self._valid(record)]

    @staticmethod
    def _valid(record):
        if not isinstance(record, dict):
            return False
        if not isinstance(record.get("call_id"), str) or not isinstance(record.get("turn_id"), str):
            return False
        return all(key in {"call_id", "turn_id", *TIMING_FIELDS, *MODE_FIELDS} for key in record)

    def add(self, call_id, turn_id, timing, mode):
        record = {"call_id": call_id, "turn_id": turn_id, "mode": mode}
        self._copy(record, timing)
        with self.lock:
            self.records.append(record)
            self.dirty = True
        self.schedule_write()

    def mark(self, call_id, turn_id, stage, value):
        if stage not in TIMING_FIELDS | MODE_FIELDS:
            return False
        with self.lock:
            for record in reversed(self.records):
                if record["call_id"] == call_id and record["turn_id"] == turn_id:
                    if stage in record:
                        return False
                    record[stage] = value
                    self.dirty = True
                    break
            else:
                return False
        self.schedule_write()
        return True

    def list(self, call_id=None):
        with self.lock:
            records = [dict(record) for record in self.records]
        if call_id is not None:
            records = [record for record in records if record["call_id"] == call_id]
        return [self._output(record) for record in records]

    def contains(self, call_id, turn_id):
        with self.lock:
            return any(
                record["call_id"] == call_id and record["turn_id"] == turn_id
                for record in self.records
            )

    def schedule_write(self):
        if self.write_task is None or self.write_task.done():
            self.write_task = asyncio.create_task(self._write_until_clean())

    async def flush(self):
        self.schedule_write()
        if self.write_task is not None:
            await self.write_task

    async def _write_until_clean(self):
        while True:
            with self.lock:
                if not self.dirty:
                    return
                records = [dict(record) for record in self.records]
                self.dirty = False
            try:
                await asyncio.to_thread(self._write, records)
            except OSError:
                logger.exception("The timing file write failed.")
                with self.lock:
                    self.dirty = True
                return

    def _write(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w") as file:
                json.dump(records, file, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _copy(record, timing):
        for key, value in timing.items():
            if key in TIMING_FIELDS | MODE_FIELDS:
                record[key] = value

    @staticmethod
    def _output(record):
        output = dict(record)
        output["durations_ms"] = {
            name: duration
            for name, start, end in (
                ("pause", "speech_end_ms", "commit_sent_ms"),
                ("commit", "commit_sent_ms", "committed_ms"),
                ("transcript", "committed_ms", "room_message_ms"),
                ("cancel", "cancel_start_ms", "cancel_end_ms"),
                ("queue_start", "room_message_ms", "queue_start_ms"),
                ("queue", "queue_start_ms", "queued_ms"),
                ("queue_accept", "queued_ms", "accepted_ms"),
                ("agent", "accepted_ms", "first_message_ms"),
                ("tts_ready", "first_message_ms", "tts_ready_ms"),
                ("tts_text", "tts_ready_ms", "first_tts_text_ms"),
                ("audio", "first_tts_text_ms", "first_audio_received_ms"),
                ("schedule", "first_audio_received_ms", "first_audio_scheduled_ms"),
                ("audible", "first_audio_scheduled_ms", "first_audio_ms"),
            )
            if isinstance(record.get(start), (int, float))
            and isinstance(record.get(end), (int, float))
            and record[end] >= record[start]
            for duration in (record[end] - record[start],)
        }
        return output
