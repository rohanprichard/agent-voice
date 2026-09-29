"""Control managed turns and keep speech separate from agent output."""

import asyncio
import contextlib
import logging
import re
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .attach import AttachedAdapter, session_name
from .cooperative import CooperativeAdapter
from .external_adapters import create_external_adapter
from .streaming import ElevenLabsConnection, ElevenLabsStream

logger = logging.getLogger(__name__)

# How long a call rings before it gives up. The user can answer or decline on the
# pill, from the notification, or in the menu bar. RING_GUARD_MS in call.js and
# REQUEST_TIMEOUT in cli.py follow this value.
RING_TIMEOUT = 30

# How long a caller waits for a ring to be taken. The ring gives up first; this is
# that plus room for the status to settle, so a ring that ended is never reported
# as one that is still going.
ANSWER_WAIT = RING_TIMEOUT + 5

# A Codex id goes into a file search, so it keeps a strict pattern: `*` would
# follow whichever session happened to sort last.
CODEX_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,399}")

# Other agents own their ids. OpenClaw keys hold `+`, `@`, and `!`, for example
# agent:main:whatsapp:direct:+15551234567, and remote ids are <pair>:<thread>.
MAX_SESSION_ID = 512


def valid_session_id(thread_id, agent):
    if agent == "codex":
        return bool(CODEX_SESSION_ID.fullmatch(thread_id or ""))
    return (
        isinstance(thread_id, str)
        and 0 < len(thread_id) <= MAX_SESSION_ID
        and thread_id.isprintable()
        and not any(character.isspace() for character in thread_id)
    )

# A spoken turn is capped; the transcript keeps whatever is left over.
MAX_SPOKEN = 16000

# A streaming provider wants text sooner than a sentence boundary, but never
# mid-word and never so eagerly that markup gets split across two requests.
STREAM_UNIT = 50

# A local engine can only be handed whole strings, so the first chunk is cut at a
# clause instead of a sentence to start audio sooner. Clauses shorter than this
# are not worth a separate synthesis request, so the cut waits for a later one.
MIN_CLAUSE = 24
CLAUSE_BREAK = re.compile(r"[,;:—]\s+")


class SentenceBuffer:
    def __init__(self):
        self.pending = ""
        self.in_code = False
        self.opened = False

    def _boundary(self, clauses):
        """Find where to cut, preferring a sentence end over a clause.

        Clause cuts are only for the first chunk of a turn. A local engine needs
        one request per chunk, so cutting every clause would multiply the work
        for the rest of the reply while only the first chunk is waiting on it.
        """
        match = re.search(r'[.!?]["\')]*\s+|\n\n', self.pending)
        if match or not clauses or self.opened:
            return match
        for candidate in CLAUSE_BREAK.finditer(self.pending):
            if candidate.end() >= MIN_CLAUSE:
                return candidate
        return None

    def feed(self, text, final=False, unit=None, clauses=False):
        self.pending += text
        parts = []
        while True:
            match = self._boundary(clauses)
            if match:
                parts.append(self.pending[: match.end()])
                self.pending = self.pending[match.end() :]
                self.opened = True
                continue
            # A streaming voice wants text sooner than a sentence ends, but never
            # mid-word, and never so eagerly that markup gets split in half.
            if unit and len(self.pending) > unit:
                cut = self.pending.find(" ", unit - 1)
                if cut > 0:
                    parts.append(self.pending[: cut + 1])
                    self.pending = self.pending[cut + 1 :]
                    continue
            break
        if final and self.pending:
            parts.append(self.pending)
            self.pending = ""
        result = []
        for part in parts:
            spoken = []
            for index, section in enumerate(part.split("```")):
                if index:
                    self.in_code = not self.in_code
                if not self.in_code:
                    spoken.append(section)
            clean = "".join(spoken)
            clean = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", clean)
            clean = re.sub(r"[*_`#]+", "", clean).strip()
            if clean:
                # Bound each synthesis request without changing the transcript.
                result.extend(clean[i : i + 1000] for i in range(0, len(clean), 1000))
        return result


class ManagedSession:
    def __init__(
        self, room, synthesize, cache_audio, open_stream=None, warm_stream=None, speech_problem=None,
    ):
        self.room = room
        # Returns a reason when speech cannot work, so a call is refused before it
        # rings instead of ringing into a call that cannot hear or speak.
        self.speech_problem = speech_problem
        self.synthesize = synthesize
        self.cache_audio = cache_audio
        self.open_stream = open_stream
        self.warm_stream = warm_stream
        self.adapter = None
        self.client_id = None
        self.options = None
        self.task = None
        self.speaker = None
        self.ring = None
        self.ringer = None
        self.greeting_audio = None
        self.audio_queue = asyncio.Queue(maxsize=64)
        self.lock = asyncio.Lock()
        self.approvals = {}
        self.status = "disconnected"
        self.error = None
        self.tool = None
        self.usage = None
        self.generation = 0
        self.voice_connection = None
        self.voice_warmup = None

    def snapshot(self):
        return {
            "connected": self.adapter is not None,
            # Who is ringing, so the call surface can say so before the user has
            # decided to answer.
            "ring": dict(self.ring) if self.ring else None,
            **(self.options or {}),
            "session_id": self.adapter.session_id if self.adapter else None,
            "status": self.status,
            "error": self.error,
            "tool": self.tool,
            "usage": self.usage,
            "approvals": [entry[0] for entry in self.approvals.values()],
            "capabilities": self.capabilities(),
        }

    def capabilities(self):
        adapter = self.adapter
        values = getattr(adapter, "capabilities", {})
        if callable(values):
            values = values()
        if isinstance(adapter, AttachedAdapter):
            return {"connection": "terminal", "cancel_work": False, "cancel_speech": True}
        if isinstance(adapter, CooperativeAdapter):
            return {**values, "connection": "cooperative", "cancel_work": False, "cancel_speech": True}
        return {
            **values, "connection": "host", "cancel_speech": True,
            "cancel_work": bool(values.get("stop", adapter is not None)),
        }

    async def changed(self):
        await self.room.emit("managed.state")

    async def attach(self, thread_id, cwd, greeting=None, name=None, agent="codex", connection="auto"):
        """Ring in from a session a terminal is already writing.

        The terminal keeps the writer, so this call follows the thread rather than
        driving it. The adapter holds everything that differs between agents.

        Ringing is a state of its own rather than an immediate call. The user is
        being asked to stop what they are doing, so they get to decide, and the
        agent's greeting waits until they do.
        """
        if not valid_session_id(thread_id, agent):
            raise HTTPException(400, "That session id is not valid.")
        problem = self.speech_problem() if self.speech_problem else None
        if problem:
            raise HTTPException(409, problem)
        async with self.lock:
            directory = self._project(cwd)
            if agent not in {"codex", "claude", "hermes", "openclaw", "generic"}:
                raise HTTPException(400, "Select a supported agent or use generic.")
            if connection not in {"auto", "cooperative"}:
                raise HTTPException(400, "Select auto or cooperative connection mode.")
            if connection == "cooperative" or agent in {"claude", "generic"}:
                adapter = CooperativeAdapter(agent, thread_id, str(directory))
            elif agent == "codex":
                adapter = AttachedAdapter(thread_id, str(directory))
            else:
                adapter = create_external_adapter(agent, thread_id, str(directory))
            caller = (
                (await asyncio.to_thread(session_name, thread_id) if agent == "codex" else None)
                or (name or "").strip()
                or directory.name
                or "A session"
            )
            await self._begin(
                adapter,
                getattr(adapter, "agent_name", "Agent"),
                {
                    "provider": "attach",
                    "agent": agent,
                    "connection": "cooperative" if isinstance(adapter, CooperativeAdapter) else "auto",
                    "thread_id": thread_id,
                    "thread_name": caller,
                    "cwd": str(directory),
                },
            )
            self.ring = {"id": str(uuid4()), "name": caller, "greeting": greeting or ""}
            self.status = "ringing"
            # Made while it rings, so the first words play as soon as the user answers.
            if greeting:
                self.greeting_audio = asyncio.create_task(self._prepare_greeting(greeting))
            await self.changed()
            self.ringer = asyncio.create_task(self._ring_until_answered(self.ring))
            return self.snapshot()

    async def _prepare_greeting(self, text):
        try:
            return await self.synthesize(text)
        except Exception:
            logger.exception("The greeting could not be prepared while the call rang.")
            return None

    def _drop_greeting(self):
        if self.greeting_audio:
            self.greeting_audio.cancel()
            self.greeting_audio = None

    async def accept(self, ring_id=None):
        """Take the call. The greeting is what the user hears first."""
        async with self.lock:
            ring = self.ring
            if not ring or (ring_id and ring_id != ring["id"]):
                raise HTTPException(409, "That call is no longer ringing.")
            self._stop_ringer()
            # Ready before the ring clears, so `answered` never sees a taken call
            # with the ringing status.
            self.status = "ready"
            self.ring = None
            await self.room.start()
            if ring["greeting"]:
                await self.greet(ring["greeting"], self.greeting_audio)
            self.greeting_audio = None
            await self.changed()
            return self.snapshot()

    async def decline(self, ring_id=None):
        """Turn the call down. Nothing is left attached and nothing was said."""
        async with self.lock:
            ring = self.ring
            if not ring or (ring_id and ring_id != ring["id"]):
                raise HTTPException(409, "That call is no longer ringing.")
            self._stop_ringer()
            self._drop_greeting()
            self.ring = None
            await self._release()
            self.status = "idle"
            await self.changed()
            return self.snapshot()

    async def answered(self, ring_id, timeout=ANSWER_WAIT, sleep=asyncio.sleep):
        """Whether a ring was taken, once it stops being pending.

        The command that rang cannot see this session, so the waiting happens
        here and the answer travels back with the request. Without it an agent
        cannot tell a call nobody answered from one happening quietly, so it
        cannot tell the user which of the two occurred.

        The identifier is checked rather than the mere absence of a ring, so a
        later call cannot be mistaken for this one being answered.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ring = self.ring
            if not ring or ring.get("id") != ring_id:
                # No longer pending: either taken or stopped.
                return self.status == "ready"
            await sleep(0.5)
        return False

    async def hangup(self, expected_call_id=None, expected_adapter=None):
        """End whatever call is live, without knowing its identifier.

        The call surface has the call id to hand; a terminal does not, and having
        to look it up first is the difference between a command someone will use
        and one they will not. A remote caller passes ``expected_call_id`` and
        ``expected_adapter`` so it can only ever end the call it owns, never a
        later local one that started while this one was waiting.
        """
        # Read what to release under the lock, then release it outside. Handling a
        # ring means calling `decline`, which takes this same non-reentrant lock,
        # and holding it across that call deadlocks the whole session.
        async with self.lock:
            if expected_adapter is not None and self.adapter is not expected_adapter:
                return self.snapshot()
            ring_id = self.ring["id"] if self.ring else None
            call_id = None if ring_id else self.room.call_id
            if expected_call_id is not None and call_id != expected_call_id:
                return self.snapshot()
            adapter = self.adapter
        # A ring that has not been answered is declined rather than hung up, so
        # nothing is left attached to a session nobody is talking to.
        if ring_id:
            try:
                return await self.decline(ring_id)
            except HTTPException:
                # The ring timed out between the two locks. That is the same end.
                return self.snapshot()
        if not call_id:
            if adapter is not None and self.options and self.options.get("provider") == "attach":
                await self.close(expected_adapter=adapter)
                async with self.lock:
                    # `close` releases the adapter. Only settle the status if no
                    # later call has taken its place in the meantime.
                    if self.adapter is None:
                        self.status = "idle"
                        await self.changed()
            return self.snapshot()
        await self.room.end(call_id)
        await self.close(expected_adapter=adapter)
        async with self.lock:
            if self.adapter is None:
                self.status = "idle"
                await self.changed()
            return self.snapshot()

    def _stop_ringer(self):
        """Stop the ring timer, unless this *is* the ring timer.

        The timer ends a ring by declining it, and declining stops the timer. Left
        unchecked that cancels the running task from inside itself, which throws
        CancelledError at the next await and leaves the ring half torn down.
        """
        ringer = self.ringer
        self.ringer = None
        if ringer and not ringer.done() and ringer is not asyncio.current_task():
            ringer.cancel()

    async def _ring_until_answered(self, ring):
        """Stop ringing on its own, so an ignored call does not stay attached."""
        try:
            await asyncio.sleep(RING_TIMEOUT)
        except asyncio.CancelledError:
            return
        # Only if this is still the ring that was pending when the wait began.
        if self.ring and self.ring["id"] == ring["id"]:
            with contextlib.suppress(HTTPException):
                await self.decline(ring["id"])

    async def _release(self):
        """Let go of an attached session without touching its room state.

        `close` holds the session lock while this runs, so no step may wait on
        speech, and one failed step must not leave the others undone.
        """
        voice_warmup, self.voice_warmup = self.voice_warmup, None
        voice_connection, self.voice_connection = self.voice_connection, None
        adapter, self.adapter = self.adapter, None
        speaker, self.speaker = self.speaker, None

        async def stop(task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        steps = [self._cancel]
        if voice_warmup:
            steps.append(lambda: stop(voice_warmup))
        if voice_connection:
            steps.append(voice_connection.close)
        if adapter:
            steps.append(adapter.close)
        # A sentence can take a long time to synthesize. It is dropped, not waited for.
        if speaker:
            steps.append(lambda: stop(speaker))
        for step in steps:
            try:
                await step()
            except Exception:
                logger.exception("A step of the call teardown failed.")
        try:
            if self.room.agent and self.room.agent["client_id"] == self.client_id:
                await self.room.disconnect()
        finally:
            self.client_id = None
            self.options = None

    def _project(self, cwd):
        directory = Path(cwd).expanduser().resolve()
        if not directory.is_dir():
            raise HTTPException(400, "Select an existing project folder.")
        return directory

    async def _begin(self, adapter, name, options):
        """Connect the adapter to the room and start the speech loop."""
        if self.room.call_id or self.room.agent or self.adapter:
            raise HTTPException(409, "End the call and disconnect the current agent first.")
        self.status = "starting"
        self.error = None
        await self.changed()
        try:
            await adapter.start()
            connection = await self.room.connect(name)
        except Exception as exc:
            await adapter.close()
            self.status = "error"
            self.error = str(exc)
            await self.changed()
            raise HTTPException(400, str(exc)) from exc
        self.adapter = adapter
        self.client_id = connection["client_id"]
        self.options = options
        self.status = "ready"
        self.speaker = asyncio.create_task(self._speech_loop())
        if self.warm_stream:
            self.voice_warmup = asyncio.create_task(self._prepare_voice())
        await self.changed()
        return self.snapshot()

    async def greet(self, text, audio=None):
        """Speak a line the agent supplied, before the user says anything."""
        event = {
            "call_id": self.room.call_id,
            "turn_id": f"greeting-{uuid4()}",
            "kind": "greeting",
            "text": "",
            "time": datetime.now(UTC).isoformat(),
        }
        item_id = f"greeting-{uuid4()}"
        await self.room.emit(
            "agent.greeting", text=text, item_id=item_id, turn_id=event["turn_id"],
            name=self.room.agent["name"], kind="greeting",
        )
        message = {
            "role": "agent",
            "name": self.room.agent["name"],
            "text": text,
            "item_id": item_id,
            "turn_id": event["turn_id"],
            "call_id": event["call_id"],
            "kind": "greeting",
            "time": event["time"],
        }
        self.room.messages.append(message)
        self.audio_queue.put_nowait((event, self.generation, text, audio))
        return message

    async def _cancel(self):
        self.generation += 1
        for _, future in self.approvals.values():
            if not future.done():
                future.set_result(False)
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.task = None
        while not self.audio_queue.empty():
            entry = self.audio_queue.get_nowait()
            if entry and entry[3]:
                entry[3].cancel()
        self.tool = None

    async def resume(self):
        """Open the voice socket again after the computer slept.

        A socket from before sleep can look open and be dead, and the next reply
        would then wait on it.
        """
        async with self.lock:
            if self.voice_connection is None and self.voice_warmup is None:
                return
            warmup, self.voice_warmup = self.voice_warmup, None
            connection, self.voice_connection = self.voice_connection, None
            if warmup:
                warmup.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await warmup
            if connection:
                with contextlib.suppress(Exception):
                    await connection.close()
            if self.adapter and self.warm_stream:
                self.voice_warmup = asyncio.create_task(self._prepare_voice())

    async def interrupt(self, revision=None):
        async with self.lock:
            if revision is not None and revision != self.room.revision:
                return
            await self._cancel()
            if hasattr(self.adapter, "stop_speaking"):
                self.adapter.stop_speaking()
            if self.adapter:
                self.status = "ready"
            await self.changed()

    async def close(self, expected_adapter=None):
        async with self.lock:
            if expected_adapter is not None and self.adapter is not expected_adapter:
                # A later call took over while this one waited. Do not release it.
                return self.snapshot()
            self._stop_ringer()
            self._drop_greeting()
            self.ring = None
            await self._release()
            self.error = None
            self.status = "disconnected"
            await self.changed()

    async def submit(self, event):
        if not self.adapter:
            return
        async with self.lock:
            if event["turn_id"] != self.room.turn_id:
                return
            self.room.mark_timing(event["turn_id"], "cancel_start_ms", time.time_ns() / 1_000_000)
            await self._cancel()
            self.room.mark_timing(event["turn_id"], "cancel_end_ms", time.time_ns() / 1_000_000)
            self.error = None
            self.status = "working"
            self.task = asyncio.create_task(self._run(event, self.generation))
            await self.changed()

    def current(self, event, generation):
        if generation != self.generation or self.adapter is None:
            return False
        if event["call_id"] != self.room.call_id:
            return False
        # A greeting has no turn of its own: it is spoken before the user has said
        # anything, so judging it against the room's current turn rejected it and
        # the first thing the user should hear was never spoken at all.
        if event.get("kind") == "greeting":
            return True
        return event["turn_id"] == self.room.turn_id

    async def decide(self, approval_id, allow):
        entry = self.approvals.get(approval_id)
        if not entry or entry[1].done():
            raise HTTPException(409, "This approval request ended.")
        entry[1].set_result(allow)

    async def _prepare_voice(self):
        """Open the voice connection before the first reply."""
        if self.warm_stream is None:
            return
        try:
            template = await self.warm_stream()
            if isinstance(template, ElevenLabsStream):
                self.voice_connection = ElevenLabsConnection.from_stream(template)
                await self.voice_connection.start()
        except Exception:
            logger.exception("The voice connection could not start before the reply.")
            if self.voice_connection:
                await self.voice_connection.close()
                self.voice_connection = None

    async def _open_stream(self, event, generation):
        """Start a streaming voice, or return None to synthesize sentence by sentence."""
        if self.open_stream is None:
            return None
        playback_epoch = self.room.revision

        async def on_audio(audio):
            if not self.current(event, generation):
                return
            self.room.mark_timing(event["turn_id"], "first_audio_received_ms", time.time_ns() / 1_000_000)
            audio_id = self.cache_audio(audio)
            await self.room.audio(
                audio_id, audio, turn_id=event["turn_id"],
                expected_call_id=event["call_id"], expected_epoch=playback_epoch,
                alignment=getattr(stream, "last_alignment", None),
            )

        stream = None
        try:
            if self.voice_warmup:
                await asyncio.shield(self.voice_warmup)
            stream = (
                self.voice_connection.context(on_audio)
                if self.voice_connection else await self.open_stream(on_audio)
            )
            if stream is not None:
                if hasattr(stream, "on_text_sent"):
                    stream.on_text_sent = lambda: self.room.mark_timing(
                        event["turn_id"], "first_tts_text_ms", time.time_ns() / 1_000_000,
                    )
                await stream.start()
                self.room.mark_timing(event["turn_id"], "tts_ready_ms", time.time_ns() / 1_000_000)
            return stream
        except asyncio.CancelledError:
            if stream is not None:
                await stream.abort()
            raise
        except Exception:
            logger.exception("Streaming speech was unavailable; using sentence speech.")
            if stream is not None:
                with contextlib.suppress(Exception):
                    await stream.abort()
            return None

    async def _run(self, event, generation):
        messages = {}
        buffers = {}
        completed = set()
        spoken_size = 0
        stream = None
        streaming_available = None
        pending_speech = {}
        speech_changed = asyncio.Event()
        speech_ended = False
        queued_size = 0
        queued_events = 0
        queued_messages = set()

        async def finish_stream():
            nonlocal stream
            if stream is None:
                return
            finished = stream
            stream = None
            try:
                await finished.finish()
                if finished.error is not None and self.current(event, generation):
                    self.error = " ".join(
                        part
                        for part in (
                            "The streaming voice stopped.",
                            finished.reason(),
                            "The text is in the transcript.",
                        )
                        if part
                    )
                    await self.changed()
            finally:
                await finished.abort()

        async def queue_speech(item_id, text, final=False):
            nonlocal spoken_size
            buffer = buffers.setdefault(item_id, SentenceBuffer())
            # A local engine gets one clause-sized request at the start of the
            # turn so the first sound is not held back to a sentence end. The
            # buffer stops cutting at clauses once it has released anything.
            for sentence in buffer.feed(
                text,
                final,
                STREAM_UNIT if stream else None,
                clauses=stream is None,
            ):
                if spoken_size + len(sentence) > MAX_SPOKEN or (
                    stream is None and self.audio_queue.full()
                ):
                    self.error = "The voice queue is full. The remaining text is in the transcript."
                    continue
                spoken_size += len(sentence)
                if stream is not None:
                    # SentenceBuffer strips, and the provider reads a trailing
                    # space as the word boundary, so put the boundary back.
                    if not stream.push(f"{sentence} "):
                        self.error = "The voice stopped before the message ended. The text is in the transcript."
                        await self.changed()
                else:
                    self.audio_queue.put_nowait((event, generation, sentence, None))

        async def speak():
            nonlocal stream, streaming_available
            try:
                while True:
                    if not pending_speech:
                        if speech_ended:
                            break
                        speech_changed.clear()
                        await speech_changed.wait()
                        continue
                    item_id = next(iter(pending_speech))
                    chunks = pending_speech[item_id]
                    if chunks:
                        text, final = chunks.popleft()
                    elif speech_ended:
                        text, final = "", True
                    else:
                        speech_changed.clear()
                        await speech_changed.wait()
                        continue
                    if not self.current(event, generation):
                        return
                    if streaming_available is not False and stream is None:
                        stream = await self._open_stream(event, generation)
                        streaming_available = stream is not None
                    await queue_speech(item_id, text, final)
                    if final:
                        await finish_stream()
                        pending_speech.pop(item_id)
                await finish_stream()
            finally:
                if stream is not None:
                    await stream.abort()
                    stream = None

        def enqueue_speech(item_id, text, final):
            nonlocal queued_size, queued_events
            if queued_size + len(text) > MAX_SPOKEN or queued_events >= MAX_SPOKEN + 64 or (
                item_id not in queued_messages and len(queued_messages) >= 64
            ):
                self.error = "The voice queue is full. The remaining text is in the transcript."
                return
            queued_size += len(text)
            queued_events += 1
            queued_messages.add(item_id)
            pending_speech.setdefault(item_id, deque()).append((text, final))
            speech_changed.set()

        async def emit(event_type, **data):
            if not self.current(event, generation):
                return
            if event_type == "turn.queue_start":
                self.room.mark_timing(event["turn_id"], "queue_start_ms", time.time_ns() / 1_000_000)
                return
            if event_type == "turn.queued":
                self.room.mark_timing(event["turn_id"], "queued_ms", time.time_ns() / 1_000_000)
                return
            if event_type == "turn.accepted":
                self.room.mark_timing(event["turn_id"], "accepted_ms", time.time_ns() / 1_000_000)
                if self.tool:
                    self.tool = None
                    await self.changed()
                return
            if event_type.startswith("message."):
                item_id = data["item_id"]
                if item_id in completed:
                    return
                message = messages.get(item_id)
                if message is None:
                    message = {
                        "role": "agent",
                        "name": self.room.agent["name"],
                        "text": "",
                        "item_id": item_id,
                        "turn_id": event["turn_id"],
                        "call_id": event["call_id"],
                        "time": event["time"],
                    }
                    messages[item_id] = message
                    self.room.messages.append(message)
                old_text = message["text"]
                if event_type == "message.delta":
                    added = data["text"]
                    message["text"] += added
                else:
                    full_text = data.get("text")
                    if full_text is not None:
                        message["text"] = full_text
                    added = (
                        message["text"][len(old_text) :]
                        if message["text"].startswith(old_text)
                        else ""
                    )
                    completed.add(item_id)
                message["kind"] = data.get("kind", "message")
                if message["text"].strip():
                    # The last tool line stays on the pill until the agent says something.
                    if self.tool:
                        self.tool = None
                        await self.changed()
                    self.room.mark_timing(
                        event["turn_id"], "first_message_ms", time.time_ns() / 1_000_000
                    )
                # The event carries the new text, so a client can follow the
                # reply without reading the whole room again.
                update = await self.room.emit(
                    event_type, turn_id=event["turn_id"], item_id=item_id,
                    text=added if event_type == "message.delta" else message["text"],
                    kind=message["kind"], name=message["name"],
                )
                message["seq"] = update["seq"]
                if added or event_type == "message.done":
                    enqueue_speech(item_id, added, event_type == "message.done")
            elif event_type == "tool.status":
                self.tool = data.get("text") or None
                await self.changed()
            elif event_type == "usage":
                self.usage = data["usage"]

        async def approve(action, details):
            if not self.current(event, generation):
                return False
            approval_id = str(uuid4())
            future = asyncio.get_running_loop().create_future()
            self.approvals[approval_id] = (
                {"id": approval_id, "action": action, "details": details},
                future,
            )
            self.status = "approval"
            await self.changed()
            try:
                return await asyncio.wait_for(future, 180)
            except TimeoutError:
                return False
            finally:
                self.approvals.pop(approval_id, None)
                if self.current(event, generation):
                    self.status = "working"
                    await self.changed()

        speech_task = asyncio.create_task(speak(), name="turn-speech")
        try:
            if hasattr(self.adapter, "begin_turn"):
                self.adapter.begin_turn(event)
            await self.adapter.run(event.get("agent_text", event["text"]), emit, approve)
            speech_ended = True
            speech_changed.set()
            await speech_task
            if self.current(event, generation):
                self.room.answered = True
                self.status = "ready"
                self.tool = None
                await self.room.emit("turn.done", turn_id=event["turn_id"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("The managed turn failed.")
            if self.current(event, generation):
                self.room.answered = True
                self.status = "error"
                self.error = str(exc) or "The agent session failed. Connect again."
                self.tool = None
                await self.changed()
        finally:
            speech_task.cancel()
            await asyncio.gather(speech_task, return_exceptions=True)

    async def _speech_loop(self):
        while True:
            entry = await self.audio_queue.get()
            if entry is None:
                return
            event, generation, text, prepared = entry
            if not self.current(event, generation):
                if prepared:
                    prepared.cancel()
                continue
            playback_epoch = self.room.revision
            try:
                audio = (await prepared if prepared else None) or await self.synthesize(text)
                if self.current(event, generation):
                    audio_id = self.cache_audio(audio)
                    await self.room.audio(
                        audio_id, audio,
                        turn_id=event["turn_id"],
                        expected_call_id=event["call_id"], expected_epoch=playback_epoch,
                        text=text,
                        **({"kind": "greeting"} if event.get("kind") == "greeting" else {}),
                    )
            except Exception:
                logger.exception("The managed voice failed.")
                if self.current(event, generation):
                    self.error = "The voice failed. The text is in the transcript."
                    await self.changed()
