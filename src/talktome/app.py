import asyncio
import hmac
import json
import logging
import math
import secrets
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, agents, inbox
from .calls import CallHistory, call_routes
from .config import data_dir, get_token
from .cooperative import CooperativeAdapter
from .external_adapters import configure_external_provider, external_provider_status
from .managed import ManagedSession
from .room import Room
from .smart_turn import MAX_AUDIO_BYTES, SmartTurn, SmartTurnUnavailable
from .speech import MODELS, Speech
from .timing import TimingHistory

logger = logging.getLogger(__name__)

# A stream ends after this long and the browser opens it again from the last
# event id. A stream that never ended would hold the server open at shutdown.
STREAM_SECONDS = 25


class AuthBody(BaseModel):
    token: str


class CallBody(BaseModel):
    call_id: str


class TimingBody(CallBody):
    turn_id: str
    first_audio_ms: float | None = Field(default=None, allow_inf_nan=False)
    commit_sent_ms: float | None = Field(default=None, allow_inf_nan=False)
    committed_ms: float | None = Field(default=None, allow_inf_nan=False)
    first_audio_scheduled_ms: float | None = Field(default=None, allow_inf_nan=False)


class PlaybackReceipt(BaseModel):
    audio_id: str = Field(max_length=100)
    played_ms: float = Field(ge=0, le=3_600_000, allow_inf_nan=False)
    completed: bool = False


class InterruptBody(CallBody):
    playback_epoch: int | None = Field(default=None, ge=0)
    playback: list[PlaybackReceipt] = Field(default_factory=list, max_length=128)


class TextBody(InterruptBody):
    text: str = Field(min_length=1, max_length=6000)
    speech_end_ms: float | None = None
    capture_end_ms: float | None = None
    transcribed_ms: float | None = None
    commit_sent_ms: float | None = None
    committed_ms: float | None = None
    turn_reason: str | None = Field(default=None, pattern="^(smart_turn|pause|silence_limit|duration_limit)$")
    turn_probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    turn_check_ms: float | None = Field(default=None, ge=0, le=60_000, allow_inf_nan=False)


class VoiceBody(BaseModel):
    voice: str = Field(max_length=100)


class AttachBody(BaseModel):
    thread: str = Field(min_length=1, max_length=512)
    cwd: str = Field(min_length=1, max_length=4096)
    greeting: str | None = Field(default=None, max_length=2000)
    name: str | None = Field(default=None, max_length=120)
    agent: str = "codex"
    connection: str = "auto"


class RingBody(BaseModel):
    ring_id: str | None = Field(default=None, max_length=80)


class ApprovalBody(BaseModel):
    allow: bool


class SpeakBody(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    voice: str = "default"


class ProviderBody(BaseModel):
    stt_provider: str = "whisper"
    tts_provider: str


class ElevenLabsBody(BaseModel):
    api_key: str = Field(min_length=1, max_length=512, repr=False)
    remember: bool = False


class TurnDetectionBody(BaseModel):
    enabled: bool


def create_app(*, token=None, speech=None):
    secret = token or get_token()
    browser_secret = secrets.token_urlsafe(32)
    timing_history = TimingHistory(data_dir() / "timings.json")
    room = Room(timing_history)
    engine = speech or Speech(data_dir())
    audio_cache = OrderedDict()
    tasks = set()
    voice = engine.saved_voice()
    synthesis_lock = asyncio.Lock()
    transcription_lock = asyncio.Lock()
    setup_task = None
    voice_setup_task = None
    settings_lock = asyncio.Lock()
    turn_detector = SmartTurn(data_dir())
    turn_setup_task = None
    turn_lock = asyncio.Lock()
    smart_turn_enabled = engine.settings().get("smart_turn_enabled", True)

    def finished(task):
        tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("A background task stopped.", exc_info=task.exception())

    def background(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.add(task)
        task.add_done_callback(finished)
        return task

    def speech_status():
        return {
            **engine.status(),
            "smart_turn": {**turn_detector.status(), "enabled": smart_turn_enabled},
        }

    async def load_turn_detector():
        await asyncio.to_thread(turn_detector.setup)
        await room.emit("turn_detector.updated")

    @asynccontextmanager
    async def lifespan(app):
        nonlocal setup_task, voice_setup_task, turn_setup_task
        await timing_history.load()
        if smart_turn_enabled:
            turn_setup_task = background(load_turn_detector())
        voice_setup_task = background(asyncio.to_thread(engine.restore_providers))
        saved = engine.saved_model()
        if saved and saved in {m["id"] for m in MODELS}:
            setup_task = background(asyncio.to_thread(engine.setup, saved))
        background(watch_inbox())
        background(history.prune_daily())
        yield
        await managed.close()
        await timing_history.flush()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(
        title="TalkToMe",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.room = room
    app.state.engine = engine

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path == "/v1/speech/elevenlabs":
            return JSONResponse(
                {"detail": "Enter a valid API key and Remember key value."}, status_code=422
            )
        return await request_validation_exception_handler(request, exc)

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def protect(request: Request, call_next):
        path = request.url.path
        origin = request.headers.get("origin")
        expected = str(request.base_url).rstrip("/")
        if origin and origin != expected:
            return JSONResponse({"detail": "This origin is not permitted."}, status_code=403)
        if path.startswith("/v1/") and path not in {"/v1/health", "/v1/auth"}:
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
            cookie = request.cookies.get("talktome_session", "")
            if not (
                hmac.compare_digest(bearer.encode(), secret.encode())
                or hmac.compare_digest(cookie.encode(), browser_secret.encode())
            ):
                return JSONResponse({"detail": "Connect with the local token."}, status_code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; media-src 'self' blob:; "
            "connect-src 'self' wss://api.elevenlabs.io; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.get("/v1/health")
    async def health():
        return {"service": "talktome", "version": __version__, "status": engine.state["status"]}

    @app.post("/v1/auth")
    async def auth(body: AuthBody):
        if not hmac.compare_digest(body.token.encode(), secret.encode()):
            raise HTTPException(401, "The local token is incorrect.")
        response = JSONResponse({"ok": True})
        response.set_cookie("talktome_session", browser_secret, httponly=True, samesite="strict")
        return response

    @app.get("/v1/state")
    async def state():
        return {
            "room": room.snapshot(),
            "speech": speech_status(),
            "voice": voice,
            "managed": managed.snapshot(),
        }

    def sse(kind, data, event_id=None):
        head = f"id: {event_id}\n" if event_id is not None else ""
        return f"{head}event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"

    @app.get("/v1/stream")
    async def stream(request: Request):
        """One snapshot, then only what changed.

        A reply delta carries its own text, so a streamed reply costs a few
        hundred bytes an event instead of the whole room. A client that fell
        behind the event buffer gets a new snapshot.
        """
        try:
            resume = int(request.headers.get("last-event-id", ""))
        except ValueError:
            resume = None

        async def events():
            nonlocal resume
            loop = asyncio.get_running_loop()
            deadline = loop.time() + STREAM_SECONDS
            after = resume if resume is not None and 0 <= resume <= room.sequence else None
            spoken = None
            yield "retry: 500\n\n"
            while loop.time() < deadline:
                if after is None:
                    after = room.sequence
                    state = {
                        "room": room.snapshot(), "speech": speech_status(),
                        "managed": managed.snapshot(), "voice": voice,
                    }
                    spoken = json.dumps(state["speech"])
                    yield sse("snapshot", state, after)
                    continue
                batch, gap = await room.wait(after, min(1, deadline - loop.time()))
                if gap:
                    after = None
                    continue
                for event in batch:
                    after = event["seq"]
                    data = {"event": {k: v for k, v in event.items() if k != "agent_text"}}
                    # A delta changes one message and nothing else.
                    if event["type"] != "message.delta":
                        data["room"] = room.snapshot(messages=False)
                        data["managed"] = managed.snapshot()
                    yield sse("event", data, after)
                speech = speech_status()
                if json.dumps(speech) != spoken:
                    spoken = json.dumps(speech)
                    yield sse("speech", speech, after)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/v1/events")
    async def events(after: int = Query(0, ge=0), timeout: float = Query(25, ge=0, le=25)):
        result = await room.poll(after, timeout)
        result["speech"] = speech_status()
        result["managed"] = managed.snapshot()
        return result

    def timing_mode():
        if not managed.options:
            return "direct"
        return managed.options.get("provider", "direct")

    @app.get("/v1/skill")
    async def skill():
        # skill_status can start a login shell to find the command.
        return await asyncio.to_thread(agents.skill_status, Path.home())

    @app.post("/v1/skill/install")
    async def install_skill():
        try:
            return await asyncio.to_thread(agents.install_skill_and_command, Path.home())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/v1/models")
    async def models():
        return {"models": MODELS, "speech": engine.status()}

    @app.post("/v1/models/{model_id}/download")
    async def download(model_id: str):
        nonlocal setup_task
        require_idle()
        if model_id not in {m["id"] for m in MODELS}:
            raise HTTPException(404, "This model is not in the catalog.")
        if setup_task and not setup_task.done():
            raise HTTPException(409, "Wait for the current model to load.")
        if transcription_lock.locked():
            raise HTTPException(409, "Wait for the current transcription to end.")
        setup_task = background(asyncio.to_thread(engine.setup, model_id))
        return {"status": "started"}

    @app.get("/v1/tts/voices")
    async def voices():
        try:
            return {
                "voices": await asyncio.to_thread(engine.voices),
                "selected": voice,
                "withheld": await asyncio.to_thread(engine.withheld_voices),
            }
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def require_idle():
        if room.call_id or synthesis_lock.locked() or transcription_lock.locked():
            raise HTTPException(409, "End the conversation before you change speech settings.")

    @app.post("/v1/speech/providers")
    async def providers(body: ProviderBody):
        nonlocal voice
        async with settings_lock:
            require_idle()
            if body.stt_provider not in {"whisper", "elevenlabs"} or body.tts_provider not in {
                "system",
                "kokoro",
                "elevenlabs",
            }:
                raise HTTPException(400, "Select a speech provider from the list.")
            settings = engine.settings()
            previous = engine.provider()
            voice = (
                settings.get("voice", "default")
                if previous == body.tts_provider
                else settings.get(f"voice_{body.tts_provider}", "default")
            )
            await asyncio.to_thread(
                engine.save_settings,
                stt_provider=body.stt_provider,
                tts_provider=body.tts_provider,
                voice=voice,
                **{f"voice_{previous}": settings.get("voice", "default")},
            )
            return engine.status()

    @app.post("/v1/tts/kokoro/download")
    async def download_kokoro():
        nonlocal voice_setup_task
        require_idle()
        if voice_setup_task and not voice_setup_task.done():
            raise HTTPException(409, "Wait for the voice model to load.")
        voice_setup_task = background(asyncio.to_thread(engine.kokoro.setup))
        return {"status": "started"}

    @app.post("/v1/speech/elevenlabs")
    async def configure_elevenlabs(body: ElevenLabsBody):
        async with settings_lock:
            require_idle()
            if not body.api_key.strip() or not body.api_key.strip().isascii():
                raise HTTPException(400, "Enter a valid ElevenLabs API key.")
            try:
                saved = await asyncio.to_thread(
                    engine.elevenlabs.configure, body.api_key.strip(), body.remember
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            # Only record that the key is remembered when it actually is. A keychain
            # that refuses leaves the session working and the setting honest.
            await asyncio.to_thread(
                engine.save_settings, remember_elevenlabs=bool(saved["remembered"])
            )
            return {**engine.status(), **saved}

    @app.delete("/v1/speech/elevenlabs")
    async def forget_elevenlabs():
        async with settings_lock:
            require_idle()
            try:
                await asyncio.to_thread(engine.elevenlabs.forget)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            await asyncio.to_thread(engine.save_settings, remember_elevenlabs=False)
            return engine.status()

    @app.post("/v1/tts/voice")
    async def set_voice(body: VoiceBody):
        nonlocal voice
        async with settings_lock:
            require_idle()
            try:
                installed = await asyncio.to_thread(engine.voices)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if not installed or (
                body.voice != "default" and body.voice not in {v["id"] for v in installed}
            ):
                raise HTTPException(400, "Select an installed voice.")
            voice = body.voice
            await asyncio.to_thread(engine.save_settings, voice=voice)
            return {"voice": voice}

    async def synthesize(text, selected_voice):
        async with synthesis_lock:
            try:
                return await asyncio.to_thread(engine.synthesize, text, selected_voice)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            except Exception as exc:
                raise HTTPException(
                    503, "The voice engine failed. Examine the server log."
                ) from exc

    def cache_audio(audio):
        audio_id = str(uuid4())
        audio_cache[audio_id] = audio
        while len(audio_cache) > 128:
            audio_cache.popitem(last=False)
        return audio_id

    async def managed_speech(text):
        return await synthesize(text, voice)

    async def managed_stream(on_audio):
        """Stream the reply as it is written, when the provider can."""
        opener = getattr(engine, "open_stream", None)
        if opener is None:
            return None
        return await asyncio.to_thread(opener, voice, on_audio)

    async def warm_stream():
        return await managed_stream(None)

    def speech_problem():
        # A model or a remembered key still loading after the app woke up is
        # not a missing setup. The user answers after it is ready.
        if any(task is not None and not task.done() for task in (setup_task, voice_setup_task)):
            return None
        status = engine.status()
        loading = {"downloading", "loading"}
        hearing = status.get("status") == "ready" or status.get("status") in loading
        speaking = status.get("tts_available") or (
            status.get("tts_provider") == "kokoro"
            and (status.get("kokoro") or {}).get("status") in loading
        )
        if hearing and speaking:
            return None
        return "TalkToMe speech is not set up. Ask the user to finish setup in TalkToMe."

    managed = ManagedSession(
        room, managed_speech, cache_audio, managed_stream,
        warm_stream=warm_stream if isinstance(engine, Speech) else None,
        speech_problem=speech_problem,
    )
    app.state.managed = managed
    history = CallHistory(data_dir() / "calls")
    managed.history = history
    app.include_router(call_routes(managed, history))

    def provider_report():
        return {
            "codex": {"connection": "terminal", "available": bool(agents.find_command("codex"))},
            "claude": {"connection": "cooperative", "available": True},
            "generic": {"connection": "cooperative", "available": True},
            "hermes": {"connection": "api-session", "experimental": True, **external_provider_status("hermes")},
            "openclaw": {"connection": "gateway", "experimental": True, **external_provider_status("openclaw")},
        }

    async def serve_request(command, payload):
        """Do what a note in the inbox asks for.

        This is the same work the HTTP routes below do, reached without a
        connection. The two cannot drift far: both call the same session.
        """
        if command == "call":
            thread = str(payload.get("thread") or "").strip()
            if not thread:
                raise HTTPException(400, "A call joins an existing session, so it needs one.")
            result = await managed.attach(
                thread,
                str(payload.get("cwd") or Path.cwd()),
                payload.get("greeting"),
                payload.get("name"),
                payload.get("agent", "codex"),
                payload.get("connection", "auto"),
            )
            ring = result.get("ring") or {}
            if payload.get("wait", True) and ring.get("id"):
                result["answered"] = await managed.answered(ring["id"])
            return result
        if command == "end":
            return await managed.hangup()
        if command == "cooperative-end":
            adapter = managed.adapter
            if adapter is None:
                return {"status": "idle"}
            if not isinstance(adapter, CooperativeAdapter) or payload.get("thread") != adapter.session_id:
                raise HTTPException(409, "This connection does not own the call.")
            # Retain the adapter identity across the asynchronous call cleanup.
            await managed.hangup(expected_adapter=adapter)
            return {"status": "ended"}
        if command == "providers":
            # Finding a command can start a login shell, so it runs off the loop.
            return await asyncio.to_thread(provider_report)
        if command == "configure-agent":
            if room.call_id or managed.ring:
                raise HTTPException(409, "End the call before you change the agent connection.")
            return configure_external_provider(
                payload.get("agent"), payload.get("url"), payload.get("token"),
            )
        if command in {"listen", "reply"}:
            adapter = managed.adapter
            if not isinstance(adapter, CooperativeAdapter):
                raise HTTPException(409, "This call does not use cooperative voice commands.")
            if payload.get("thread") != adapter.session_id:
                raise HTTPException(409, "This session does not own the call.")
            if command == "listen":
                return await adapter.listen(payload.get("after"), payload.get("timeout", 25))
            return await adapter.reply(
                payload["thread"], payload.get("call_id"), payload.get("turn_id"),
                payload.get("item_id"), payload.get("text"), payload.get("final", True),
            )
        raise HTTPException(400, f"TalkToMe does not know the request {command!r}.")

    async def answer_request(request):
        try:
            result = await serve_request(request.command, request.payload)
            reply = {"result": result}
        except HTTPException as exc:
            reply = {"error": str(exc.detail)}
        except Exception as exc:
            logger.exception("An inbox request failed.")
            reply = {"error": str(exc) or "TalkToMe could not take that request."}
        try:
            inbox.answer(request, **reply)
        except OSError:
            # The folder went away. The command times out and says so.
            logger.warning("An inbox reply could not be written.", exc_info=True)

    async def watch_inbox():
        """Read requests that arrive as files, for commands with no network.

        Both folders are watched, because which one a command could write to
        depends on the sandbox it ran in and nothing here can know that in
        advance. A request is retired as soon as it is picked up, which is also
        the claim on it: it is not returned again, so a ring that takes ten
        seconds to resolve cannot be started twice by the next pass. Each one is
        handled in its own task for the same reason — an `end` while a call is
        ringing should not have to wait for the ring to finish asking.
        """
        prepared = False
        while True:
            # A failed pass is logged and tried again. If this loop stops, no
            # agent can ring the user.
            try:
                if not prepared:
                    inbox.ready()
                    inbox.sweep()
                    prepared = True
                for request in inbox.pending():
                    inbox.retire(request)
                    background(answer_request(request))
            except Exception:
                logger.exception("The inbox could not be read. TalkToMe tries again.")
            await asyncio.sleep(inbox.POLL)

    @app.get("/v1/managed")
    async def managed_state():
        return {"session": managed.snapshot()}

    @app.post("/v1/attach/start")
    async def attach_start(body: AttachBody):
        """Ring the app from a session a terminal already owns.

        Nothing is resumed and no writer is taken, so the terminal keeps working.
        This starts a ring, not a call: the user decides whether to answer.
        """
        return await managed.attach(
            body.thread, body.cwd, body.greeting, body.name, body.agent, body.connection,
        )

    @app.post("/v1/attach/accept")
    async def attach_accept(body: RingBody):
        return await managed.accept(body.ring_id)

    @app.post("/v1/attach/decline")
    async def attach_decline(body: RingBody):
        return await managed.decline(body.ring_id)

    @app.post("/v1/hangup")
    async def hangup():
        """End whatever call is live.

        A terminal does not know the call's identifier and should not have to look
        it up, so this takes no arguments and is safe to run when nothing is live.
        """
        return await managed.hangup()

    @app.post("/v1/managed/approvals/{approval_id}")
    async def managed_approval(approval_id: str, body: ApprovalBody):
        await managed.decide(approval_id, body.allow)
        return {"ok": True}

    @app.post("/v1/tts/speak")
    async def speak(body: SpeakBody):
        audio = await synthesize(body.text, body.voice)
        return Response(audio, media_type="audio/wav")

    @app.post("/v1/call/end")
    async def end(body: CallBody):
        if managed.adapter and managed.options and managed.options.get("provider") == "attach":
            room.require_call(body.call_id)
            await managed.hangup()
            result = room.snapshot()
        else:
            result = await room.end(body.call_id)
            await managed.interrupt()
        audio_cache.clear()
        return result

    @app.post("/v1/call/resume")
    async def resume(body: CallBody):
        room.require_call(body.call_id)
        await managed.resume()
        return {"ok": True}

    @app.post("/v1/call/interrupt")
    async def interrupt(body: InterruptBody):
        result = await room.interrupt(
            body.call_id, [item.model_dump() for item in body.playback], body.playback_epoch,
        )
        if result.get("status") == "stale":
            return result
        result["cancel_start_ms"] = time.time_ns() / 1_000_000
        await managed.interrupt(revision=result["next_epoch"])
        result["cancel_end_ms"] = time.time_ns() / 1_000_000
        result["agent_work_cancel_requested"] = managed.capabilities()["cancel_work"]
        return result

    @app.post("/v1/call/text")
    async def text(body: TextBody):
        if not body.text.strip():
            raise HTTPException(400, "Enter a message.")
        timing = {}
        if body.playback_epoch is not None:
            result = await interrupt(body)
            if result.get("status") == "stale" or room.revision != result["next_epoch"]:
                raise HTTPException(409, "A newer turn replaced this recording.")
            timing.update({key: result[key] for key in ("cancel_start_ms", "cancel_end_ms")})
        now_ms = time.time_ns() / 1_000_000
        for key in ("speech_end_ms", "capture_end_ms", "commit_sent_ms", "committed_ms", "transcribed_ms"):
            value = getattr(body, key)
            if value is not None and math.isfinite(value) and 0 <= now_ms - value <= 60_000:
                timing[key] = value
        for key in ("turn_reason", "turn_probability", "turn_check_ms"):
            if (value := getattr(body, key)) is not None:
                timing[key] = value
        event = await room.utterance(body.call_id, body.text.strip(), timing, timing_mode())
        await managed.submit(event)
        return event

    @app.post("/v1/stt/realtime-token")
    async def realtime_token(body: CallBody):
        room.require_call(body.call_id)
        if engine.recognition_provider() != "elevenlabs":
            raise HTTPException(409, "Select ElevenLabs speech input in Settings.")
        try:
            token = await asyncio.to_thread(engine.elevenlabs.realtime_token)
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
        room.require_call(body.call_id)
        return {"token": token}

    @app.post("/v1/speech/turn-detection")
    async def configure_turn_detection(body: TurnDetectionBody):
        nonlocal smart_turn_enabled, turn_setup_task
        async with settings_lock:
            require_idle()
            await asyncio.to_thread(engine.save_settings, smart_turn_enabled=body.enabled)
            smart_turn_enabled = body.enabled
            if body.enabled and (turn_setup_task is None or turn_setup_task.done()):
                turn_setup_task = background(load_turn_detector())
            await room.emit("turn_detector.updated")
            return speech_status()["smart_turn"]

    @app.post("/v1/call/turn-check")
    async def check_turn(request: Request, call_id: str, playback_epoch: int):
        room.require_call(call_id)
        if room.revision != playback_epoch:
            raise HTTPException(409, "A newer turn replaced this recording.")
        if not smart_turn_enabled or turn_detector.status()["status"] != "ready":
            raise HTTPException(503, "Smart Turn is not ready. Use the pause setting.")
        if turn_lock.locked():
            raise HTTPException(429, "A turn check is still active.")
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > MAX_AUDIO_BYTES:
                raise HTTPException(413, "Send at most eight seconds of microphone audio.")
        if turn_lock.locked():
            raise HTTPException(429, "A turn check is still active.")
        room.require_call(call_id)
        if room.revision != playback_epoch:
            raise HTTPException(409, "A newer turn replaced this recording.")
        # A canceled request must not leave unbounded native inference work.
        async with turn_lock:
            work = asyncio.create_task(asyncio.to_thread(turn_detector.predict, bytes(chunks)))
            try:
                result = await asyncio.shield(work)
            except asyncio.CancelledError:
                await asyncio.gather(work, return_exceptions=True)
                raise
            except SmartTurnUnavailable as exc:
                logger.exception("Smart Turn inference stopped.")
                await room.emit("turn_detector.updated")
                raise HTTPException(503, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        room.require_call(call_id)
        if room.revision != playback_epoch:
            raise HTTPException(409, "A newer turn replaced this recording.")
        return {**result, "call_id": call_id, "playback_epoch": playback_epoch}

    async def transcribe(request):
        if engine.status()["status"] != "ready":
            raise HTTPException(409, "Download a speech model before you use the microphone.")
        if transcription_lock.locked():
            raise HTTPException(429, "Wait for the current transcription to end.")
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > 8 * 1024 * 1024:
                raise HTTPException(413, "The audio exceeds 8 MB. Send a shorter recording.")
        async with transcription_lock:
            try:
                return await asyncio.to_thread(engine.transcribe, bytes(chunks))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

    @app.post("/v1/stt/transcribe")
    async def stt(request: Request):
        return await transcribe(request)

    @app.post("/v1/call/audio")
    async def call_audio(request: Request, call_id: str):
        room.require_call(call_id)
        original_revision = room.revision
        result = await transcribe(request)
        transcribed_ms = time.time_ns() / 1_000_000
        room.require_call(call_id)
        if room.revision != original_revision:
            raise HTTPException(409, "A newer turn replaced this recording.")
        if result["text"]:
            timing = {"transcribed_ms": transcribed_ms}
            reason = request.headers.get("x-talktome-turn-reason")
            if reason in {"smart_turn", "pause", "silence_limit", "duration_limit"}:
                timing["turn_reason"] = reason
            for key, maximum in (("turn_probability", 1), ("turn_check_ms", 60_000)):
                try:
                    value = float(request.headers.get(f"x-talktome-{key.replace('_', '-')}", ""))
                    if math.isfinite(value) and 0 <= value <= maximum:
                        timing[key] = value
                except ValueError:
                    pass
            try:
                speech_end_ms = float(request.headers.get("x-talktome-speech-end-ms", ""))
                if math.isfinite(speech_end_ms) and 0 <= transcribed_ms - speech_end_ms <= 60_000:
                    timing["speech_end_ms"] = speech_end_ms
            except ValueError:
                pass
            try:
                capture_end_ms = float(request.headers.get("x-talktome-capture-end-ms", ""))
                if math.isfinite(capture_end_ms) and 0 <= transcribed_ms - capture_end_ms <= 60_000:
                    timing["capture_end_ms"] = capture_end_ms
            except ValueError:
                pass
            result["event"] = await room.utterance(call_id, result["text"], timing, timing_mode())
            await managed.submit(result["event"])
        return result

    @app.post("/v1/call/timing")
    async def call_timing(body: TimingBody):
        if not timing_history.contains(body.call_id, body.turn_id):
            raise HTTPException(409, "This turn has no timing record.")
        changed = False
        for stage in (
            "first_audio_ms",
            "commit_sent_ms",
            "committed_ms",
            "first_audio_scheduled_ms",
        ):
            value = getattr(body, stage)
            if value is not None and math.isfinite(value):
                changed = room.mark_timing(body.turn_id, stage, value, body.call_id) or changed
        return {"ok": True, "recorded": changed}

    @app.get("/v1/call/timings")
    async def call_timings(call_id: str | None = Query(default=None, max_length=100)):
        return {"timings": timing_history.list(call_id)}

    @app.get("/v1/audio/{audio_id}")
    async def get_audio(audio_id: str):
        if audio_id not in audio_cache:
            raise HTTPException(404, "This audio expired.")
        return Response(audio_cache[audio_id], media_type="audio/wav")

    # The Settings window ends the connection to the agent here.
    @app.post("/v1/agent/disconnect")
    async def disconnect():
        await managed.close()
        return {"ok": True}

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True))
    return app
