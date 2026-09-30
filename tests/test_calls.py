import asyncio
import json
import os
import stat
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_app import FakeSpeech

from talktome import calls, external_adapters
from talktome.app import create_app
from talktome.attach import AttachedAdapter
from talktome.calls import CALLBACK_PREFIX, CallHistory, call_back, terminal_argv
from talktome.claude_resume import ClaudeResumeAdapter
from talktome.managed import ManagedSession
from talktome.room import Room

CLAUDE_ID = "0b6a3c55-5f3e-4a52-9d4c-3f2a8e6c1d10"


class FakeRing:
    """Enough of a ringing session for the store to read."""

    def __init__(self, agent="codex", thread="t-1", cwd="/tmp", name="Auth refactor"):
        self.options = {"agent": agent, "thread_id": thread, "thread_name": name, "cwd": cwd}
        self.ring = {"id": "r-1", "name": name}
        self.room = Room()
        self.error = None


def history(tmp_path):
    return CallHistory(tmp_path / "calls")


def add(store, **fields):
    entry = {
        "id": fields.pop("id", f"c-{len(store.records)}"),
        "agent": "codex",
        "session_id": "t-1",
        "name": "Auth refactor",
        "cwd": "/tmp",
        "started_at": datetime.now(UTC).isoformat(),
        "answered_at": None,
        "ended_at": None,
        "duration": None,
        "outcome": "missed",
        "callback": False,
        "call_id": None,
        "transcript": False,
        **fields,
    }
    store.records.append(entry)
    store.save()
    return entry


async def test_an_answered_call_is_recorded_with_its_duration(tmp_path):
    store = history(tmp_path)
    session = FakeRing()
    store.record("ringing", session)
    assert store.records[0]["outcome"] is None
    await session.room.start()
    store.record("answered", session)
    store.records[0]["answered_at"] = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
    store.record("ended", session)
    entry = store.records[0]
    assert entry["outcome"] == "answered"
    assert entry["name"] == "Auth refactor"
    assert entry["agent"] == "codex"
    assert entry["session_id"] == "t-1"
    assert 89 <= entry["duration"] <= 91
    assert entry["call_id"] == session.room.call_id
    # Off is the default, so nothing was said is kept.
    assert entry["transcript"] is False
    assert not (tmp_path / "calls" / "transcripts").exists()


def test_the_files_are_private(tmp_path):
    store = history(tmp_path)
    store.record("ringing", FakeRing())
    assert stat.S_IMODE(os.stat(tmp_path / "calls").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(tmp_path / "calls" / "calls.jsonl").st_mode) == 0o600


def test_missed_and_declined_are_final(tmp_path):
    store = history(tmp_path)
    store.record("ringing", FakeRing())
    store.record("missed", FakeRing())
    # The timer declines the ring after it records the miss.
    store.record("declined", FakeRing())
    store.record("ended", FakeRing())
    store.record("ringing", FakeRing(name="Billing"))
    store.record("declined", FakeRing())
    store.record("ended", FakeRing())
    assert [entry["outcome"] for entry in store.list()] == ["declined", "missed"]
    assert all(entry["ended_at"] for entry in store.records)


def test_a_failed_start_is_recorded(tmp_path):
    store = history(tmp_path)
    session = FakeRing()
    session.error = "That session has no transcript yet."
    store.record("failed", session, session.options)
    assert store.records[0]["outcome"] == "failed"
    assert store.records[0]["error"] == "That session has no transcript yet."
    assert store.current is None


def test_a_ring_left_by_a_stopped_app_loads_as_missed(tmp_path):
    store = history(tmp_path)
    store.record("ringing", FakeRing())
    assert history(tmp_path).records[0]["outcome"] == "missed"


def test_the_history_keeps_the_last_500_calls(tmp_path):
    store = history(tmp_path)
    for index in range(calls.MAX_CALLS + 5):
        store.record("ringing", FakeRing(name=f"Call {index}"))
        store.record("missed", FakeRing())
    assert len(store.records) == calls.MAX_CALLS
    assert store.records[0]["name"] == "Call 5"
    assert len(history(tmp_path).records) == calls.MAX_CALLS


async def test_transcripts_are_saved_only_when_on(tmp_path):
    store = history(tmp_path)
    store.set_mode("7d")
    session = FakeRing()
    store.record("ringing", session)
    await session.room.start()
    store.record("answered", session)
    event = await session.room.utterance(session.room.call_id, "What changed?")
    assert event["text"] == "What changed?"
    session.room.messages.append(
        {"role": "agent", "name": "Codex", "text": "Two files.", "call_id": session.room.call_id}
    )
    store.record("ended", session)
    entry = store.records[0]
    assert entry["transcript"] is True
    path = tmp_path / "calls" / "transcripts" / f"{entry['id']}.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [line["text"] for line in store.transcript(entry["id"])] == ["What changed?", "Two files."]
    # The mode survives a restart.
    assert history(tmp_path).mode == "7d"
    # Turning transcripts off removes the saved ones.
    store.set_mode("off")
    assert not path.exists()
    assert store.transcript(entry["id"]) is None


def test_prune_removes_old_and_orphaned_transcripts(tmp_path):
    store = history(tmp_path)
    store.set_mode("7d")
    folder = tmp_path / "calls" / "transcripts"
    old = add(store, transcript=True, ended_at=(datetime.now(UTC) - timedelta(days=8)).isoformat())
    new = add(store, transcript=True, ended_at=datetime.now(UTC).isoformat())
    for name in (old["id"], new["id"], "orphan"):
        calls.write_private(folder / f"{name}.json", "[]")
    store.prune()
    assert sorted(path.name for path in folder.iterdir()) == [f"{new['id']}.json"]
    assert old["transcript"] is False
    store.set_mode("30d")
    assert new["transcript"] is True
    with pytest.raises(HTTPException):
        store.set_mode("forever")


def test_delete_and_clear(tmp_path):
    store = history(tmp_path)
    first = add(store)
    add(store)
    assert store.delete(first["id"])
    assert not store.delete(first["id"])
    assert len(history(tmp_path).records) == 1
    store.clear()
    assert history(tmp_path).records == []


def test_call_back_is_off_for_generic():
    reason = calls.callback_reason
    assert reason({"agent": "generic", "session_id": "x"})
    assert reason({"agent": "claude", "session_id": "my-connection"})
    assert reason({"agent": "claude", "session_id": CLAUDE_ID}) is None
    assert reason({"agent": "codex", "session_id": "t-1"}) is None
    assert reason({"agent": "hermes", "session_id": "h-1"}) is None


def test_open_in_terminal_quotes_the_folder():
    argv = terminal_argv("/tmp/it's here; rm -rf ~", "t-1")
    assert argv[0] == "/usr/bin/osascript"
    assert argv[-1] == "cd '/tmp/it'\"'\"'s here; rm -rf ~' && codex resume t-1"


def test_open_in_terminal_only_for_codex(tmp_path):
    ran = []
    entry = {"agent": "codex", "session_id": "t-1", "cwd": str(tmp_path)}
    calls.open_in_terminal(entry, run=lambda argv, **kwargs: ran.append(argv))
    assert ran[0][-1] == f"cd {tmp_path} && codex resume t-1"
    with pytest.raises(HTTPException):
        calls.open_in_terminal({**entry, "agent": "claude"}, run=lambda *a, **k: None)
    with pytest.raises(HTTPException):
        calls.open_in_terminal({**entry, "session_id": "t 1; ls"}, run=lambda *a, **k: None)


# --------------------------------------------------------------- call back


async def wait_for(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


def managed_session(store):
    spoken = []

    async def speech(text):
        spoken.append(text)
        return b"RIFF"

    managed = ManagedSession(Room(), speech, lambda data: "audio-id")
    managed.history = store
    return managed, spoken


def completed(turn, kind, text):
    return {
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "turn_id": turn,
            "item": {"id": f"{kind}-1", "type": kind, "content": [{"type": "text", "text": text}]},
        },
    }


class FakeRollout:
    def __init__(self, batches):
        self.batches = list(batches)
        self.path = Path("/nonexistent/rollout.jsonl")

    def skip_history(self):
        pass

    def read_new(self):
        return self.batches.pop(0) if self.batches else []


def fake_codex(delivered, replies=True):
    class FakeCodex(AttachedAdapter):
        async def start(self):
            self.poll = 0.001
            self.ack_timeout = 0.5
            prompt = f"{CALLBACK_PREFIX}\n\nWhat changed?"
            batches = [[]]
            if replies:
                batches.append([
                    completed("u-1", "UserMessage", prompt),
                    completed("u-1", "AgentMessage", "Two files."),
                    {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "u-1"}},
                ])
            self.rollout = FakeRollout(batches)
            self.queue_fallback = True
            self.deliver = lambda thread, text, cwd: delivered.append((thread, text, cwd))

    return FakeCodex


async def test_codex_call_back_starts_live_and_prefixes_the_first_turn(tmp_path, monkeypatch):
    store = history(tmp_path)
    entry = add(store, cwd=str(tmp_path))
    delivered = []
    monkeypatch.setattr(calls, "rollout_path", lambda thread: tmp_path / "rollout.jsonl")
    monkeypatch.setattr(calls, "AttachedAdapter", fake_codex(delivered))
    managed, spoken = managed_session(store)
    try:
        snapshot = await call_back(managed, store, entry["id"])
        # No ring: the user placed the call.
        assert snapshot["ring"] is None
        assert snapshot["status"] == "ready"
        assert managed.room.call_id
        await wait_for(lambda: spoken == ["Calling Auth refactor."])
        latest = store.list()[0]
        assert latest["callback"] is True
        assert latest["outcome"] == "answered"
        event = await managed.room.utterance(managed.room.call_id, "What changed?")
        await managed.submit(event)
        await managed.task
        assert delivered == [("t-1", f"{CALLBACK_PREFIX}\n\nWhat changed?", str(tmp_path))]
        assert managed.room.messages[-1]["text"] == "Two files."
        # Only the first turn carries the prefix.
        assert managed.adapter.run.__func__ is AttachedAdapter.run
        # One call at a time.
        with pytest.raises(HTTPException) as busy:
            await call_back(managed, store, entry["id"])
        assert busy.value.status_code == 409
    finally:
        await managed.close()
    assert store.list()[0]["ended_at"]


async def test_codex_call_back_without_a_rollout_offers_terminal(tmp_path, monkeypatch):
    store = history(tmp_path)
    entry = add(store, cwd=str(tmp_path))
    monkeypatch.setattr(calls, "rollout_path", lambda thread: None)
    managed, _ = managed_session(store)
    with pytest.raises(HTTPException) as closed:
        await call_back(managed, store, entry["id"])
    assert closed.value.status_code == 409
    assert closed.value.detail == {"message": "That Codex session is closed.", "action": "open_terminal"}
    assert store.get(entry["id"])["closed"] is True
    assert managed.adapter is None


async def test_codex_queue_failure_marks_the_session_closed(tmp_path, monkeypatch):
    store = history(tmp_path)
    entry = add(store, cwd=str(tmp_path))
    monkeypatch.setattr(calls, "rollout_path", lambda thread: tmp_path / "rollout.jsonl")
    monkeypatch.setattr(calls, "AttachedAdapter", fake_codex([]))
    managed, _ = managed_session(store)
    try:
        await call_back(managed, store, entry["id"])

        def refuse(thread, text, cwd):
            raise ValueError("Codex would not accept the message for this session.")

        managed.adapter.deliver = refuse
        event = await managed.room.utterance(managed.room.call_id, "What changed?")
        await managed.submit(event)
        await managed.task
        assert managed.error == "That Codex session is closed. Open it in Terminal from Calls."
        assert store.get(entry["id"])["closed"] is True
    finally:
        await managed.close()


def fake_claude(tmp_path):
    script = tmp_path / "claude"
    events = [
        {"type": "system", "subtype": "init", "session_id": CLAUDE_ID},
        {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m-1"}}},
        {"type": "stream_event", "event": {
            "type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "name": "Read"}}},
        {"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}},
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        {"type": "stream_event", "parent_tool_use_id": "tool-1", "event": {
            "type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Subagent."}}},
        {"type": "stream_event", "event": {
            "type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}},
        {"type": "stream_event", "event": {
            "type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Two "}}},
        {"type": "stream_event", "event": {
            "type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "files."}}},
        {"type": "stream_event", "event": {"type": "content_block_stop", "index": 1}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "Two files."},
    ]
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"record = {{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd()}}\n"
        f"open({str(tmp_path / 'claude-run.json')!r}, 'w').write(json.dumps(record))\n"
        f"for event in {events!r}:\n"
        "    print(json.dumps(event), flush=True)\n"
    )
    script.chmod(0o755)
    return script


async def test_claude_call_back_resumes_the_session_for_each_turn(tmp_path, monkeypatch):
    store = history(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    entry = add(store, agent="claude", session_id=CLAUDE_ID, cwd=str(project))
    script = fake_claude(tmp_path)
    monkeypatch.setattr("talktome.claude_resume.find_command", lambda name: str(script))
    managed, _ = managed_session(store)
    try:
        await call_back(managed, store, entry["id"])
        assert isinstance(managed.adapter, ClaudeResumeAdapter)
        event = await managed.room.utterance(managed.room.call_id, "What changed?")
        await managed.submit(event)
        await managed.task
        assert managed.status == "ready", managed.error
        run = json.loads((tmp_path / "claude-run.json").read_text())
        assert run["argv"] == [
            "-p", "--resume", CLAUDE_ID, "--output-format", "stream-json",
            "--verbose", "--include-partial-messages",
        ]
        assert run["stdin"] == f"{CALLBACK_PREFIX}\n\nWhat changed?"
        assert os.path.realpath(run["cwd"]) == os.path.realpath(project)
        agent = [message["text"] for message in managed.room.messages if message["role"] == "agent"]
        assert agent[-1] == "Two files."
        assert "Subagent." not in "".join(agent)
    finally:
        await managed.close()


async def test_claude_stops_on_interrupt(tmp_path):
    script = tmp_path / "claude"
    script.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    script.chmod(0o755)
    adapter = ClaudeResumeAdapter(CLAUDE_ID, str(tmp_path))
    adapter.binary = str(script)

    async def emit(event_type, **data):
        pass

    task = asyncio.create_task(adapter.run("hello", emit, None))
    await wait_for(lambda: adapter.process is not None)
    process = adapter.process
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode is not None
    assert adapter.process is None


async def test_claude_reports_a_failed_turn(tmp_path):
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\nimport json, sys\nsys.stdin.read()\n"
        "print(json.dumps({'type': 'result', 'is_error': True, 'result': 'No conversation found.'}))\n"
    )
    script.chmod(0o755)
    adapter = ClaudeResumeAdapter(CLAUDE_ID, str(tmp_path))
    adapter.binary = str(script)

    async def emit(event_type, **data):
        pass

    with pytest.raises(RuntimeError, match="No conversation found."):
        await adapter.run("hello", emit, None)


async def test_hermes_call_back_uses_the_saved_session(tmp_path, monkeypatch):
    monkeypatch.setenv("TALKTOME_HERMES_API_KEY", "test-key")
    inputs = []

    def handler(request):
        path = request.url.path
        if path == "/v1/capabilities":
            return httpx.Response(200, json={"features": {"run_submission": True, "run_events_sse": True}})
        if path == "/api/sessions/h-1":
            return httpx.Response(200, json={"session": {"id": "h-1"}})
        if path == "/v1/runs":
            inputs.append(json.loads(request.content))
            return httpx.Response(202, json={"run_id": "r-1"})
        if path == "/v1/runs/r-1/events":
            body = "".join(
                f"data: {json.dumps(event)}\n\n"
                for event in (
                    {"event": "message.delta", "run_id": "r-1", "delta": "Hi."},
                    {"event": "run.completed", "run_id": "r-1", "output": "Hi."},
                )
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        external_adapters.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    store = history(tmp_path)
    entry = add(store, agent="hermes", session_id="h-1", cwd=str(tmp_path))
    managed, _ = managed_session(store)
    try:
        await call_back(managed, store, entry["id"])
        event = await managed.room.utterance(managed.room.call_id, "Hello")
        await managed.submit(event)
        await managed.task
        assert inputs == [{"input": f"{CALLBACK_PREFIX}\n\nHello", "session_id": "h-1"}]
        assert managed.status == "ready"
    finally:
        await managed.close()


async def test_call_back_refuses_generic(tmp_path):
    store = history(tmp_path)
    entry = add(store, agent="generic", session_id="x")
    managed, _ = managed_session(store)
    with pytest.raises(HTTPException) as refused:
        await call_back(managed, store, entry["id"])
    assert refused.value.status_code == 409


# ------------------------------------------------------------------ routes


@pytest.fixture
def client():
    app = create_app(token="test-token", speech=FakeSpeech())
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        client.store = app.state.managed.history
        yield client


def test_routes_need_the_token():
    app = create_app(token="test-token", speech=FakeSpeech())
    with TestClient(app) as anonymous:
        assert anonymous.get("/v1/calls").status_code == 401
        assert anonymous.delete("/v1/calls").status_code == 401


def test_list_delete_clear_and_settings(client):
    first = add(client.store)
    add(client.store, agent="generic", session_id="x")
    listed = client.get("/v1/calls").json()
    assert listed["transcripts"] == "off"
    assert [entry["agent"] for entry in listed["calls"]] == ["generic", "codex"]
    assert listed["calls"][0]["callback_reason"]
    assert listed["calls"][1]["callback_reason"] is None
    assert client.get(f"/v1/calls/{first['id']}/transcript").status_code == 404
    assert client.delete(f"/v1/calls/{first['id']}").json() == {"ok": True}
    assert client.delete(f"/v1/calls/{first['id']}").status_code == 404
    assert client.delete("/v1/calls").json() == {"ok": True}
    assert client.get("/v1/calls").json()["calls"] == []
    assert client.post("/v1/calls/settings", json={"transcripts": "30d"}).json() == {"transcripts": "30d"}
    assert client.post("/v1/calls/settings", json={"transcripts": "1y"}).status_code == 400


def test_a_ring_that_times_out_is_a_missed_call(client, tmp_path, monkeypatch):
    monkeypatch.setattr("talktome.managed.RING_TIMEOUT", 0.05)
    monkeypatch.setattr("talktome.managed.session_name", lambda thread: None)
    monkeypatch.setattr("talktome.managed.AttachedAdapter", fake_codex([]))
    response = client.post("/v1/attach/start", json={"thread": "t-1", "cwd": str(tmp_path), "name": "Billing"})
    assert response.status_code == 200
    deadline = time.monotonic() + 3
    while client.store.list()[0]["outcome"] is None and time.monotonic() < deadline:
        time.sleep(0.02)
    entry = client.get("/v1/calls").json()["calls"][0]
    assert entry["outcome"] == "missed"
    assert entry["name"] == "Billing"


def test_the_callback_route_reports_a_closed_codex_session(client, tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "rollout_path", lambda thread: None)
    entry = add(client.store, cwd=str(tmp_path))
    response = client.post(f"/v1/calls/{entry['id']}/callback")
    assert response.status_code == 409
    assert response.json()["detail"]["action"] == "open_terminal"
    assert client.get("/v1/calls").json()["calls"][0]["closed"] is True
