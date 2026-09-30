"""talktome as a Hermes platform.

A voice call is a chat on this platform. The agent starts it with the
``talktome_call`` tool from any other chat. After the user answers, the call's
chat is bound to the session that placed the call, so the voice turns continue
that conversation. Each thing the user says arrives as an ordinary inbound
message, and what Hermes sends back is spoken.

The talktome server on this machine runs the call. The plugin reaches it
over its local API: ``call`` returns the user's first sentence, and ``turn``
speaks the answer and returns the user's next sentence.

Hermes can send more than one message for a turn, for example a short note
before a tool call and then the answer. The adapter holds the newest message and
speaks the one before it as progress. When Hermes finishes the turn, the held
message is spoken as the final answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from gateway.config import Platform
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    ProcessingOutcome,
    SendResult,
)

from .client import LocalClient, TalkToMeError, data_dir, speakable

logger = logging.getLogger(__name__)

PLATFORM = "talktome"
DEFAULT_GREETING = "Hey, what would you like to talk about?"
FAILED = "Sorry, something went wrong on my side."
TOOL_WAIT = 300

PLATFORM_HINT = (
    "You are in a live talktome voice call. The user hears each message you send as "
    "speech, and you hear the user as text. Answer in one or two short spoken "
    "sentences unless the user asks for detail. Do not use markdown, lists, code, "
    "file paths, or URLs. Do not keep the user waiting in silence. If a request needs "
    "more than about a minute of work, choose one: start it in a background subagent, "
    "tell the user in one sentence, and keep talking; or say \"I'll call you back when "
    "I'm done with that\", call talktome_end, do the work, and then call talktome_call "
    "with the result in the greeting, in one or two spoken sentences. Keep technical "
    "detail for a written follow-up in another chat."
)

_adapter: TalkToMeAdapter | None = None


@dataclass
class Turn:
    id: str
    answer: asyncio.Future
    held: str | None = None
    held_id: str | None = None
    items: int = 0
    finished: bool = False


@dataclass
class Call:
    chat: str
    client: LocalClient
    source: Any
    turn: Turn | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None


class TalkToMeAdapter(BasePlatformAdapter):
    MAX_MESSAGE_LENGTH = 4000
    # The user's answer to the ring authorizes each turn.
    authorization_is_upstream = True

    def __init__(self, config):
        super().__init__(config=config, platform=Platform(PLATFORM))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._call: Call | None = None
        self.client = LocalClient.default()

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        global _adapter
        self._loop = asyncio.get_running_loop()
        _adapter = self
        self._mark_connected()
        return True

    async def disconnect(self) -> None:
        global _adapter
        call, self._call = self._call, None
        if call and call.task:
            call.task.cancel()
        if _adapter is self:
            _adapter = None
        self._mark_disconnected()

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        return {"name": "talktome call", "type": "dm", "chat_id": chat_id}

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        pass

    async def send_image(self, chat_id, image_url, caption=None, reply_to=None, metadata=None):
        if caption:
            return await self.send(chat_id, caption)
        return SendResult(success=True)

    # -- starting and ending a call ------------------------------------------

    def run(self, coroutine, timeout: float):
        """Run a coroutine on the gateway loop from a tool's thread."""
        if self._loop is None:
            raise TalkToMeError("The talktome platform is not connected.")
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            raise TalkToMeError("The talktome tool cannot wait on the gateway loop.")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout)

    async def start_call(self, session_id: str, greeting: str, name: str | None) -> dict:
        if self._call is not None:
            return {"answered": False, "error": "A talktome call is already live."}
        result = await self.client.call(reason=name or "Hermes", greeting=greeting)
        if not result.get("answered"):
            return {"answered": False, "status": result.get("status") or "not answered"}
        chat = f"call-{uuid.uuid4().hex[:16]}"
        source = self.build_source(
            chat_id=chat,
            chat_name=name or "talktome call",
            chat_type="dm",
            user_id="talktome",
            user_name="talktome",
        )
        await self._bind(source, session_id)
        call = Call(chat=chat, client=self.client, source=source)
        self._call = call
        call.task = asyncio.create_task(self._converse(call, result))
        return {"answered": True, "call": chat}

    async def _bind(self, source, session_id: str) -> None:
        """Point this call's chat at the session that placed the call."""
        runner = getattr(self, "gateway_runner", None)
        store = getattr(runner, "async_session_store", None)
        if store is None or not session_id:
            logger.warning("[talktome] No session store, so the call starts a new session.")
            return
        entry = await store.get_or_create_session(source)
        if await store.switch_session(entry.session_key, session_id) is None:
            logger.warning("[talktome] Could not bind the call to session %s.", session_id)
            return
        evict = getattr(runner, "_evict_cached_agent", None)
        if evict:
            evict(entry.session_key)

    async def end_call(self) -> dict:
        """Hang up after the last message is spoken.

        The agent can end the call in the middle of its own turn, for example
        after "I'll call you back". That sentence is still held, so the agent
        node speaks it as the goodbye. The turn itself keeps running.
        """
        call = self._call
        if call is None:
            return await self.client.end()
        async with call.lock:
            turn = call.turn
            goodbye = turn.held if turn and not turn.finished else None
            if turn:
                turn.finished = True
                if not turn.answer.done():
                    turn.answer.cancel()
            call.turn = None
        self._call = None
        if call.task:
            call.task.cancel()
        return await call.client.end(goodbye or "")

    # -- the conversation ------------------------------------------------------

    async def _converse(self, call: Call, first: dict) -> None:
        """Hand each thing the user says to Hermes, and speak each answer."""
        heard, ended = first.get("user_said"), first.get("ended")
        try:
            while self._call is call and not ended:
                if heard:
                    answer = await self._dispatch(call, heard)
                else:
                    answer = ""
                result = await call.client.turn(answer)
                heard, ended = result.get("user_said"), result.get("ended")
        except asyncio.CancelledError:
            raise
        except TalkToMeError as exc:
            logger.warning("[talktome] The call stopped: %s", exc)
        except Exception:
            logger.exception("[talktome] The call stopped.")
        finally:
            if self._call is call:
                self._call = None
            logger.info("[talktome] Call %s ended.", call.chat)

    async def _dispatch(self, call: Call, text: str) -> str:
        """Give Hermes one thing the user said, and wait for its answer."""
        turn = Turn(id=uuid.uuid4().hex[:16], answer=asyncio.get_running_loop().create_future())
        async with call.lock:
            call.turn = turn
        event = MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=call.source,
            message_id=turn.id,
            raw_message={"text": text},
            timestamp=datetime.now(tz=UTC),
        )
        await self.handle_message(event)
        return await turn.answer

    # -- speaking --------------------------------------------------------------

    def _current(self, chat_id: str) -> tuple[Call, Turn] | None:
        call = self._call
        if call is None or call.chat != chat_id or call.turn is None:
            return None
        return call, call.turn

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        live = self._current(chat_id)
        if live is None:
            # The turn ended or the call closed. There is nobody to speak to.
            return SendResult(success=True)
        call, turn = live
        text = speakable(content)
        if not text:
            return SendResult(success=True)
        async with call.lock:
            if turn.finished:
                return SendResult(success=True)
            if turn.held is not None:
                try:
                    await call.client.progress(turn.held)
                except TalkToMeError as exc:
                    logger.info("[talktome] Progress not spoken: %s", exc)
            turn.items += 1
            turn.held = text
            turn.held_id = f"{turn.id}-{turn.items}"
        return SendResult(success=True, message_id=turn.held_id)

    async def edit_message(self, chat_id, message_id, content, *args, **kwargs) -> SendResult:
        live = self._current(chat_id)
        if live is None:
            return SendResult(success=True, message_id=message_id)
        call, turn = live
        async with call.lock:
            if turn.held_id == message_id and not turn.finished:
                turn.held = speakable(content) or turn.held
        return SendResult(success=True, message_id=message_id)

    async def on_processing_complete(self, event: MessageEvent, outcome: ProcessingOutcome) -> None:
        call = self._call
        if call is None or event.source.chat_id != call.chat:
            return
        async with call.lock:
            turn = call.turn
            if turn is None or turn.id != event.message_id or turn.finished:
                return
            text = turn.held
            if text is None and outcome == ProcessingOutcome.FAILURE:
                text = FAILED
            turn.finished = True
            if call.turn is turn:
                call.turn = None
            if not turn.answer.done():
                turn.answer.set_result(text or "")


# -- tools ----------------------------------------------------------------------

CALL_SCHEMA = {
    "name": "talktome_call",
    "description": (
        "Ring the user for a live talktome voice call on their devices. Use it when the user "
        "says call me, ring me, or talk to me. This is a voice call to the user's own devices, "
        "not a phone call, so do not look for a phone or telephony tool. After the user answers, "
        "the call continues this conversation by voice. To call back with a result, "
        "put the result in the greeting. Returns whether they answered."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "greeting": {
                "type": "string",
                "description": "The first sentence the user hears. Write it as speech.",
            },
            "name": {
                "type": "string",
                "description": "A short title that shows while the call rings.",
            },
        },
        "additionalProperties": False,
    },
}

END_SCHEMA = {
    "name": "talktome_end",
    "description": (
        "End the live talktome voice call, or stop a ring. Anything you already said "
        "is spoken first. Your current work keeps running."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


def _result(value: dict) -> str:
    return json.dumps(value)


def _session_id() -> str:
    from gateway.session_context import get_session_env

    return get_session_env("HERMES_SESSION_ID", "")


def handle_call(args: dict, **_kw) -> str:
    adapter = _adapter
    if adapter is None:
        return _result({"answered": False, "error": "The talktome platform is not running in this Hermes gateway."})
    greeting = (args.get("greeting") or "").strip() or DEFAULT_GREETING
    name = (args.get("name") or "").strip() or None
    try:
        return _result(adapter.run(adapter.start_call(_session_id(), greeting, name), TOOL_WAIT))
    except TalkToMeError as exc:
        return _result({"answered": False, "error": str(exc)})


def handle_end(args: dict, **_kw) -> str:
    adapter = _adapter
    try:
        if adapter is None:
            raise TalkToMeError("The talktome platform is not running in this Hermes gateway.")
        return _result(adapter.run(adapter.end_call(), TOOL_WAIT))
    except TalkToMeError as exc:
        return _result({"ended": False, "error": str(exc)})


# -- registration ---------------------------------------------------------------


def check_requirements() -> bool:
    """talktome-server is set up on this machine."""
    return data_dir().exists()


def _env_enablement() -> dict | None:
    # Installing the plugin is the setup. There is nothing to configure here.
    # A home channel stops the gateway from asking for /sethome in the first call.
    if not check_requirements():
        return None
    return {"home_channel": {"chat_id": PLATFORM, "name": "talktome"}}


def register(ctx) -> None:
    ctx.register_platform(
        name=PLATFORM,
        label="talktome",
        adapter_factory=lambda config: TalkToMeAdapter(config),
        check_fn=check_requirements,
        validate_config=lambda config: True,
        is_connected=lambda config: check_requirements(),
        install_hint="Run talktome-server plugin install --host hermes, then restart the gateway.",
        env_enablement_fn=_env_enablement,
        max_message_length=TalkToMeAdapter.MAX_MESSAGE_LENGTH,
        emoji="📞",
        pii_safe=True,
        platform_hint=PLATFORM_HINT,
    )
    ctx.register_tool(
        name="talktome_call",
        toolset="talktome",
        schema=CALL_SCHEMA,
        handler=handle_call,
        check_fn=check_requirements,
        emoji="📞",
    )
    ctx.register_tool(
        name="talktome_end",
        toolset="talktome",
        schema=END_SCHEMA,
        handler=handle_end,
        check_fn=check_requirements,
        emoji="📞",
    )
