"""TalkToMe as a Hermes platform.

A voice call is a chat on this platform. The agent starts it with the
``talktome_call`` tool from any other chat. After the user answers, the call's
chat is bound to the session that placed the call, so the voice turns continue
that conversation. The adapter runs ``talktome listen`` itself and turns each
spoken user turn into an ordinary inbound message. What Hermes sends back is
spoken. The model never runs the listen and reply loop.

Hermes can send more than one message for a turn, for example a short note
before a tool call and then the answer. The adapter holds the newest message and
speaks the one before it as progress. When Hermes finishes the turn, the held
message is spoken as the final reply.
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

from .client import TalkToMeClient, TalkToMeError, find_command, speakable

logger = logging.getLogger(__name__)

PLATFORM = "talktome"
DEFAULT_GREETING = "Hey, what would you like to talk about?"
MAX_LISTEN_FAILURES = 4
TOOL_WAIT = 150

PLATFORM_HINT = (
    "You are in a live TalkToMe voice call. The user hears each message you send as "
    "speech, and you hear the user as text. Answer in one or two short spoken "
    "sentences unless the user asks for detail. Do not use markdown, lists, code, "
    "file paths, or URLs. Before long work, say in a few words what you will do. "
    "Keep technical detail for a written follow-up in another chat."
)

_adapter: TalkToMeAdapter | None = None


@dataclass
class Turn:
    call_id: str
    turn_id: str
    held: str | None = None
    held_id: str | None = None
    items: int = 0
    finished: bool = False


@dataclass
class Call:
    thread: str
    client: TalkToMeClient
    source: Any
    turn: Turn | None = None
    seen: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None


class TalkToMeAdapter(BasePlatformAdapter):
    MAX_MESSAGE_LENGTH = 4000
    # The bridge credential and the user's answer to the ring authorize each turn.
    authorization_is_upstream = True

    def __init__(self, config):
        super().__init__(config=config, platform=Platform(PLATFORM))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._call: Call | None = None

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
        return {"name": "TalkToMe call", "type": "dm", "chat_id": chat_id}

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
            raise TalkToMeError("The TalkToMe platform is not connected.")
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            raise TalkToMeError("The TalkToMe tool cannot wait on the gateway loop.")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout)

    async def start_call(self, session_id: str, greeting: str, name: str | None) -> dict:
        if self._call is not None:
            return {"answered": False, "error": "A TalkToMe call is already live."}
        client = await TalkToMeClient.discover()
        thread = f"hermes-{uuid.uuid4().hex[:16]}"
        result = await client.call(thread, greeting, name)
        if not result.get("answered"):
            return {"answered": False, "status": result.get("status") or "not answered"}
        source = self.build_source(
            chat_id=thread,
            chat_name=name or "TalkToMe call",
            chat_type="dm",
            user_id="talktome",
            user_name="TalkToMe",
        )
        await self._bind(source, session_id)
        call = Call(thread=thread, client=client, source=source)
        call.task = asyncio.create_task(self._listen(call))
        self._call = call
        return {"answered": True, "call": thread, "remote": client.remote}

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
        call = self._call
        if call is None:
            client = await TalkToMeClient.discover()
            return await client.end()
        self._call = None
        try:
            return await call.client.end()
        finally:
            if call.task:
                call.task.cancel()

    # -- the listen loop -------------------------------------------------------

    async def _listen(self, call: Call) -> None:
        after = 0
        failures = 0
        try:
            while self._call is call:
                try:
                    result = await call.client.listen(call.thread, after)
                except TalkToMeError as exc:
                    failures += 1
                    logger.warning("[talktome] listen failed (%d): %s", failures, exc)
                    if failures >= MAX_LISTEN_FAILURES:
                        break
                    await asyncio.sleep(2**failures)
                    continue
                failures = 0
                after = int(result.get("seq") or 0)
                for event in result.get("events") or []:
                    if event.get("type") == "turn.cancelled":
                        await self._cancelled(call, event.get("turn_id"))
                if result.get("closed"):
                    break
                pending = result.get("pending")
                if pending and pending.get("turn_id") not in call.seen:
                    await self._dispatch(call, pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[talktome] The listen loop stopped.")
        finally:
            if self._call is call:
                self._call = None
            logger.info("[talktome] Call %s ended.", call.thread)

    async def _cancelled(self, call: Call, turn_id: str | None) -> None:
        async with call.lock:
            if call.turn and call.turn.turn_id == turn_id:
                call.turn.finished = True
                call.turn = None

    async def _dispatch(self, call: Call, pending: dict) -> None:
        turn = Turn(call_id=pending["call_id"], turn_id=pending["turn_id"])
        async with call.lock:
            call.seen.add(turn.turn_id)
            call.turn = turn
        event = MessageEvent(
            text=pending.get("text") or "",
            message_type=MessageType.TEXT,
            source=call.source,
            message_id=turn.turn_id,
            raw_message=pending,
            timestamp=datetime.now(tz=UTC),
        )
        await self.handle_message(event)

    # -- speaking --------------------------------------------------------------

    def _current(self, chat_id: str) -> tuple[Call, Turn] | None:
        call = self._call
        if call is None or call.thread != chat_id or call.turn is None:
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
                await self._speak(call, turn, turn.held, final=False)
            turn.items += 1
            turn.held = text
            turn.held_id = f"{turn.turn_id}-{turn.items}"
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
        if call is None or event.source.chat_id != call.thread:
            return
        async with call.lock:
            turn = call.turn
            if turn is None or turn.turn_id != event.message_id or turn.finished:
                return
            text = turn.held
            if text is None and outcome == ProcessingOutcome.FAILURE:
                text = "Sorry, something went wrong on my side."
            turn.held = None
            try:
                await self._speak(call, turn, text or "", final=True)
            finally:
                turn.finished = True
                if call.turn is turn:
                    call.turn = None

    async def _speak(self, call: Call, turn: Turn, text: str, final: bool) -> None:
        item_id = f"{turn.turn_id}-{'final' if final else turn.items}"
        try:
            await call.client.reply(call.thread, turn.call_id, turn.turn_id, item_id, text, final)
        except TalkToMeError as exc:
            # A cancelled or replaced turn refuses replies. The next turn is
            # already on its way, so the reply is dropped.
            logger.info("[talktome] Reply not spoken: %s", exc)


# -- tools ----------------------------------------------------------------------

CALL_SCHEMA = {
    "name": "talktome_call",
    "description": (
        "Ring the user for a live TalkToMe voice call on their Mac. Use it when the user "
        "says call me, ring me, or talk to me. This is a desktop voice call, not a phone "
        "call, so do not look for a phone or telephony tool. After the user answers, "
        "the call continues this conversation by voice. Returns whether they answered."
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
    "description": "End the live TalkToMe voice call, or stop a ring.",
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
        return _result(
            {
                "answered": False,
                "error": "The TalkToMe platform is not running in this Hermes gateway.",
            }
        )
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
            raise TalkToMeError("The TalkToMe platform is not running in this Hermes gateway.")
        return _result(adapter.run(adapter.end_call(), TOOL_WAIT))
    except TalkToMeError as exc:
        return _result({"ended": False, "error": str(exc)})


# -- registration ---------------------------------------------------------------


def check_requirements() -> bool:
    return find_command() is not None


def _env_enablement() -> dict | None:
    # Installing the talktome command is the setup. There is nothing to configure.
    # A home channel stops the gateway from asking for /sethome in the first call.
    if not check_requirements():
        return None
    return {"home_channel": {"chat_id": PLATFORM, "name": "TalkToMe"}}


def register(ctx) -> None:
    ctx.register_platform(
        name=PLATFORM,
        label="TalkToMe",
        adapter_factory=lambda config: TalkToMeAdapter(config),
        check_fn=check_requirements,
        validate_config=lambda config: True,
        is_connected=lambda config: check_requirements(),
        install_hint="Install the talktome command, then restart the gateway.",
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
