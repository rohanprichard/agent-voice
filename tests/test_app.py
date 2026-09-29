import asyncio
import io
import os
import threading
import time
import wave

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from talktome import inbox
from talktome.app import create_app


class FakeSpeech:
    def __init__(self):
        self.state = {"status": "ready", "model_id": "small", "progress": 100}
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False

    def saved_model(self):
        return None

    def restore_providers(self):
        pass

    def saved_voice(self):
        return "default"

    def save_settings(self, **changes):
        pass

    def settings(self):
        return {}

    def status(self):
        return {**self.state, "tts_available": True}

    def voices(self):
        return [{"id": "default", "name": "Test voice"}]

    def synthesize(self, text, voice):
        if self.block:
            self.started.set()
            assert self.release.wait(5)
        file = io.BytesIO()
        with wave.open(file, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\0\0" * 1600)
        return file.getvalue()

    def transcribe(self, audio):
        return {"text": "Hello from the microphone.", "language": "en", "duration_ms": 1000}


@pytest.fixture
def app():
    return create_app(token="test-token", speech=FakeSpeech())


@pytest.fixture
def client(app):
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        yield client


def test_auth_origin_host_and_browser_cookie(app):
    with TestClient(app) as client:
        assert client.get("/v1/state").status_code == 401
        assert client.post("/v1/auth", json={"token": "wrong"}).status_code == 401
        assert client.post("/v1/auth", json={"token": "错误"}).status_code == 401
        assert (
            client.post(
                "/v1/auth", json={"token": "test-token"}, headers={"Origin": "https://other.test"}
            ).status_code
            == 403
        )
        response = client.post("/v1/auth", json={"token": "test-token"})
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert client.get("/v1/state").status_code == 200
        assert client.get("/v1/state", headers={"Host": "evil.test"}).status_code == 400
        assert client.get("/v1/state", headers={"Origin": "null"}).status_code == 403


def test_audio_upload_and_size_limit(app, client):
    call_id = client.portal.call(app.state.room.start)["call_id"]
    speech_end_ms = time.time_ns() / 1_000_000 - 1000
    capture_end_ms = speech_end_ms + 600
    response = client.post(
        "/v1/call/audio",
        params={"call_id": call_id},
        content=b"test audio",
        headers={
            "X-TalkToMe-Speech-End-Ms": str(speech_end_ms),
            "X-TalkToMe-Capture-End-Ms": str(capture_end_ms),
        },
    )
    assert response.json()["event"]["text"] == "Hello from the microphone."
    turn_id = response.json()["event"]["turn_id"]
    timing = client.get("/v1/state").json()["room"]["timing"]
    assert timing["speech_end_ms"] == speech_end_ms
    assert timing["capture_end_ms"] == capture_end_ms
    assert timing["transcribed_ms"] >= capture_end_ms
    assert client.post(
        "/v1/call/timing",
        json={"call_id": call_id, "turn_id": turn_id, "first_audio_ms": time.time_ns() / 1_000_000},
    ).status_code == 200
    assert client.get("/v1/state").json()["room"]["timing"]["first_audio_ms"]
    response = client.post("/v1/stt/transcribe", content=b"x" * (8 * 1024 * 1024 + 1))
    assert response.status_code == 413


async def test_long_poll_wakes_for_new_message(app):
    room = app.state.room
    call = await room.start()
    task = asyncio.create_task(room.poll(room.sequence, timeout=1))
    await asyncio.sleep(0)
    await room.utterance(call["call_id"], "Hello")
    result = await task
    assert result["events"][0]["type"] == "user.utterance"


async def test_event_gap_requires_reset(app):
    room = app.state.room
    for _ in range(520):
        await room.emit("test")
    result = await room.poll(0, 0)
    assert result["reset"] is True
    assert len(result["events"]) == 512


# ------------------------------- the way in for commands that have no network


def wait_for_reply(request, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = inbox.reply_for(request)
        if reply is not None:
            return reply
        time.sleep(0.02)
    raise AssertionError("the app never answered the request")


def attach_to(managed, snapshot):
    """Point the session at a stub, so the test does not need a real Codex."""

    async def attach(thread, cwd, greeting=None, name=None, agent="codex", connection="auto"):
        attach_to.seen = {"thread": thread, "cwd": cwd, "greeting": greeting, "name": name}
        return snapshot

    managed.attach = attach


def test_a_command_can_ring_the_app_without_a_connection(app):
    # This is the path that replaces the loopback call: an agent's sandbox blocks
    # connections to 127.0.0.1, so the request arrives as a file and the answer
    # leaves as one. Nothing here touches the network.
    attach_to(app.state.managed, {"status": "ringing", "ring": {"id": "r-1", "name": "Auth"}})

    async def answered(ring_id, timeout=None):
        assert ring_id == "r-1"
        return True

    app.state.managed.answered = answered
    with TestClient(app):
        request = inbox.ask(
            "call",
            {"thread": "t-1", "cwd": "/tmp", "greeting": "Hey", "name": "Auth", "wait": True},
        )
        reply = wait_for_reply(request)

    assert reply["ok"] is True
    assert reply["result"]["answered"] is True
    assert attach_to.seen == {"thread": "t-1", "cwd": "/tmp", "greeting": "Hey", "name": "Auth"}


def test_not_waiting_is_honoured_at_the_far_end(app):
    attach_to(app.state.managed, {"status": "ringing", "ring": {"id": "r-1"}})

    async def answered(ring_id, timeout=None):
        raise AssertionError("a request that did not ask to wait must not be waited on")

    app.state.managed.answered = answered
    with TestClient(app):
        request = inbox.ask("call", {"thread": "t-1", "cwd": "/tmp", "wait": False})
        reply = wait_for_reply(request)

    assert "answered" not in reply["result"]


def test_a_refusal_travels_back_as_a_reason_the_agent_can_repeat(app):
    async def attach(thread, cwd, greeting=None, name=None, agent="codex", connection="auto"):
        raise HTTPException(409, "That session has no transcript yet.")

    app.state.managed.attach = attach
    with TestClient(app):
        reply = wait_for_reply(inbox.ask("call", {"thread": "t-1", "cwd": "/tmp"}))

    assert reply["ok"] is False
    assert reply["error"] == "That session has no transcript yet."


def test_a_request_without_a_session_is_refused_before_anything_is_started(app):
    async def attach(*args, **kwargs):
        raise AssertionError("a call with no session must not reach the session")

    app.state.managed.attach = attach
    with TestClient(app):
        reply = wait_for_reply(inbox.ask("call", {"cwd": "/tmp"}))

    assert reply["ok"] is False
    assert "needs one" in reply["error"]


def test_ending_a_call_arrives_the_same_way(app):
    ended = []

    async def hangup():
        ended.append(True)
        return {"status": "idle"}

    app.state.managed.hangup = hangup
    with TestClient(app):
        reply = wait_for_reply(inbox.ask("end"))

    assert reply["result"] == {"status": "idle"}
    assert ended == [True]


def test_a_request_is_handled_once_and_not_again(app):
    # Retiring the request is the claim on it. A ring takes ten seconds to
    # resolve, and the next pass over the folder must not start a second one.
    attach_to(app.state.managed, {"status": "ringing", "ring": {"id": "r-1"}})
    rings = []

    async def attach(thread, cwd, greeting=None, name=None, agent="codex", connection="auto"):
        rings.append(thread)
        return {"status": "ringing", "ring": {"id": "r-1"}}

    app.state.managed.attach = attach

    async def answered(ring_id, timeout=None):
        return False

    app.state.managed.answered = answered
    with TestClient(app):
        reply = wait_for_reply(inbox.ask("call", {"thread": "t-1", "cwd": "/tmp"}))
        assert reply["ok"] is True
        time.sleep(0.4)

    assert rings == ["t-1"]


def test_the_finished_request_is_removed_but_the_answer_is_left(app):
    async def hangup():
        return {"status": "idle"}

    app.state.managed.hangup = hangup
    with TestClient(app):
        request = inbox.ask("end")
        wait_for_reply(request)

    assert inbox.pending() == []
    assert inbox.reply_for(request)["result"] == {"status": "idle"}


def test_a_note_left_for_an_app_that_never_came_up_is_swept_on_startup(app):
    # Otherwise it would ring the user the next time the app opened, for a command
    # that finished long ago.
    request = inbox.ask("end")
    old = time.time() - inbox.STALE - 1
    os.utime(request.path, (old, old))

    async def hangup():
        raise AssertionError("a stale request must not be honoured")

    app.state.managed.hangup = hangup
    with TestClient(app):
        time.sleep(0.4)

    assert inbox.pending() == []
