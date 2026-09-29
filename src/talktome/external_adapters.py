"""Connect TalkToMe to supported external agent hosts."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
from urllib.parse import quote, urlparse
from uuid import uuid4

import httpx
import websockets
from websockets.exceptions import WebSocketException

from .agents import find_command
from .config import data_dir

REQUEST_TIMEOUT = 30
RUN_TIMEOUT = 600
MAX_EVENT_BYTES = 1024 * 1024
EXTERNAL_CONFIG = "agent-hosts.json"


class AgentConfigurationError(ValueError):
    """The saved agent settings are invalid."""


def _local_url(value: str, name: str, schemes: set[str]) -> str:
    """Get a loopback URL unless the user enables a secure remote URL."""
    if not isinstance(value, str):
        raise AgentConfigurationError(f"Set {name} to a complete supported URL.")
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AgentConfigurationError("Use a host URL without credentials, query parameters, or a fragment.")
    if parsed.scheme not in schemes or not parsed.hostname:
        raise AgentConfigurationError(f"Set {name} to a complete supported URL.")
    local = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    remote = os.environ.get("TALKTOME_ALLOW_REMOTE_AGENTS") == "1"
    if not local and (not remote or parsed.scheme not in {"https", "wss"}):
        raise AgentConfigurationError(
            f"Set {name} to a loopback URL, or enable a secure remote agent URL."
        )
    return value.rstrip("/")


def _event_name(event: dict) -> str:
    return str(event.get("event") or event.get("type") or "")


def _path_part(value) -> str:
    return quote(str(value), safe="")


def _config_path():
    return data_dir() / EXTERNAL_CONFIG


def _external_settings():
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AgentConfigurationError(f"The external-agent configuration cannot be read. {exc}") from None
    if not isinstance(data, dict):
        raise AgentConfigurationError("The external-agent configuration must contain a JSON object.")
    return data


def _provider_settings(provider):
    settings = _external_settings().get(provider, {})
    if not isinstance(settings, dict):
        raise AgentConfigurationError(f"The {provider} configuration must contain a JSON object.")
    return settings


def _configured_value(provider, key, environment, default=None):
    value = os.environ.get(environment)
    if value is not None:
        return value
    value = _provider_settings(provider).get(key, default)
    if value is not None and not isinstance(value, str):
        raise AgentConfigurationError(f"The {provider} {key} setting must be text.")
    return value


def configure_external_provider(provider: str, url: str, token: str):
    """Save one external agent setting without returning its token."""
    if not isinstance(provider, str):
        raise AgentConfigurationError("Select Hermes or OpenClaw.")
    provider = provider.lower()
    schemes = {"hermes": {"http", "https"}, "openclaw": {"ws", "wss"}}
    if provider not in schemes:
        raise AgentConfigurationError("Select Hermes or OpenClaw.")
    if not isinstance(token, str) or not token.strip():
        raise AgentConfigurationError("Give a token for this external agent.")
    url = _local_url(url, "host URL", schemes[provider])
    settings = _external_settings()
    settings[provider] = {"url": url, "token": token}
    path = _config_path()
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(16)}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    return {"provider": provider, "configured_url": url}


async def _emit(emit, event_type, **data):
    if emit is not None:
        await emit(event_type, **data)


class HermesAdapter:
    """Drive one Hermes REST session through the documented Runs API."""

    agent_name = "Hermes Agent"

    def __init__(self, cwd, session_id=None):
        self.cwd = cwd
        self.session_id = session_id or None
        self.url = _local_url(
            _configured_value("hermes", "url", "TALKTOME_HERMES_URL", "http://127.0.0.1:8642"),
            "TALKTOME_HERMES_URL",
            {"http", "https"},
        )
        self.token = (
            os.environ.get("TALKTOME_HERMES_API_KEY")
            or os.environ.get("API_SERVER_KEY")
            or _configured_value("hermes", "token", "TALKTOME_HERMES_TOKEN")
        )
        self.client = None
        self.run_id = None
        self.capabilities = {
            "managed": True,
            "attach": True,
            "text_stream": True,
            "tool_status": True,
            "stop": False,
            "approval": False,
            "resume": True,
            "single_writer": True,
        }

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    async def start(self):
        if not self.token:
            raise AgentConfigurationError("Set TALKTOME_HERMES_API_KEY before you connect Hermes Agent.")
        self.client = httpx.AsyncClient(base_url=self.url, headers=self._headers())
        try:
            response = await self.client.get("/v1/capabilities", timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            await self.close()
            raise AgentConfigurationError(f"Hermes Agent did not supply capabilities. {exc}") from None
        self._set_capabilities(data)
        if not self.session_id:
            self.session_id = await self._create_session()
        else:
            await self._read_session()

    def _set_capabilities(self, data):
        features = data.get("features") if isinstance(data, dict) else {}
        features = features if isinstance(features, dict) else {}
        if not (features.get("run_submission") and features.get("run_events_sse")):
            raise AgentConfigurationError("This Hermes Agent version does not support the Runs event API.")
        self.capabilities["stop"] = bool(features.get("run_stop"))
        # `run_approval` is an endpoint entry. The feature flag has another name.
        self.capabilities["approval"] = bool(features.get("run_approval_response"))

    async def _create_session(self):
        assert self.client is not None
        try:
            response = await self.client.post("/api/sessions", json={}, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AgentConfigurationError(f"Hermes Agent could not create a session. {exc}") from None
        # Hermes returns {"object": "hermes.session", "session": {"id": ...}}.
        session = data.get("session") if isinstance(data.get("session"), dict) else data
        session_id = session.get("id") or session.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise AgentConfigurationError("Hermes Agent did not return a session ID.")
        return session_id

    async def _read_session(self):
        assert self.client is not None
        try:
            response = await self.client.get(
                f"/api/sessions/{_path_part(self.session_id)}", timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentConfigurationError(f"Hermes Agent could not open this session. {exc}") from None

    async def run(self, text, emit, approve):
        assert self.client is not None
        request_id = str(uuid4())
        try:
            response = await self.client.post(
                "/v1/runs",
                json={"input": text, "session_id": self.session_id},
                headers={"Idempotency-Key": request_id},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Hermes Agent did not start the turn. {exc}") from None
        run_id = result.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise RuntimeError("Hermes Agent did not return a run ID.")
        self.run_id = run_id
        try:
            await self._events(run_id, emit, approve)
        except asyncio.CancelledError:
            await self._stop(run_id)
            raise
        except Exception:
            await self._stop(run_id)
            raise
        finally:
            self.run_id = None

    async def _events(self, run_id, emit, approve):
        assert self.client is not None
        item_id = f"hermes:{run_id}"
        sent_text = False
        try:
            # Keepalives arrive every 10 seconds, so the read timeout never fires on
            # a run that waits for another process's turn. This caps the whole run.
            async with asyncio.timeout(RUN_TIMEOUT), self.client.stream(
                "GET", f"/v1/runs/{_path_part(run_id)}/events", timeout=RUN_TIMEOUT
            ) as response:
                response.raise_for_status()
                event = "message"
                data_lines = []
                async for line in response.aiter_lines():
                    if len(line.encode()) > MAX_EVENT_BYTES:
                        raise RuntimeError("Hermes Agent sent an event that is too large.")
                    if not line:
                        done, name = await self._sse_event(
                            event, data_lines, run_id, item_id, emit, approve, sent_text
                        )
                        if name in {"message.delta", "assistant.delta"}:
                            sent_text = True
                        event = "message"
                        data_lines = []
                        if done:
                            return
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event = line[6:].strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                        if sum(len(part.encode()) for part in data_lines) > MAX_EVENT_BYTES:
                            raise RuntimeError("Hermes Agent sent an event that is too large.")
                done, _ = await self._sse_event(
                    event, data_lines, run_id, item_id, emit, approve, sent_text
                )
                if done:
                    return
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Hermes Agent event stream stopped. {exc}") from None
        except TimeoutError:
            raise RuntimeError(
                f"Hermes Agent did not finish the turn in {RUN_TIMEOUT // 60} minutes."
            ) from None
        raise RuntimeError("Hermes Agent ended the event stream before the run finished.")

    async def _sse_event(self, event, data_lines, run_id, item_id, emit, approve, sent_text):
        """Handle one frame. Return whether the run ended, and the event name."""
        if not data_lines:
            return False, event
        try:
            data = json.loads("\n".join(data_lines))
        except ValueError:
            return False, event
        # Run streams write no `event:` line. The name is in the JSON body.
        if isinstance(data, dict) and isinstance(data.get("event"), str):
            event = data["event"]
        return await self._event(event, data, run_id, item_id, emit, approve, sent_text), event

    async def _event(self, event, data, run_id, item_id, emit, approve, sent_text):
        if not isinstance(data, dict):
            return False
        text = data.get("delta") or data.get("text")
        if event in {"message.delta", "assistant.delta"} and isinstance(text, str):
            await _emit(emit, "message.delta", item_id=item_id, text=text, kind="message")
        elif event in {"message.interim", "assistant.commentary"} and isinstance(text, str):
            if not data.get("already_streamed"):
                message_id = data.get("message_id") or uuid4()
                await _emit(
                    emit,
                    "message.done",
                    item_id=f"hermes:{run_id}:commentary:{message_id}",
                    text=text,
                    kind="commentary",
                )
        elif event in {"tool.started", "tool.completed", "tool.failed"}:
            name = data.get("tool") or "Tool"
            status = "active" if event == "tool.started" else "complete"
            await _emit(emit, "tool.status", text=str(name), status=status)
        elif event == "approval.request":
            if not self.capabilities["approval"]:
                raise RuntimeError(
                    "Hermes Agent requested an approval that this version cannot resolve."
                )
            allowed = await approve("approval", data)
            await self._approval(run_id, "once" if allowed else "deny", data.get("request_id"))
        elif event in {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}:
            if event == "run.completed":
                output = data.get("output")
                await _emit(
                    emit,
                    "message.done",
                    item_id=item_id,
                    text=output if isinstance(output, str) and not sent_text else None,
                    kind="message",
                )
                usage = data.get("usage")
                if isinstance(usage, dict):
                    await _emit(emit, "usage", usage=usage)
                return True
            detail = data.get("error") or data.get("message") or event
            raise RuntimeError(f"Hermes Agent ended the run: {detail}")
        return False

    async def _approval(self, run_id, choice, request_id=None):
        assert self.client is not None
        body = {"choice": choice}
        if isinstance(request_id, str) and request_id:
            body["request_id"] = request_id
        try:
            response = await self.client.post(
                f"/v1/runs/{_path_part(run_id)}/approval",
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Hermes Agent could not record the approval. {exc}") from None

    async def _stop(self, run_id):
        if not self.client or not self.capabilities.get("stop"):
            return
        with contextlib.suppress(httpx.HTTPError):
            await self.client.post(f"/v1/runs/{_path_part(run_id)}/stop", timeout=REQUEST_TIMEOUT)

    async def close(self):
        if self.run_id:
            await self._stop(self.run_id)
            self.run_id = None
        if self.client:
            await self.client.aclose()
            self.client = None


class OpenClawAdapter:
    """Join an OpenClaw Gateway session through its WebSocket protocol."""

    agent_name = "OpenClaw"

    def __init__(self, cwd, session_id=None):
        self.cwd = cwd
        self.session_id = session_id or None
        self.url = _local_url(
            _configured_value("openclaw", "url", "TALKTOME_OPENCLAW_URL", "ws://127.0.0.1:18789"),
            "TALKTOME_OPENCLAW_URL",
            {"ws", "wss"},
        )
        self.token = _configured_value("openclaw", "token", "TALKTOME_OPENCLAW_TOKEN")
        self.socket = None
        self.reader = None
        self.pending = {}
        self.events = asyncio.Queue(maxsize=2048)
        self.request_id = 0
        self.run_id = None
        self.item_id = None
        self.closing = False
        self.capabilities = {
            "managed": False,
            "attach": True,
            "text_stream": True,
            "tool_status": True,
            "stop": True,
            "approval": False,
            "resume": True,
            "single_writer": True,
        }

    async def start(self):
        if not self.session_id:
            raise AgentConfigurationError("Give an OpenClaw Gateway session key.")
        if not self.token:
            raise AgentConfigurationError("Set TALKTOME_OPENCLAW_TOKEN before you connect OpenClaw.")
        binary = await asyncio.to_thread(find_command, "openclaw")
        if not binary:
            raise AgentConfigurationError("Install OpenClaw before you connect an OpenClaw session.")
        try:
            self.socket = await websockets.connect(self.url, max_size=MAX_EVENT_BYTES)
            challenge = json.loads(await asyncio.wait_for(self.socket.recv(), REQUEST_TIMEOUT))
            if challenge.get("event") != "connect.challenge":
                raise AgentConfigurationError("OpenClaw Gateway did not send a connection challenge.")
            await self._write(
                {
                    "type": "req",
                    "id": "connect",
                    "method": "connect",
                    "params": {
                        "minProtocol": 4,
                        "maxProtocol": 4,
                        "client": {
                            "id": "gateway-client",
                            "version": "0.1.0",
                            "platform": "desktop",
                            "mode": "backend",
                        },
                        "role": "operator",
                        # exec.approval.resolve needs operator.approvals.
                        "scopes": ["operator.read", "operator.write", "operator.approvals"],
                        "caps": ["tool-events", "session-scoped-events"],
                        "commands": [],
                        "permissions": {},
                        "auth": {"token": self.token},
                        "locale": "en-US",
                        "userAgent": "talktome/0.1.0",
                    },
                }
            )
            hello = json.loads(await asyncio.wait_for(self.socket.recv(), REQUEST_TIMEOUT))
            if not hello.get("ok") or hello.get("payload", {}).get("type") != "hello-ok":
                raise AgentConfigurationError(
                    self._error_text(hello, "OpenClaw Gateway refused this connection.")
                )
            methods = hello.get("payload", {}).get("features", {}).get("methods", [])
            needed = {"chat.history", "chat.send", "sessions.abort", "sessions.messages.subscribe"}
            if not needed.issubset(set(methods)):
                raise AgentConfigurationError(
                    "This OpenClaw Gateway does not support the required session methods."
                )
            self.capabilities["approval"] = "exec.approval.resolve" in methods
            self.reader = asyncio.create_task(self._read())
            # The subscribe schema is a closed object with `key`, not `sessionKey`.
            await self.request("sessions.messages.subscribe", {"key": self.session_id})
            await self.request("chat.history", {"sessionKey": self.session_id, "limit": 1})
        except (TimeoutError, OSError, ValueError, RuntimeError, WebSocketException) as exc:
            await self.close()
            raise AgentConfigurationError(f"OpenClaw Gateway could not open this session. {exc}") from None

    async def _write(self, message):
        if not self.socket:
            raise RuntimeError("OpenClaw Gateway is not connected.")
        await self.socket.send(json.dumps(message))

    async def request(self, method, params):
        self.request_id += 1
        request_id = str(self.request_id)
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self._write({"type": "req", "id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, REQUEST_TIMEOUT)
        finally:
            self.pending.pop(request_id, None)

    async def _read(self):
        try:
            assert self.socket is not None
            async for line in self.socket:
                message = json.loads(line)
                if message.get("type") == "res":
                    future = self.pending.get(str(message.get("id")))
                    if future and not future.done():
                        if message.get("ok"):
                            future.set_result(message.get("payload") or {})
                        else:
                            future.set_exception(
                                RuntimeError(self._error_text(message, "OpenClaw request failed."))
                            )
                elif message.get("type") == "event":
                    # The subscription also carries every run the terminal user
                    # starts. Only the voice run is kept, so those cannot fill the
                    # queue between voice turns.
                    run_id = (message.get("payload") or {}).get("runId")
                    if _event_name(message) == "agent" and run_id and run_id == self.run_id:
                        if self.events.full():
                            raise RuntimeError("OpenClaw sent too many unread events. Reconnect the call.")
                        self.events.put_nowait(message)
        except (OSError, ValueError, RuntimeError, WebSocketException) as exc:
            while not self.events.empty():
                self.events.get_nowait()
            message = (
                "OpenClaw Gateway closed the connection."
                if isinstance(exc, WebSocketException)
                else str(exc)
            )
            self.events.put_nowait({"event": "host.error", "payload": {"message": message}})
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("OpenClaw Gateway stopped."))
            if not self.closing:
                if self.events.full():
                    self.events.get_nowait()
                self.events.put_nowait(
                    {"event": "host.error", "payload": {"message": "OpenClaw Gateway stopped."}}
                )

    @staticmethod
    def _error_text(message, fallback):
        error = message.get("error") or message.get("payload", {}).get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(error, str):
            return error
        return fallback

    async def run(self, text, emit, approve):
        # The Gateway can drop an idle socket between turns. Connect again
        # rather than fail the turn with the close reason.
        if not self._connected():
            await self.close()
            self.closing = False
            await self.start()
        while not self.events.empty():
            self.events.get_nowait()
        # The Gateway uses the idempotency key as the run ID. Set it before the
        # request, so events that arrive before the reply are kept.
        key = str(uuid4())
        self.run_id = key
        try:
            result = await self.request(
                "chat.send",
                {
                    "sessionKey": self.session_id,
                    "message": text,
                    "queueMode": "followup",
                    "idempotencyKey": key,
                },
            )
        except BaseException:
            self.run_id = None
            raise
        run_id = result.get("runId")
        if not isinstance(run_id, str) or not run_id:
            self.run_id = None
            raise RuntimeError("OpenClaw Gateway did not return a run ID.")
        self.run_id = run_id
        item_id = f"openclaw:{run_id}"
        self.item_id = item_id
        assistant_text = ""
        try:
            async with asyncio.timeout(RUN_TIMEOUT):
                while True:
                    event = await self.events.get()
                    if _event_name(event) == "host.error":
                        raise RuntimeError(event["payload"]["message"])
                    done, assistant_text = await self._handle_event(
                        event, run_id, self.item_id, emit, assistant_text, approve
                    )
                    if done:
                        return
        except asyncio.CancelledError:
            await self._stop(run_id)
            raise
        except Exception:
            await self._stop(run_id)
            raise
        finally:
            self.run_id = None

    async def _handle_event(self, event, run_id, item_id, emit, assistant_text, approve=None):
        if _event_name(event) != "agent":
            return False, assistant_text
        payload = event.get("payload") or {}
        if payload.get("runId") != run_id:
            return False, assistant_text
        stream = payload.get("stream")
        data = payload.get("data") or {}
        if stream == "assistant":
            text = data.get("delta") or data.get("deltaText")
            if data.get("replace"):
                # The event carries the whole new text. Speak only what is new.
                replacement = data.get("text") if isinstance(data.get("text"), str) else text
                replacement = replacement if isinstance(replacement, str) else ""
                if replacement.startswith(assistant_text):
                    text = replacement[len(assistant_text) :]
                else:
                    # Words already spoken cannot be taken back. Start a new item
                    # so the transcript shows the correction.
                    await _emit(emit, "message.done", item_id=item_id, text=None, kind="message")
                    self.item_id = item_id = f"{item_id}:{uuid4().hex[:8]}"
                    text = replacement
                if text:
                    await _emit(emit, "message.delta", item_id=item_id, text=text, kind="message")
                return False, replacement
            from_delta = isinstance(text, str)
            if not isinstance(text, str):
                snapshot = data.get("text")
                if isinstance(snapshot, str) and snapshot.startswith(assistant_text):
                    text = snapshot[len(assistant_text) :]
                    assistant_text = snapshot
            if isinstance(text, str) and text:
                if from_delta:
                    assistant_text += text
                await _emit(emit, "message.delta", item_id=item_id, text=text, kind="message")
        elif stream == "tool":
            name = data.get("name") or data.get("tool") or "Tool"
            phase = data.get("phase") or data.get("status")
            status = "complete" if phase in {"end", "result", "complete", "completed"} else "active"
            await _emit(emit, "tool.status", text=str(name), status=status)
        elif stream == "usage" and isinstance(data, dict):
            await _emit(emit, "usage", usage=data)
        elif stream == "approval" and data.get("phase") == "requested" and data.get("kind") == "exec":
            await self._exec_approval(data, emit, approve)
        elif stream == "lifecycle":
            phase = data.get("phase")
            if phase == "end":
                await _emit(emit, "message.done", item_id=item_id, text=None, kind="message")
                return True, assistant_text
            if phase == "error":
                raise RuntimeError(str(data.get("error") or "OpenClaw run failed."))
        return False, assistant_text

    async def _exec_approval(self, data, emit, approve):
        approval_id = data.get("approvalId")
        if data.get("status") != "pending" or not isinstance(approval_id, str):
            return
        if not self.capabilities["approval"] or approve is None:
            # The run waits for a decision somewhere else. Say where.
            await _emit(emit, "tool.status", text="Waiting for approval in OpenClaw", status="active")
            return
        details = {key: data[key] for key in ("command", "host", "title") if data.get(key)}
        allowed = await approve(data.get("title") or "Run a command", details)
        try:
            await self.request(
                "exec.approval.resolve",
                {"id": approval_id, "decision": "allow-once" if allowed else "deny"},
            )
        except (RuntimeError, TimeoutError) as exc:
            raise RuntimeError(f"OpenClaw could not record the approval. {exc}") from None

    def _connected(self):
        return bool(self.socket and self.reader and not self.reader.done())

    async def _stop(self, run_id):
        if not self._connected():
            return
        with contextlib.suppress(RuntimeError, TimeoutError, OSError, WebSocketException):
            await self.request("sessions.abort", {"key": self.session_id, "runId": run_id})

    async def close(self):
        self.closing = True
        if self.run_id:
            await self._stop(self.run_id)
            self.run_id = None
        if self._connected():
            with contextlib.suppress(RuntimeError, TimeoutError, OSError, WebSocketException):
                await self.request("sessions.messages.unsubscribe", {"key": self.session_id})
        if self.socket:
            with contextlib.suppress(OSError, WebSocketException):
                await self.socket.close()
            self.socket = None
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader
            self.reader = None


EXTERNAL_ADAPTERS = {"hermes": HermesAdapter, "openclaw": OpenClawAdapter}


def external_provider_status(provider: str) -> dict:
    """Show whether this computer has the required local configuration."""
    if not isinstance(provider, str):
        raise AgentConfigurationError("Select Hermes or OpenClaw.")
    provider = provider.lower()
    if provider == "hermes":
        url = _configured_value("hermes", "url", "TALKTOME_HERMES_URL", "http://127.0.0.1:8642")
        token = (
            os.environ.get("TALKTOME_HERMES_API_KEY")
            or os.environ.get("API_SERVER_KEY")
            or _configured_value("hermes", "token", "TALKTOME_HERMES_TOKEN")
        )
        return {
            "available": bool(token),
            "configured_url": url,
            "requires": "A Hermes API token",
        }
    if provider == "openclaw":
        url = _configured_value(
            "openclaw", "url", "TALKTOME_OPENCLAW_URL", "ws://127.0.0.1:18789"
        )
        token = _configured_value("openclaw", "token", "TALKTOME_OPENCLAW_TOKEN")
        return {
            "available": bool(find_command("openclaw") and token),
            "configured_url": url,
            "requires": "OpenClaw and a Gateway token",
        }
    return {
        "available": False,
        "configured_url": None,
        "requires": "A supported external provider",
    }


def create_external_adapter(provider: str, session_id: str | None, cwd: str):
    """Create an external host adapter without starting a host process."""
    adapter = EXTERNAL_ADAPTERS.get(provider.lower())
    if not adapter:
        raise AgentConfigurationError("Select Hermes or OpenClaw.")
    return adapter(cwd, session_id)
