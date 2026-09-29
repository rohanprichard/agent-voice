"""The external adapters against fakes built from the hosts' own source.

Hermes: gateway/platforms/api_server.py and api_server_runs.py. Run streams write
no `event:` line, and the approval body takes `choice`.
OpenClaw: packages/gateway-protocol/src/schema/sessions.ts and
docs/gateway/protocol/rpc-bootstrap-and-events.md. The subscribe schema is a
closed object with `key`, and the subscription carries every run in the session.
"""

import asyncio
import json

import httpx
import pytest
import websockets

from talktome import external_adapters
from talktome.external_adapters import HermesAdapter, OpenClawAdapter


def recorder():
    emitted = []

    async def emit(event, **data):
        emitted.append((event, data))

    return emitted, emit


def sse(*events):
    return "".join(
        f"id: {seq}\ndata: {json.dumps({**event, 'seq': seq})}\n\n"
        for seq, event in enumerate(events, 1)
    )


@pytest.mark.asyncio
async def test_hermes_speaks_a_run_and_answers_its_approval(monkeypatch):
    monkeypatch.setenv("TALKTOME_HERMES_API_KEY", "test-key")
    approvals = []

    def handler(request):
        path = request.url.path
        if path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "features": {
                        "run_submission": True,
                        "run_events_sse": True,
                        "run_stop": True,
                        "run_approval_response": True,
                    },
                    "endpoints": {"run_approval": ["POST", "/v1/runs/{run_id}/approval"]},
                },
            )
        if path == "/api/sessions/h-1":
            return httpx.Response(200, json={"object": "hermes.session", "session": {"id": "h-1"}})
        if path == "/v1/runs":
            assert json.loads(request.content) == {"input": "list files", "session_id": "h-1"}
            return httpx.Response(202, json={"run_id": "r-1"})
        if path == "/v1/runs/r-1/events":
            body = sse(
                {"event": "message.delta", "run_id": "r-1", "delta": "Let me look. "},
                {"event": "tool.started", "run_id": "r-1", "tool": "terminal"},
                {"event": "approval.request", "run_id": "r-1", "request_id": "q-1"},
                {"event": "tool.completed", "run_id": "r-1", "tool": "terminal"},
                {"event": "message.delta", "run_id": "r-1", "delta": "Two files."},
                {"event": "run.completed", "run_id": "r-1", "output": "Let me look. Two files."},
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if path == "/v1/runs/r-1/approval":
            approvals.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        external_adapters.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    adapter = HermesAdapter("/tmp", session_id="h-1")
    await adapter.start()
    emitted, emit = recorder()

    async def approve(action, details):
        return True

    try:
        await adapter.run("list files", emit, approve)
    finally:
        await adapter.close()

    assert approvals == [{"choice": "once", "request_id": "q-1"}]
    spoken = "".join(data["text"] for event, data in emitted if event == "message.delta")
    assert spoken == "Let me look. Two files."
    # The final output repeats the deltas, so it must not be spoken again.
    assert ("message.done", {"item_id": "hermes:r-1", "text": None, "kind": "message"}) in emitted
    assert [data["status"] for event, data in emitted if event == "tool.status"] == [
        "active",
        "complete",
    ]


@pytest.mark.asyncio
async def test_hermes_creates_a_session_from_the_nested_reply(monkeypatch):
    monkeypatch.setenv("TALKTOME_HERMES_API_KEY", "test-key")

    def handler(request):
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200, json={"features": {"run_submission": True, "run_events_sse": True}}
            )
        if request.url.path == "/api/sessions":
            return httpx.Response(201, json={"object": "hermes.session", "session": {"id": "new"}})
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        external_adapters.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    adapter = HermesAdapter("/tmp")
    await adapter.start()
    await adapter.close()
    assert adapter.session_id == "new"


def openclaw_gateway(sent):
    async def handler(socket):
        await socket.send(json.dumps({"type": "event", "event": "connect.challenge"}))
        connect = json.loads(await socket.recv())
        assert connect["params"]["auth"] == {"token": "test-token"}
        await socket.send(
            json.dumps(
                {
                    "type": "res",
                    "id": "connect",
                    "ok": True,
                    "payload": {
                        "type": "hello-ok",
                        "features": {
                            "methods": [
                                "chat.history",
                                "chat.send",
                                "sessions.abort",
                                "sessions.messages.subscribe",
                                "sessions.messages.unsubscribe",
                            ]
                        },
                    },
                }
            )
        )

        async def reply(message, ok=True, payload=None, error=None):
            await socket.send(
                json.dumps(
                    {"type": "res", "id": message["id"], "ok": ok, "payload": payload or {}}
                    | ({"error": {"message": error}} if error else {})
                )
            )

        async def agent(run_id, stream, data):
            await socket.send(
                json.dumps(
                    {
                        "type": "event",
                        "event": "agent",
                        "payload": {"runId": run_id, "stream": stream, "data": data},
                    }
                )
            )

        async for line in socket:
            message = json.loads(line)
            method, params = message["method"], message["params"]
            sent.append((method, params))
            if method.startswith("sessions.messages."):
                if set(params) != {"key"}:
                    await reply(message, ok=False, error="invalid params")
                else:
                    await reply(message)
            elif method == "chat.send":
                run_id = params["idempotencyKey"]
                # A run the terminal user started. It must not reach the call.
                await agent("terminal-run", "assistant", {"delta": "not for the call"})
                await agent(run_id, "assistant", {"delta": "On it. "})
                await reply(message, payload={"runId": run_id})
                await agent(run_id, "tool", {"name": "exec", "phase": "start"})
                await agent(run_id, "tool", {"name": "exec", "phase": "result"})
                await agent(run_id, "assistant", {"replace": True, "text": "On it. Done."})
                await agent(run_id, "lifecycle", {"phase": "end"})
            else:
                await reply(message)

    return handler


@pytest.mark.asyncio
async def test_openclaw_joins_a_session_and_speaks_only_its_own_run(monkeypatch):
    sent = []
    async with websockets.serve(openclaw_gateway(sent), "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("TALKTOME_OPENCLAW_URL", f"ws://127.0.0.1:{port}")
        monkeypatch.setenv("TALKTOME_OPENCLAW_TOKEN", "test-token")
        monkeypatch.setattr(external_adapters, "find_command", lambda name: "/bin/openclaw")
        adapter = OpenClawAdapter("/tmp", session_id="agent:main:main")
        await adapter.start()
        emitted, emit = recorder()
        try:
            await asyncio.wait_for(adapter.run("list files", emit, None), 10)
        finally:
            await adapter.close()

    assert ("sessions.messages.subscribe", {"key": "agent:main:main"}) in sent
    assert ("sessions.messages.unsubscribe", {"key": "agent:main:main"}) in sent
    spoken = "".join(data["text"] for event, data in emitted if event == "message.delta")
    # The replacement repeats the spoken prefix, so only the new words are added.
    assert spoken == "On it. Done."
    assert [data["status"] for event, data in emitted if event == "tool.status"] == [
        "active",
        "complete",
    ]
    assert emitted[-1][0] == "message.done"


@pytest.mark.asyncio
async def test_openclaw_close_after_the_gateway_drops_does_not_raise(monkeypatch):
    async def handler(socket):
        await openclaw_gateway([])(socket)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("TALKTOME_OPENCLAW_URL", f"ws://127.0.0.1:{port}")
        monkeypatch.setenv("TALKTOME_OPENCLAW_TOKEN", "test-token")
        monkeypatch.setattr(external_adapters, "find_command", lambda name: "/bin/openclaw")
        adapter = OpenClawAdapter("/tmp", session_id="agent:main:main")
        await adapter.start()
        server.close()
        await server.wait_closed()
        await asyncio.wait_for(adapter.reader, 5)
        adapter.run_id = "r-1"
        await adapter.close()
    assert adapter.socket is None


def approval_gateway(sent, drops=None):
    """A Gateway whose run asks for an exec approval, from permission-relay.ts."""
    async def handler(socket):
        if drops is not None and not drops:
            # The first connection is dropped while idle, after the handshake.
            drops.append(True)
            await socket.send(json.dumps({"type": "event", "event": "connect.challenge"}))
            await socket.recv()
            await socket.send(
                json.dumps(
                    {
                        "type": "res",
                        "id": "connect",
                        "ok": True,
                        "payload": {
                            "type": "hello-ok",
                            "features": {
                                "methods": [
                                    "chat.history",
                                    "chat.send",
                                    "sessions.abort",
                                    "sessions.messages.subscribe",
                                ]
                            },
                        },
                    }
                )
            )
            for _ in range(2):
                message = json.loads(await socket.recv())
                await socket.send(json.dumps({"type": "res", "id": message["id"], "ok": True}))
            await socket.close()
            return
        await socket.send(json.dumps({"type": "event", "event": "connect.challenge"}))
        connect = json.loads(await socket.recv())
        sent.append(("connect", connect["params"]["scopes"]))
        await socket.send(
            json.dumps(
                {
                    "type": "res",
                    "id": "connect",
                    "ok": True,
                    "payload": {
                        "type": "hello-ok",
                        "features": {
                            "methods": [
                                "chat.history",
                                "chat.send",
                                "sessions.abort",
                                "sessions.messages.subscribe",
                                "exec.approval.resolve",
                            ]
                        },
                    },
                }
            )
        )
        run_id = None

        async def agent(stream, data):
            await socket.send(
                json.dumps(
                    {
                        "type": "event",
                        "event": "agent",
                        "payload": {"runId": run_id, "stream": stream, "data": data},
                    }
                )
            )

        async for line in socket:
            message = json.loads(line)
            method, params = message["method"], message["params"]
            sent.append((method, params))
            await socket.send(
                json.dumps(
                    {
                        "type": "res",
                        "id": message["id"],
                        "ok": True,
                        "payload": {"runId": params["idempotencyKey"]}
                        if method == "chat.send"
                        else {},
                    }
                )
            )
            if method == "chat.send":
                run_id = params["idempotencyKey"]
                await agent(
                    "approval",
                    {
                        "phase": "requested",
                        "kind": "exec",
                        "status": "pending",
                        "approvalId": "approval-1",
                        "command": "rm -rf build",
                        "title": "Run rm -rf build",
                    },
                )
            elif method == "exec.approval.resolve":
                await agent("assistant", {"delta": "Done."})
                await agent("lifecycle", {"phase": "end"})

    return handler


@pytest.mark.parametrize(("allowed", "decision"), [(True, "allow-once"), (False, "deny")])
@pytest.mark.asyncio
async def test_openclaw_exec_approval_reaches_the_user(monkeypatch, allowed, decision):
    sent = []
    async with websockets.serve(approval_gateway(sent), "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("TALKTOME_OPENCLAW_URL", f"ws://127.0.0.1:{port}")
        monkeypatch.setenv("TALKTOME_OPENCLAW_TOKEN", "test-token")
        monkeypatch.setattr(external_adapters, "find_command", lambda name: "/bin/openclaw")
        adapter = OpenClawAdapter("/tmp", session_id="agent:main:main")
        await adapter.start()
        asked = []

        async def approve(action, details):
            asked.append((action, details))
            return allowed

        _, emit = recorder()
        try:
            await asyncio.wait_for(adapter.run("clean up", emit, approve), 10)
        finally:
            await adapter.close()

    assert asked == [("Run rm -rf build", {"command": "rm -rf build", "title": "Run rm -rf build"})]
    assert ("exec.approval.resolve", {"id": "approval-1", "decision": decision}) in sent
    assert "operator.approvals" in dict(sent)["connect"]


@pytest.mark.asyncio
async def test_openclaw_connects_again_after_an_idle_drop(monkeypatch):
    sent, drops = [], []
    async with websockets.serve(approval_gateway(sent, drops), "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("TALKTOME_OPENCLAW_URL", f"ws://127.0.0.1:{port}")
        monkeypatch.setenv("TALKTOME_OPENCLAW_TOKEN", "test-token")
        monkeypatch.setattr(external_adapters, "find_command", lambda name: "/bin/openclaw")
        adapter = OpenClawAdapter("/tmp", session_id="agent:main:main")
        await adapter.start()
        # The Gateway closes the first socket while no turn runs.
        await asyncio.wait_for(adapter.reader, 5)

        async def approve(action, details):
            return True

        emitted, emit = recorder()
        try:
            await asyncio.wait_for(adapter.run("hello", emit, approve), 10)
        finally:
            await adapter.close()
    assert drops == [True]
    assert "".join(data["text"] for event, data in emitted if event == "message.delta") == "Done."
