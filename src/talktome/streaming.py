"""Speech that starts before the reply is finished.

ElevenLabs' WebSocket endpoint accepts text as it arrives and generates audio
on its own schedule, so a caller can hand it agent deltas directly instead of
waiting for sentence boundaries. Its schedule is the buffer; buffering again on
this side would only add delay.

Two provider rules shape this module:

* Every text message has to end at a word boundary, because ElevenLabs treats
  the trailing space as the cue to consider the text. Raw model deltas split
  words, so text is held until the last space before it goes out.
* Audio arrives base64 in ``{"audio": ...}`` frames and ends with
  ``{"isFinal": true}``. The frames are headerless PCM, so each one is wrapped
  in a WAV container to match every other audio payload in the app.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import struct
from urllib.parse import urlencode
from uuid import uuid4

logger = logging.getLogger(__name__)

STREAM_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice}/stream-input"

# ElevenLabs counts characters before it generates. The default ladder
# ([120, 160, 250, 290]) waits for 120 characters, which is several sentences of
# delay. Short turns want a much earlier first chunk.
DEFAULT_SCHEDULE = [50, 90, 150, 220]

STREAM_MODEL = "eleven_flash_v2_5"
STREAM_RATE = 24000

# A spoken turn is capped the same way the sentence path caps it.
MAX_SPOKEN = 16000

# Leave generation enough time to drain, but never hold a turn open forever.
FINISH_TIMEOUT = 30.0
CONNECT_TIMEOUT = 8.0
WRITE_TIMEOUT = 3.0


def pcm_to_wav(payload: bytes, rate: int) -> bytes:
    """Wrap headerless 16-bit mono little-endian PCM in a WAV container."""
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", 36 + len(payload)),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16),
            b"data",
            struct.pack("<I", len(payload)),
            payload,
        ]
    )


class WordBuffer:
    """Hold text back to the last word boundary.

    Deltas arrive mid-word (``"con"``, ``"nect"``). Sending those as separate
    messages would make ElevenLabs read two words, so only the part up to the
    final space is released and the tail waits for the rest of the word.
    """

    def __init__(self):
        self.pending = ""

    def push(self, text: str) -> str:
        """Return the text that is safe to send, keeping any partial word."""
        self.pending += text
        cut = max(self.pending.rfind(" "), self.pending.rfind("\n"))
        if cut < 0:
            return ""
        ready, rest = self.pending[: cut + 1], self.pending[cut + 1 :]
        if not ready.strip():
            # A lone separator is not worth a message of its own.
            return ""
        self.pending = rest
        return ready

    def flush(self) -> str:
        """Release everything left, terminated so the provider accepts it."""
        ready, self.pending = self.pending, ""
        if ready and not ready.endswith(" "):
            ready += " "
        return ready


async def default_connect(url: str, headers: dict):
    """Open the socket, isolating the library's header argument name."""
    import websockets

    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:  # websockets < 14
        return await websockets.connect(url, extra_headers=headers, max_size=None)


class ElevenLabsStream:
    """One streaming synthesis session, normally the length of one turn."""

    def __init__(
        self,
        connect,
        *,
        voice: str,
        api_key: str,
        on_audio,
        model: str = STREAM_MODEL,
        schedule=None,
        rate: int = STREAM_RATE,
    ):
        self.connect = connect
        self.voice = voice
        self.api_key = api_key
        self.on_audio = on_audio
        self.model = model
        self.schedule = list(schedule or DEFAULT_SCHEDULE)
        self.rate = rate
        self.socket = None
        self.buffer = WordBuffer()
        self.outgoing: asyncio.Queue = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []
        self.sent = 0
        self.error: Exception | None = None
        self.aborting = False
        self.last_alignment = None
        self.on_text_sent = None

    def url(self) -> str:
        query = urlencode(
            {"model_id": self.model, "output_format": f"pcm_{self.rate}", "sync_alignment": "true"},
        )
        return f"{STREAM_URL.format(voice=self.voice)}?{query}"

    async def start(self):
        self.socket = await self.connect(
            self.url(),
            {"xi-api-key": self.api_key},
        )
        await self._write(
            {
                "text": " ",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                "generation_config": {"chunk_length_schedule": self.schedule},
            }
        )
        self.tasks = [
            asyncio.create_task(self._sender(), name="tts-send"),
            asyncio.create_task(self._receiver(), name="tts-receive"),
        ]
        return self

    async def _write(self, message):
        if self.socket is None:
            return
        await self.socket.send(json.dumps(message))

    async def _fail(self, exc):
        """Record a real failure. An abort closes the socket on purpose."""
        if self.aborting:
            return
        # The first failure is the cause. A later one is the other task seeing
        # the socket that the first failure closed.
        if self.error is None:
            self.error = exc
        logger.warning("The streaming voice failed.", exc_info=exc)

    async def _sender(self):
        try:
            while True:
                text = await self.outgoing.get()
                if text is None:
                    await self._write({"text": ""})
                    return
                await self._write({"text": text})
                if self.on_text_sent:
                    self.on_text_sent()
        except Exception as exc:  # noqa: BLE001 - a dead socket must not kill the turn.
            await self._fail(exc)

    async def _receiver(self):
        try:
            async for raw in self.socket:
                message = json.loads(raw)
                audio = message.get("audio")
                if audio:
                    self.last_alignment = message.get("normalizedAlignment") or message.get("alignment")
                    await self.on_audio(pcm_to_wav(base64.b64decode(audio), self.rate))
                if message.get("isFinal"):
                    return
            if not self.aborting:
                await self._fail(RuntimeError("The voice connection closed early."))
        except Exception as exc:  # noqa: BLE001 - _fail reports it and the turn carries on.
            await self._fail(exc)

    def reason(self) -> str:
        """The provider's own explanation when it closed the socket on purpose."""
        reason = getattr(self.error, "reason", "")
        if not isinstance(reason, str):
            return ""
        return " ".join(reason.split())[:200]

    def push(self, text: str) -> bool:
        """Accept reply text. Returns False once the turn has spoken too much."""
        if self.sent + len(text) > MAX_SPOKEN:
            return False
        self.sent += len(text)
        ready = self.buffer.push(text)
        if ready:
            self.outgoing.put_nowait(ready)
        return True

    async def finish(self):
        """Flush the tail, ask for the remaining audio, and wait for it."""
        tail = self.buffer.flush()
        if tail:
            self.outgoing.put_nowait(tail)
        self.outgoing.put_nowait(None)
        if not self.tasks:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*self.tasks), FINISH_TIMEOUT)
        except TimeoutError:
            await self._fail(TimeoutError("The voice took too long to finish."))

    async def abort(self):
        """Drop unspoken text and stop generation, not just playback."""
        self.aborting = True
        for task in self.tasks:
            task.cancel()
        if self.socket is not None:
            with contextlib.suppress(Exception):
                await self.socket.close()
        for task in self.tasks:
            with contextlib.suppress(BaseException):
                await task
        self.tasks = []
        self.buffer = WordBuffer()
        self.outgoing = asyncio.Queue()


class ElevenLabsConnection:
    """Keep one output socket for a call. Give each message a separate context."""

    def __init__(self, connect, *, voice, api_key, model=STREAM_MODEL, schedule=None, rate=STREAM_RATE):
        self.connect = connect
        self.voice = voice
        self.api_key = api_key
        self.model = model
        self.schedule = list(schedule or DEFAULT_SCHEDULE)
        self.rate = rate
        self.socket = None
        self.reader = None
        self.contexts = {}
        self.start_lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()
        self.closed = False
        self.retiring = set()

    @classmethod
    def from_stream(cls, stream):
        return cls(
            stream.connect, voice=stream.voice, api_key=stream.api_key,
            model=stream.model, schedule=stream.schedule, rate=stream.rate,
        )

    async def start(self):
        async with self.start_lock:
            if self.closed:
                raise RuntimeError("The voice connection is closed.")
            if self.socket is not None and self.reader and not self.reader.done():
                return
            query = urlencode({
                "model_id": self.model, "output_format": f"pcm_{self.rate}",
                "sync_alignment": "true", "inactivity_timeout": 180,
            })
            url = f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice}/multi-stream-input?{query}"
            socket = await asyncio.wait_for(
                self.connect(url, {"xi-api-key": self.api_key}), CONNECT_TIMEOUT,
            )
            self.socket = socket
            self.reader = asyncio.create_task(self._receive(socket), name="call-voice-receive")

    def context(self, on_audio):
        return ElevenLabsContext(self, on_audio)

    def retire(self, context_id, socket):
        async def close_context():
            with contextlib.suppress(Exception):
                await self.write({"context_id": context_id, "close_context": True}, socket)

        task = asyncio.create_task(close_context(), name="voice-context-close")
        self.retiring.add(task)
        task.add_done_callback(self.retiring.discard)

    async def write(self, message, expected_socket=None):
        async with self.write_lock:
            socket = self.socket
            if socket is None or (expected_socket is not None and socket is not expected_socket):
                raise RuntimeError("The voice connection is unavailable.")
            await asyncio.wait_for(socket.send(json.dumps(message)), WRITE_TIMEOUT)

    async def _receive(self, socket):
        error = RuntimeError("The voice connection closed before the message finished.")
        try:
            async for raw in socket:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    continue
                context_id = message.get("contextId") or message.get("context_id")
                context = self.contexts.get(context_id)
                if message.get("error"):
                    if context:
                        context.fail(RuntimeError("The voice provider rejected the message."))
                        continue
                    raise RuntimeError("The voice provider rejected the connection.")
                if context is None or context.aborting or context.done.is_set():
                    continue
                if message.get("audio"):
                    context.last_alignment = message.get("normalizedAlignment") or message.get("alignment")
                    await context.on_audio(pcm_to_wav(base64.b64decode(message["audio"]), self.rate))
                if message.get("isFinal") or message.get("is_final"):
                    context.done.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Report transport and audio callback errors to the context.
            error = exc
        finally:
            if self.socket is socket:
                self.socket = None
            for context in list(self.contexts.values()):
                if context.socket is socket:
                    context.fail(error)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(socket.close(), WRITE_TIMEOUT)

    async def close(self):
        self.closed = True
        reader, self.reader = self.reader, None
        socket, self.socket = self.socket, None
        for context in list(self.contexts.values()):
            context.fail(RuntimeError("The call ended."))
        if reader:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
        if socket:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(socket.close(), WRITE_TIMEOUT)
        for task in self.retiring:
            task.cancel()
        await asyncio.gather(*self.retiring, return_exceptions=True)
        self.retiring.clear()
        self.contexts.clear()


class ElevenLabsContext:
    """Send one message in order. Stop its output when the user interrupts."""

    def __init__(self, connection, on_audio):
        self.connection = connection
        self.on_audio = on_audio
        self.socket = None
        self.id = str(uuid4())
        self.buffer = WordBuffer()
        self.outgoing = asyncio.Queue(maxsize=MAX_SPOKEN + 1)
        self.done = asyncio.Event()
        self.sender = None
        self.sent = 0
        self.error = None
        self.aborting = False
        self.last_alignment = None
        self.on_text_sent = None

    async def start(self):
        await self.connection.start()
        if self.connection.retiring:
            await asyncio.shield(asyncio.gather(*self.connection.retiring, return_exceptions=True))
        self.socket = self.connection.socket
        if len(self.connection.contexts) >= 5:
            raise RuntimeError("The voice connection has too many active messages.")
        self.connection.contexts[self.id] = self
        await self.connection.write({
            "context_id": self.id, "text": " ",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            "generation_config": {"chunk_length_schedule": self.connection.schedule},
        }, self.socket)
        self.sender = asyncio.create_task(self._send(), name="message-voice-send")
        return self

    def fail(self, error):
        if not self.aborting and not self.done.is_set():
            self.error = error
            self.done.set()

    def reason(self):
        return "The voice connection failed." if self.error else ""

    def push(self, text):
        if self.aborting or self.done.is_set() or self.sent + len(text) > MAX_SPOKEN:
            return False
        self.sent += len(text)
        ready = self.buffer.push(text)
        if ready:
            self.outgoing.put_nowait(ready)
        return True

    async def _send(self):
        try:
            while not self.done.is_set():
                text = await self.outgoing.get()
                if text is None:
                    await self.connection.write({"context_id": self.id, "flush": True}, self.socket)
                    return
                await self.connection.write({"context_id": self.id, "text": text}, self.socket)
                if self.on_text_sent:
                    self.on_text_sent()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Release the waiter after a transport error.
            self.fail(exc)

    async def finish(self):
        tail = self.buffer.flush()
        if tail:
            self.outgoing.put_nowait(tail)
        self.outgoing.put_nowait(None)
        if not self.sent:
            return
        try:
            await asyncio.wait_for(self.done.wait(), FINISH_TIMEOUT)
        except TimeoutError:
            self.fail(TimeoutError("The voice took too long to finish."))

    async def abort(self):
        self.aborting = True
        self.connection.contexts.pop(self.id, None)
        if self.sender:
            self.sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.sender
            self.sender = None
        self.done.set()
        if self.connection.socket is not None:
            self.connection.retire(self.id, self.socket)
