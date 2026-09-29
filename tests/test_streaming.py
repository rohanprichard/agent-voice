"""Streaming speech: WAV wrapping, word boundaries, and clean shutdown."""

import asyncio
import base64
import io
import json
import wave

from talktome.streaming import (
    DEFAULT_SCHEDULE,
    ElevenLabsStream,
    WordBuffer,
    pcm_to_wav,
)


def frame(payload: bytes) -> str:
    return json.dumps({"audio": base64.b64encode(payload).decode()})


def test_pcm_is_wrapped_as_a_readable_wav():
    payload = b"\x01\x02" * 64
    data = pcm_to_wav(payload, 24000)
    with wave.open(io.BytesIO(data), "rb") as file:
        assert file.getnchannels() == 1
        assert file.getsampwidth() == 2
        assert file.getframerate() == 24000
        assert file.readframes(file.getnframes()) == payload


def test_word_buffer_never_releases_a_partial_word():
    buffer = WordBuffer()
    assert buffer.push("con") == ""
    assert buffer.push("nect") == ""
    assert buffer.push(" the sock") == "connect the "
    assert buffer.push("et") == ""
    assert buffer.flush() == "socket "


def test_word_buffer_flush_of_a_finished_sentence_keeps_one_space():
    buffer = WordBuffer()
    buffer.push("All done. ")
    assert buffer.flush() == ""


class FakeSocket:
    """A stand-in for the ElevenLabs socket, driven by the test."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.closed = False
        self.drained = asyncio.Event()

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    async def close(self):
        self.closed = True
        self.drained.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        while not self.replies:
            if self.closed:
                raise StopAsyncIteration
            await asyncio.sleep(0.01)
        item = self.replies.pop(0)
        if item is None:
            raise StopAsyncIteration
        return item


class Recorder:
    def __init__(self, socket, voices=("voice-1",)):
        self.socket = socket
        self.voices = list(voices)
        self.calls = []
        self.audio = []

        async def on_audio(chunk):
            self.audio.append(chunk)

        self.on_audio = on_audio

    async def connect(self, url, headers):
        self.calls.append((url, headers))
        return self.socket

    def stream(self, **kwargs):
        return ElevenLabsStream(self.connect, on_audio=self.on_audio, **kwargs)


def build(replies=(), **kwargs):
    socket = FakeSocket(replies)
    recorder = Recorder(socket)
    stream = recorder.stream(voice="voice-1", api_key="key-1", **kwargs)
    return socket, recorder, stream


async def test_start_requests_pcm_and_lowers_the_first_chunk():
    socket, recorder, stream = build()
    await stream.start()
    url, headers = recorder.calls[0]
    assert url.startswith("wss://api.elevenlabs.io/v1/text-to-speech/voice-1/stream-input?")
    assert "output_format=pcm_24000" in url
    opening = socket.sent[0]
    assert opening["text"] == " "
    assert opening["generation_config"]["chunk_length_schedule"] == DEFAULT_SCHEDULE
    assert DEFAULT_SCHEDULE[0] < 120  # below the provider default of 120 characters
    assert headers == {"xi-api-key": "key-1"}
    await stream.abort()


async def test_audio_frames_arrive_as_playable_wav():
    payload = b"\x07\x00" * 32
    _socket, recorder, stream = build([frame(payload), json.dumps({"isFinal": True})])
    await stream.start()
    stream.push("Hello there friend. ")
    await stream.finish()
    assert len(recorder.audio) == 1
    with wave.open(io.BytesIO(recorder.audio[0]), "rb") as file:
        assert file.getframerate() == 24000
        assert file.readframes(file.getnframes()) == payload


async def test_partial_words_wait_for_the_rest_of_the_word():
    socket, _recorder, stream = build()
    await stream.start()
    for delta in ("The con", "nect", "ion is fine. "):
        stream.push(delta)
    await asyncio.sleep(0.05)
    texts = [message["text"] for message in socket.sent[1:]]
    assert texts == ["The ", "connection is fine. "]
    await stream.abort()


async def test_finish_flushes_the_tail_and_closes_generation():
    socket, _recorder, stream = build([json.dumps({"isFinal": True})])
    await stream.start()
    stream.push("Done now")
    await stream.finish()
    texts = [message["text"] for message in socket.sent[1:]]
    assert texts == ["Done ", "now ", ""]
    assert stream.error is None


async def test_abort_stops_generation_without_closing_the_text():
    socket, _recorder, stream = build()
    await stream.start()
    stream.push("Half a thou")
    await stream.abort()
    assert all(message["text"] != "" for message in socket.sent[1:])
    assert socket.closed
    assert stream.tasks == []


async def test_push_reports_when_a_turn_speaks_too_much():
    _socket, _recorder, stream = build()
    await stream.start()
    assert stream.push("x" * 100) is True
    assert stream.push("y" * 20000) is False
    await stream.abort()


async def test_a_dead_socket_is_recorded_rather_than_raised():
    class Broken(FakeSocket):
        async def send(self, payload):
            if self.sent:
                raise ConnectionResetError("socket closed")
            await super().send(payload)

    socket = Broken([None])
    recorder = Recorder(socket)
    stream = recorder.stream(voice="voice-1", api_key="key-1")
    await stream.start()
    stream.push("Something to say. ")
    await stream.finish()
    assert isinstance(stream.error, ConnectionResetError)


def test_sentence_buffer_still_releases_whole_sentences_by_default():
    from talktome.managed import SentenceBuffer

    buffer = SentenceBuffer()
    parts = buffer.feed("One. Two. Three", False) + buffer.feed("", True)
    assert parts == ["One.", "Two.", "Three"]


def test_streaming_unit_cuts_at_spaces_and_keeps_every_word():
    from talktome.managed import SentenceBuffer

    text = "alpha beta gamma delta epsilon zeta eta theta "
    buffer = SentenceBuffer()
    parts = buffer.feed(text, True, 20)
    assert len(parts) > 1  # it released early rather than waiting for a sentence
    assert " ".join(parts) == text.strip()
    # Each part is at least one unit long, cut at the next space.
    assert parts == ["alpha beta gamma delta", "epsilon zeta eta theta"]


def test_streaming_unit_never_splits_a_word_even_without_spaces():
    from talktome.managed import SentenceBuffer

    buffer = SentenceBuffer()
    assert buffer.feed("supercalifragilistic", False, 5) == []
    assert buffer.feed("", True, 5) == ["supercalifragilistic"]


async def test_provider_reason_is_available_for_the_report():
    class Closed(ConnectionError):
        reason = "  Invalid   API key  "

    _socket, _recorder, stream = build()
    stream.error = Closed("closed")
    assert stream.reason() == "Invalid API key"


async def test_reason_is_empty_when_the_socket_did_not_explain():
    _socket, _recorder, stream = build()
    assert stream.reason() == ""
