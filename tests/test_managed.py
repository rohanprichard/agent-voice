import asyncio
import contextlib

import httpx
import pytest
from fastapi import HTTPException

from talktome import managed as managed_module
from talktome.app import create_app
from talktome.managed import ManagedSession, SentenceBuffer
from talktome.room import Room


class FakeAdapter:
    def __init__(self, cwd=None):
        self.session_id = "test-thread"
        self.calls = []
        self.cancelled = False
        self.waiting = asyncio.Event()
        self.closed = False

    async def start(self):
        pass

    async def close(self):
        self.closed = True

    async def run(self, text, emit, approve):
        self.calls.append(text)
        await emit("message.delta", item_id="progress", text="I will read it. ", kind="commentary")
        await emit("message.done", item_id="progress", text="I will read it. ", kind="commentary")
        if text == "approval":
            allowed = await approve("Write", {"file": "example.txt"})
            await emit("message.done", item_id="final", text=str(allowed), kind="final_answer")
        elif text == "wait":
            await emit("message.delta", item_id="pending", text="Still ", kind="final_answer")
            self.waiting.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        elif text == "fail":
            raise RuntimeError("Test host failure.")
        else:
            await emit("message.delta", item_id="final", text="Done. ", kind="final_answer")
            await emit("message.done", item_id="final", text="Done. ", kind="final_answer")
            await emit("message.done", item_id="final", text="Done. ", kind="final_answer")


class FakeStream:
    """A streaming voice that only records what it was asked to speak."""

    def __init__(self, on_audio):
        self.on_audio = on_audio
        self.text = []
        self.started = False
        self.finished = False
        self.aborted = False
        self.error = None

    def reason(self):
        return getattr(self.error, "reason", "")

    async def start(self):
        self.started = True
        return self

    def push(self, text):
        self.text.append(text)
        return True

    async def finish(self):
        self.finished = True
        await self.on_audio(b"RIFF-stream")

    async def abort(self):
        self.aborted = True


async def wait_for(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


@contextlib.asynccontextmanager
async def session(tmp_path, synthesize=None, open_stream=None, adapter=FakeAdapter, start=True):
    room = Room()
    audio = []

    async def speech(text):
        audio.append(text)
        return b"RIFF"

    managed = ManagedSession(room, synthesize or speech, lambda data: "audio-id", open_stream)
    if start:
        # The same startup a ring uses, without the ring in front of it.
        await managed._begin(
            adapter(str(tmp_path)), "Codex", {"provider": "attach", "cwd": str(tmp_path)}
        )
        # Room.start is what opens a call, so a caller that opens its own (ringing
        # does) must not have one made for it.
        await room.start()
    try:
        yield room, managed, audio
    finally:
        await managed.close()


async def test_progress_final_and_audio_are_separate(tmp_path):
    async with session(tmp_path) as (room, managed, audio):
        event = await room.utterance(room.call_id, "hello")
        await managed.submit(event)
        await managed.task
        await wait_for(lambda: len(audio) == 2)
        assert [m["text"] for m in room.messages] == ["hello", "I will read it. ", "Done. "]
        assert audio == ["I will read it.", "Done."]
        assert room.answered
        assert managed.status == "ready"
        assert room.snapshot()["agent"] == {"name": "Codex"}
        assert len(managed.adapter.calls) == 1
        assert room.snapshot()["timing"]["first_message_ms"]


async def test_text_arrives_before_speech_finishes(tmp_path):
    release = asyncio.Event()

    async def synthesize(text):
        await release.wait()
        return b"RIFF"

    async with session(tmp_path, synthesize) as (room, managed, _):
        await managed.submit(await room.utterance(room.call_id, "hello"))
        await managed.task
        assert room.messages[-1]["text"] == "Done. "
        assert not any(e["type"] == "agent.audio" for e in room.events)
        release.set()
        await wait_for(lambda: any(e["type"] == "agent.audio" for e in room.events))


async def test_interrupt_stops_work_and_drops_late_audio(tmp_path):
    release = asyncio.Event()
    started = asyncio.Event()

    async def synthesize(text):
        started.set()
        await release.wait()
        return b"RIFF"

    async with session(tmp_path, synthesize) as (room, managed, _):
        await managed.submit(await room.utterance(room.call_id, "wait"))
        await started.wait()
        await room.interrupt(room.call_id)
        await managed.interrupt()
        assert managed.adapter.cancelled
        release.set()
        await asyncio.sleep(0.01)
        assert not any(e["type"] == "agent.audio" for e in room.events)


async def test_new_message_cancels_old_turn_and_keeps_thread(tmp_path):
    async with session(tmp_path) as (room, managed, _):
        adapter = managed.adapter
        await managed.submit(await room.utterance(room.call_id, "wait"))
        await adapter.waiting.wait()
        await managed.submit(await room.utterance(room.call_id, "next"))
        await managed.task
        assert adapter.cancelled
        assert managed.adapter is adapter
        assert adapter.calls == ["wait", "next"]
        assert room.answered


@pytest.mark.parametrize("allow", [True, False])
async def test_approval_requires_explicit_decision(tmp_path, allow):
    async with session(tmp_path) as (room, managed, _):
        await managed.submit(await room.utterance(room.call_id, "approval"))
        await wait_for(lambda: bool(managed.approvals))
        assert not room.answered
        assert managed.status == "approval"
        approval = managed.snapshot()["approvals"][0]
        await managed.decide(approval["id"], allow)
        await managed.task
        assert room.messages[-1]["text"] == str(allow)
        assert not managed.approvals
        with pytest.raises(HTTPException):
            await managed.decide(approval["id"], True)


async def test_failure_ends_wait_and_is_visible(tmp_path):
    async with session(tmp_path) as (room, managed, _):
        await managed.submit(await room.utterance(room.call_id, "fail"))
        await managed.task
        assert room.answered
        assert managed.snapshot()["error"] == "Test host failure."


async def test_ending_the_call_stops_work_and_keeps_the_session(tmp_path):
    async with session(tmp_path) as (room, managed, _):
        first = managed.adapter
        await managed.submit(await room.utterance(room.call_id, "wait"))
        await first.waiting.wait()
        await room.end(room.call_id)
        await managed.interrupt()
        assert first.cancelled
        assert managed.adapter is first


def fake_external(monkeypatch, adapter=FakeAdapter):
    """Ring in as an external agent, without a Hermes or OpenClaw host."""

    def create(agent, thread_id, cwd):
        made = adapter(cwd)
        made.session_id = thread_id
        return made

    monkeypatch.setattr("talktome.managed.create_external_adapter", create)


async def test_an_attached_call_over_http_needs_the_token(tmp_path, monkeypatch):
    from test_app import FakeSpeech

    fake_external(monkeypatch)
    app = create_app(token="test", speech=FakeSpeech())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        assert (await client.get("/v1/managed")).status_code == 401
        client.headers["Authorization"] = "Bearer test"
        ring = {"thread": "h-1", "cwd": str(tmp_path / "missing"), "agent": "hermes"}
        assert (await client.post("/v1/attach/start", json=ring)).status_code == 400
        ring["cwd"] = str(tmp_path)
        assert (await client.post("/v1/attach/start", json=ring)).status_code == 200
        assert (await client.post("/v1/attach/accept", json={})).status_code == 200
        call_id = app.state.room.call_id
        assert (
            await client.post("/v1/call/text", json={"call_id": call_id, "text": "hello"})
        ).status_code == 200
        await app.state.managed.task
        result = (await client.get("/v1/state")).json()
        assert result["room"]["messages"][-1]["text"] == "Done. "
        assert result["managed"]["session_id"] == "h-1"
        assert (await client.get("/v1/managed")).json()["session"]["session_id"] == "h-1"
        assert (await client.post("/v1/agent/disconnect")).status_code == 200
        assert app.state.room.agent is None


@pytest.mark.parametrize("allow", [True, False])
async def test_the_approval_route_resolves_an_attached_request(tmp_path, monkeypatch, allow):
    # The call surface answers an approval through this route. Without an answer
    # the request waits 180 seconds and is denied.
    from test_app import FakeSpeech

    fake_external(monkeypatch)
    app = create_app(token="test", speech=FakeSpeech())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer test"},
        ) as client,
    ):
        ring = {"thread": "h-1", "cwd": str(tmp_path), "agent": "hermes"}
        assert (await client.post("/v1/attach/start", json=ring)).status_code == 200
        assert (await client.post("/v1/attach/accept", json={})).status_code == 200
        call_id = app.state.room.call_id
        await client.post("/v1/call/text", json={"call_id": call_id, "text": "approval"})
        await wait_for(lambda: bool(app.state.managed.approvals))
        state = (await client.get("/v1/state")).json()["managed"]
        assert state["status"] == "approval"
        [approval] = state["approvals"]
        assert approval["action"] == "Write"
        assert approval["details"] == {"file": "example.txt"}
        answer = await client.post(f"/v1/managed/approvals/{approval['id']}", json={"allow": allow})
        assert answer.status_code == 200
        await app.state.managed.task
        state = (await client.get("/v1/state")).json()
        assert state["managed"]["approvals"] == []
        assert state["managed"]["status"] == "ready"
        assert state["room"]["messages"][-1]["text"] == str(allow)
        again = await client.post(f"/v1/managed/approvals/{approval['id']}", json={"allow": True})
        assert again.status_code == 409


def test_sentence_buffer_waits_for_boundaries_and_omits_code():
    buffer = SentenceBuffer()
    assert buffer.feed("Hello") == []
    assert buffer.feed(". Next ") == ["Hello."]
    assert buffer.feed("sentence.", final=True) == ["Next sentence."]
    buffer = SentenceBuffer()
    assert buffer.feed("```python\nx = 1. ") == []
    assert buffer.feed("\n```\nDone.", final=True) == ["Done."]


async def test_streaming_voice_replaces_sentence_synthesis(tmp_path):
    streams = []

    async def open_stream(on_audio):
        stream = FakeStream(on_audio)
        streams.append(stream)
        return stream

    async with session(tmp_path, open_stream=open_stream) as (room, managed, audio):
        await managed.submit(await room.utterance(room.call_id, "hello"))
        await managed.task
        # Each message is flushed when it ends, so a tool call after it does not
        # hold its audio back. The next message opens a new stream.
        assert len(streams) == 2
        assert all(stream.started and stream.finished and stream.aborted for stream in streams)
        # Every release keeps the trailing boundary the provider reads.
        assert [stream.text for stream in streams] == [["I will read it. "], ["Done. "]]
        # The blocking sentence path must not also run.
        assert audio == []
        played = [e for e in room.events if e["type"] == "agent.audio"]
        assert len(played) == 2
        assert played[0]["audio_id"] == "audio-id"
        assert [m["text"] for m in room.messages] == ["hello", "I will read it. ", "Done. "]


async def test_interrupt_aborts_streaming_generation(tmp_path):
    streams = []

    async def open_stream(on_audio):
        stream = FakeStream(on_audio)
        streams.append(stream)
        return stream

    async with session(tmp_path, open_stream=open_stream) as (room, managed, _):
        await managed.submit(await room.utterance(room.call_id, "wait"))
        await managed.adapter.waiting.wait()
        assert managed.status == "working"
        played = sum(e["type"] == "agent.audio" for e in room.events)
        await managed.interrupt()
        # The progress message was complete and already spoke. The message still
        # being written is stopped, not finished.
        assert streams[-1].aborted
        assert not streams[-1].finished
        assert sum(e["type"] == "agent.audio" for e in room.events) == played


async def test_a_stream_that_will_not_start_falls_back_to_sentences(tmp_path):
    class Broken(FakeStream):
        async def start(self):
            raise RuntimeError("no socket")

    async def open_stream(on_audio):
        return Broken(on_audio)

    async with session(tmp_path, open_stream=open_stream) as (room, managed, audio):
        await managed.submit(await room.utterance(room.call_id, "hello"))
        await managed.task
        await wait_for(lambda: len(audio) == 2)
        assert audio == ["I will read it.", "Done."]
        assert managed.status == "ready"
        assert any(e["type"] == "agent.audio" for e in room.events)


async def test_no_stream_configured_keeps_the_sentence_path(tmp_path):
    async with session(tmp_path) as (room, managed, audio):
        await managed.submit(await room.utterance(room.call_id, "hello"))
        await managed.task
        await wait_for(lambda: len(audio) == 2)
        assert audio == ["I will read it.", "Done."]


async def test_a_stream_that_dies_mid_turn_reports_itself(tmp_path):
    class Closed(ConnectionError):
        reason = "Invalid API key"

    class Dying(FakeStream):
        async def finish(self):
            self.finished = True
            self.error = Closed("closed")

    streams = []

    async def open_stream(on_audio):
        stream = Dying(on_audio)
        streams.append(stream)
        return stream

    async with session(tmp_path, open_stream=open_stream) as (room, managed, _):
        await managed.submit(await room.utterance(room.call_id, "hello"))
        await managed.task
        assert managed.error == (
            "The streaming voice stopped. Invalid API key The text is in the transcript."
        )
        assert room.answered
        assert [m["text"] for m in room.messages] == ["hello", "I will read it. ", "Done. "]


class ScriptedAdapter(FakeAdapter):
    """Replies with one fixed line, for tests about how speech is chunked."""

    reply = ""

    async def run(self, text, emit, approve):
        self.calls.append(text)
        await emit("message.done", item_id="final", text=self.reply, kind="final_answer")


def test_clause_mode_releases_a_long_opening_clause():
    buffer = SentenceBuffer()
    text = "Let me look at the file, and then I will tell you what I found."
    assert buffer.feed(text, False, None, clauses=True) == ["Let me look at the file,"]


def test_clause_mode_ignores_a_clause_too_short_to_speak():
    buffer = SentenceBuffer()
    # "Well," is under the minimum, so the cut waits for the sentence end.
    assert buffer.feed("Well, that is right. ", False, None, clauses=True) == [
        "Well, that is right."
    ]


def test_clause_mode_still_prefers_a_sentence_end():
    buffer = SentenceBuffer()
    # The first chunk is a whole sentence because one ended before any clause was
    # long enough, and the rest of the turn is not cut at clauses either.
    assert buffer.feed("Ready. Then a clause, follows. ", False, None, clauses=True) == [
        "Ready.",
        "Then a clause, follows.",
    ]


def test_clause_mode_prefers_a_sentence_end_over_an_earlier_clause():
    buffer = SentenceBuffer()
    text = "A long enough opening clause, and then the sentence ends here. "
    assert buffer.feed(text, False, None, clauses=True) == [
        "A long enough opening clause, and then the sentence ends here."
    ]


def test_clause_mode_is_off_by_default():
    buffer = SentenceBuffer()
    text = "Let me look at the file, and then I will tell you what I found."
    assert buffer.feed(text, False, None) == []


async def test_only_the_first_chunk_uses_clause_mode(tmp_path):
    class OneClause(ScriptedAdapter):
        reply = (
            "Let me look at the file, and the answer is in auth.py, "
            "where the token check runs first."
        )

    async with session(tmp_path, adapter=OneClause) as (
        room,
        managed,
        audio,
    ):
        await managed.submit(await room.utterance(room.call_id, "hello"))
        await managed.task
        await wait_for(lambda: len(audio) == 2)
        # The first chunk is a clause, so speech starts before the sentence ends.
        assert audio[0] == "Let me look at the file,"
        # The rest is one chunk: the extra request is paid once, not per clause.
        assert audio[1] == "and the answer is in auth.py, where the token check runs first."


async def test_a_streamed_turn_is_not_cut_at_clauses(tmp_path):
    class OneClause(ScriptedAdapter):
        reply = "Let me look at the file, and the answer is in auth.py, and that is all."

    streams = []

    async def open_stream(on_audio):
        stream = FakeStream(on_audio)
        streams.append(stream)
        return stream

    async with session(
        tmp_path, open_stream=open_stream, adapter=OneClause
    ) as (room, managed, _):
        await managed.submit(await room.utterance(room.call_id, "hello"))
        await managed.task
        # The provider does its own chunking, so clause cuts would double up. The
        # only cut is at the first space after STREAM_UNIT characters.
        assert streams[0].text == [
            "Let me look at the file, and the answer is in auth.py, ",
            "and that is all. ",
        ]
        assert len(streams[0].text[0].strip()) >= managed_module.STREAM_UNIT


# ------------------------------------------------------------ ringing in


class AttachAdapter:
    """An attached session, without a terminal or a rollout file."""

    agent_name = "Codex"

    def __init__(self, thread_id, cwd=None):
        self.session_id = thread_id
        self.cwd = cwd
        self.closed = False

    async def start(self):
        pass

    async def run(self, text, emit, approve):
        await emit("message.done", item_id="m1", text="Answered here.", kind="final_message")

    async def close(self):
        self.closed = True


@contextlib.asynccontextmanager
async def attached(tmp_path):
    # Its own patch scope, so the tests read as one line and the real adapter is
    # restored even if one of them fails.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("talktome.managed.AttachedAdapter", AttachAdapter)
        # No session yet: ringing is what starts this one.
        async with session(tmp_path, start=False) as (room, managed, audio):
            yield room, managed, audio


async def test_ringing_does_not_start_a_call(tmp_path):
    # Ringing asks a question. Creating the call before it is answered would speak
    # the greeting into an empty room and show a live pill to nobody.
    async with attached(tmp_path) as (room, managed, _):
        snapshot = await managed.attach("thread-9", str(tmp_path), "Hello?", "Auth refactor")
        assert snapshot["status"] == "ringing"
        assert room.call_id is None
        await asyncio.sleep(0.01)
        assert not any(event["type"] == "agent.audio" for event in room.events)
        assert snapshot["ring"]["name"] == "Auth refactor"


async def test_the_greeting_is_made_while_it_rings(tmp_path):
    async with attached(tmp_path) as (room, managed, audio):
        await managed.attach("thread-9", str(tmp_path), "Hello?")
        await wait_for(lambda: audio == ["Hello?"])
        await managed.accept()
        await wait_for(lambda: any(event["type"] == "agent.audio" for event in room.events))
        # The audio made during the ring is the audio that plays.
        assert audio == ["Hello?"]


async def test_a_declined_ring_throws_the_greeting_away(tmp_path):
    release = asyncio.Event()
    started = []

    async def synthesize(text):
        started.append(text)
        await release.wait()
        return b"RIFF"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("talktome.managed.AttachedAdapter", AttachAdapter)
        async with session(tmp_path, synthesize, start=False) as (_room, managed, _):
            await managed.attach("thread-9", str(tmp_path), "Hello?")
            await wait_for(lambda: started == ["Hello?"])
            prepared = managed.greeting_audio
            await managed.decline()
            await asyncio.sleep(0)
            assert prepared.cancelled()
            assert managed.greeting_audio is None


async def test_an_answer_is_reported_while_the_call_is_still_opening(tmp_path):
    # `accept` awaits the room and the greeting. A caller that looks in that gap
    # must already see the call as taken.
    async with attached(tmp_path) as (room, managed, _):
        snapshot = await managed.attach("thread-9", str(tmp_path), "Hello?")
        opening = asyncio.Event()
        release = asyncio.Event()
        start = room.start

        async def slow_start():
            opening.set()
            await release.wait()
            return await start()

        room.start = slow_start
        accepting = asyncio.create_task(managed.accept())
        await opening.wait()
        assert await managed.answered(snapshot["ring"]["id"], sleep=lambda _: asyncio.sleep(0))
        release.set()
        await accepting


async def test_the_caller_name_falls_back_to_the_project_folder(tmp_path):
    project = tmp_path / "billing-service"
    project.mkdir()
    async with attached(tmp_path) as (_room, managed, _):
        snapshot = await managed.attach("thread-9", str(project))
        assert snapshot["ring"]["name"] == "billing-service"


@pytest.mark.parametrize("agent_name", ["Codex", "Claude"])
async def test_the_session_name_does_not_replace_agent_identity(tmp_path, monkeypatch, agent_name):
    monkeypatch.setattr("talktome.managed.session_name", lambda thread: "Review call UI")
    monkeypatch.setattr(AttachAdapter, "agent_name", agent_name)
    async with attached(tmp_path) as (_room, managed, _):
        snapshot = await managed.attach("thread-9", str(tmp_path), name="Talk")
        assert snapshot["ring"]["name"] == "Review call UI"
        assert snapshot["thread_name"] == "Review call UI"
        assert managed.room.agent["name"] == agent_name


async def test_answering_starts_the_call_and_speaks_the_greeting(tmp_path):
    async with attached(tmp_path) as (room, managed, audio):
        await managed.attach("thread-9", str(tmp_path), "Hey — what's up?", "Auth refactor")
        answered = await managed.accept(managed.ring["id"])
        assert answered["status"] == "ready"
        assert answered["ring"] is None
        assert room.call_id
        assert [m["text"] for m in room.messages] == ["Hey — what's up?"]
        assert room.messages[0]["name"] == "Codex"
        await wait_for(lambda: len(audio) == 1)
        assert audio == ["Hey — what's up?"]
        await wait_for(lambda: any(e["type"] == "agent.audio" for e in room.events))
        greeting = next(e for e in room.events if e["type"] == "agent.audio")
        assert greeting["kind"] == "greeting"


async def test_a_call_can_be_answered_without_naming_it(tmp_path):
    async with attached(tmp_path) as (_room, managed, _):
        await managed.attach("thread-9", str(tmp_path), "Hello?")
        assert (await managed.accept())["status"] == "ready"


async def test_declining_leaves_nothing_attached(tmp_path):
    async with attached(tmp_path) as (room, managed, audio):
        await managed.attach("thread-9", str(tmp_path), "Hello?")
        adapter = managed.adapter
        declined = await managed.decline(managed.ring["id"])
        assert declined["status"] == "idle"
        assert declined["connected"] is False
        assert room.call_id is None
        assert adapter.closed is True
        assert audio == []
        assert room.agent is None


async def test_a_stale_answer_cannot_take_a_later_call(tmp_path):
    # The surface sends the ring id back, so a reply that arrives after the ring
    # ended cannot answer the next one.
    async with attached(tmp_path) as (_room, managed, _):
        await managed.attach("thread-9", str(tmp_path), "Hello?")
        await managed.decline()
        await managed.attach("thread-9", str(tmp_path), "Hello again?")
        with pytest.raises(HTTPException):
            await managed.accept("not-this-ring")
        with pytest.raises(HTTPException):
            await managed.decline("not-this-ring")


def test_the_ring_and_its_waits_agree():
    from talktome import cli

    assert managed_module.RING_TIMEOUT == 30
    assert managed_module.ANSWER_WAIT > managed_module.RING_TIMEOUT
    assert cli.REQUEST_TIMEOUT > managed_module.ANSWER_WAIT


async def test_an_unanswered_ring_stops_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr("talktome.managed.RING_TIMEOUT", 0.05)
    async with attached(tmp_path) as (_room, managed, _):
        await managed.attach("thread-9", str(tmp_path), "Hello?")
        assert managed.status == "ringing"
        await wait_for(lambda: managed.status == "idle")
        assert managed.ring is None
        assert managed.adapter is None


async def test_hanging_up_needs_no_call_identifier(tmp_path):
    # A terminal has no call id to hand, so the command cannot require one.
    async with attached(tmp_path) as (room, managed, _):
        await managed.attach("thread-9", str(tmp_path), "Hello?")
        await managed.accept()
        assert room.call_id
        snapshot = await managed.hangup()
        assert room.call_id is None
        assert snapshot["status"] == "idle"
        assert snapshot["connected"] is False


async def test_hanging_up_while_ringing_declines_instead(tmp_path):
    async with attached(tmp_path) as (room, managed, _):
        await managed.attach("thread-9", str(tmp_path), "Hello?")
        await managed.hangup()
        assert managed.ring is None
        assert room.call_id is None
        assert managed.status == "idle"


async def test_hanging_up_when_nothing_is_live_is_harmless(tmp_path):
    async with attached(tmp_path) as (room, managed, _):
        snapshot = await managed.hangup()
        assert snapshot["connected"] is False
        assert room.call_id is None


async def test_the_call_end_control_releases_the_attached_session(tmp_path, monkeypatch):
    from test_app import FakeSpeech

    monkeypatch.setattr("talktome.managed.AttachedAdapter", AttachAdapter)
    monkeypatch.setattr("talktome.managed.session_name", lambda thread: None)
    app = create_app(token="test", speech=FakeSpeech())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        client.headers["Authorization"] = "Bearer test"
        first = await client.post(
            "/v1/attach/start", json={"thread": "thread-9", "cwd": str(tmp_path)}
        )
        assert first.status_code == 200
        answer = await client.post(
            "/v1/attach/accept", json={"ring_id": first.json()["ring"]["id"]}
        )
        assert answer.status_code == 200
        call_id = app.state.room.call_id
        ended = await client.post("/v1/call/end", json={"call_id": call_id})
        assert ended.status_code == 200
        assert app.state.managed.adapter is None
        assert app.state.room.agent is None
        again = await client.post(
            "/v1/attach/start", json={"thread": "thread-9", "cwd": str(tmp_path)}
        )
        assert again.status_code == 200


async def test_an_answered_call_takes_speech_like_any_other(tmp_path):
    # After answering, an attached call is an ordinary call: the ring is only a
    # question at the front of it.
    async with attached(tmp_path) as (room, managed, _audio):
        await managed.attach("thread-9", str(tmp_path), "Hello?")
        await managed.accept()
        await managed.submit(await room.utterance(room.call_id, "what changed?"))
        await managed.task
        assert [m["text"] for m in room.messages][-1] == "Answered here."
        assert room.messages[-1]["name"] == "Codex"


async def test_the_ring_says_whether_it_was_taken(tmp_path):
    # The command that rang cannot see this session, so this is how it finds out
    # whether to tell the agent the user picked up or never did.
    async with attached(tmp_path) as (_room, managed, _):
        snapshot = await managed.attach("thread-9", str(tmp_path), "Hello?")
        ring_id = snapshot["ring"]["id"]
        waiter = asyncio.create_task(managed.answered(ring_id))
        await asyncio.sleep(0)
        await managed.accept(ring_id)
        assert await waiter is True


async def test_a_ring_that_stopped_itself_reads_as_unanswered(tmp_path):
    async with attached(tmp_path) as (_room, managed, _):
        snapshot = await managed.attach("thread-9", str(tmp_path), "Hello?")
        ring_id = snapshot["ring"]["id"]
        waiter = asyncio.create_task(managed.answered(ring_id))
        await asyncio.sleep(0)
        await managed.decline(ring_id)
        assert await waiter is False


async def test_a_later_ring_does_not_count_as_this_one_being_answered(tmp_path):
    # The identifier is checked rather than the mere absence of a ring, so a ring
    # that ends just as another begins cannot be read as an answer.
    async with attached(tmp_path) as (_room, managed, _):
        first = (await managed.attach("thread-9", str(tmp_path), "Hello?"))["ring"]["id"]
        await managed.decline(first)
        await managed.attach("thread-9", str(tmp_path), "Hello again?")
        assert await managed.answered(first, timeout=0, sleep=lambda _: None) is False


async def test_waiting_for_an_answer_gives_up_rather_than_hanging(tmp_path):
    async with attached(tmp_path) as (_room, managed, _):
        ring_id = (await managed.attach("thread-9", str(tmp_path), "Hello?"))["ring"]["id"]
        assert await managed.answered(ring_id, timeout=0, sleep=lambda _: None) is False


# ------------------------------------------------------------ session ids

OPENCLAW_KEYS = [
    "agent:main:whatsapp:direct:+15551234567",
    "agent:main:whatsapp:group:123@g.us",
    "agent:main:matrix:channel:!room:example.org",
    "agent:main:openclaw-weixin:direct:o9cq802hhmfc@im.wechat",
]


@pytest.mark.parametrize("key", OPENCLAW_KEYS)
async def test_a_real_openclaw_session_key_can_ring(tmp_path, monkeypatch, key):
    fake_external(monkeypatch)
    async with session(tmp_path, start=False) as (_room, managed, _):
        snapshot = await managed.attach(key, str(tmp_path), agent="openclaw")
        assert snapshot["status"] == "ringing"
        assert snapshot["session_id"] == key


@pytest.mark.parametrize("thread", ["*", "thread-*", "../thread", "a b"])
async def test_a_codex_id_that_could_widen_the_file_search_is_refused(tmp_path, thread):
    async with attached(tmp_path) as (_room, managed, _):
        with pytest.raises(HTTPException) as error:
            await managed.attach(thread, str(tmp_path))
        assert error.value.status_code == 400
        assert managed.adapter is None


@pytest.mark.parametrize(
    "thread", ["", "has space", "tab\there", "line\nbreak", "bell\x07", "x" * 513]
)
def test_other_agents_refuse_whitespace_control_characters_and_long_ids(thread):
    assert managed_module.valid_session_id(thread, "openclaw") is False


def test_other_agents_accept_an_id_up_to_the_limit():
    assert managed_module.valid_session_id("agent:thread-1", "hermes") is True
    assert managed_module.valid_session_id("x" * 512, "generic") is True


async def test_closing_does_not_wait_for_a_slow_sentence(tmp_path):
    started = asyncio.Event()

    async def synthesize(text):
        started.set()
        await asyncio.Event().wait()

    async with session(tmp_path, synthesize) as (room, managed, _):
        await managed.submit(await room.utterance(room.call_id, "hello"))
        await started.wait()
        async with asyncio.timeout(1):
            await managed.close()
        assert managed.speaker is None
        assert room.agent is None


async def test_a_failed_teardown_step_does_not_stop_the_others(tmp_path):
    class BrokenClose(FakeAdapter):
        async def close(self):
            raise RuntimeError("The host went away.")

    async with session(tmp_path, adapter=BrokenClose) as (room, managed, _):
        speaker = managed.speaker
        await managed.close()
        assert speaker.done()
        assert room.agent is None
        assert managed.status == "disconnected"


async def test_waking_up_opens_the_voice_socket_again(tmp_path):
    class Connection:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    warmed = []

    async def warm():
        warmed.append(True)

    async with session(tmp_path) as (_room, managed, _):
        old = Connection()
        managed.voice_connection = old
        managed.warm_stream = warm
        managed._prepare_voice = warm
        await managed.resume()
        await managed.voice_warmup
        assert old.closed
        assert managed.voice_connection is None
        assert warmed == [True]


async def test_waking_up_without_a_voice_socket_does_nothing(tmp_path):
    async with session(tmp_path) as (_room, managed, _):
        await managed.resume()
        assert managed.voice_warmup is None
