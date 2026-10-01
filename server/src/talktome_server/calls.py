"""How an agent calls its user through the app.

A call has two shapes. With a question, it rings, the app asks the question,
the user's first answer comes back, the call says "Got it", and it hangs up.
Without a question, it stays open: the agent speaks with turn(), and each
result is the user's next sentence, until end().
"""

import asyncio
import re
import secrets
import time

ANSWER_WAIT = 90.0
RING_WAIT = 45.0  # the app stops a ring after 30 seconds
ACKNOWLEDGE = "Got it."
MAX_REASON = 200
MAX_TEXT = 4000


class NoCall(Exception):
    def __init__(self):
        super().__init__("there is no live call. Start one with call_user")


class CallIsLive(Exception):
    def __init__(self):
        super().__init__("a call is already live. Continue it with call_turn, or end it with end_call")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


class _Call:
    def __init__(self, call_id: str):
        self.id = call_id
        self.frames: asyncio.Queue = asyncio.Queue()
        self.pending: tuple[str, str] | None = None  # (turn_id, text)
        self.progress = 0
        self.speaking_until = 0.0
        self.ended = False


class Caller:
    def __init__(self, link):
        self.link = link
        self._one_call = asyncio.Lock()
        self._live: _Call | None = None
        self._routes: dict[str, _Call] = {}

    def owns(self, call_id: str) -> bool:
        return call_id in self._routes

    def dispatch(self, frame: dict) -> None:
        call = self._routes.get(frame.get("call_id", ""))
        if call:
            call.frames.put_nowait(frame)

    async def call(self, reason: str, question: str = "", choices=None, greeting: str = "", urgency: str = "") -> dict:
        async with self._one_call:
            if self._live and not self._live.ended:
                raise CallIsLive()
            call = _Call(new_id("call"))
            self._routes[call.id] = call
            body = {}
            if question.strip():
                body["question"] = question.strip()
                if choices:
                    body["choices"] = list(choices)
            elif greeting.strip():
                body["greeting"] = greeting.strip()
            await self.link.send(
                "call.start", call_id=call.id, reason=reason[:MAX_REASON], urgency=urgency or "normal", body=body
            )
            answered, status = await self._wait_answer(call)
            if not answered:
                self._forget(call)
                return {"answered": False, "status": status}
            self._live = call

            heard = await self._next_turn(call, ANSWER_WAIT)
            if not question.strip():
                result = {"answered": True, "call": call.id, "ended": call.ended}
                if heard:
                    result["user_said"] = heard
                if call.ended:
                    self._forget(call)
                return result
            result = {"answered": True}
            say = ""
            if heard:
                result["answer"] = heard
                choice = match_choice(heard, choices or [])
                if choice:
                    result["choice"] = choice
                say = ACKNOWLEDGE
            await self._finish(call, say)
            return result

    async def _wait_answer(self, call: _Call) -> tuple[bool, str]:
        deadline = time.monotonic() + RING_WAIT
        while (left := deadline - time.monotonic()) > 0:
            try:
                frame = await asyncio.wait_for(call.frames.get(), left)
            except TimeoutError:
                break
            if frame["type"] == "call.answered":
                return True, "answered"
            if frame["type"] in ("call.missed", "call.ended"):
                return False, frame.get("reason", "")
        return False, "no_answer"

    async def _next_turn(self, call: _Call, wait: float) -> str | None:
        deadline = time.monotonic() + wait
        while not call.ended and (left := deadline - time.monotonic()) > 0:
            try:
                frame = await asyncio.wait_for(call.frames.get(), left)
            except TimeoutError:
                return None
            kind = frame["type"]
            if kind == "turn.user":
                call.pending = (frame.get("turn_id", ""), frame.get("text", ""))
                call.progress = 0
                return call.pending[1]
            if kind == "turn.cancel" and call.pending and call.pending[0] == frame.get("turn_id"):
                call.pending = None
            elif kind == "call.ended":
                call.ended = True
        return None

    async def _speak(self, call: _Call, text: str) -> bool:
        if not call.pending or call.ended:
            return False
        turn_id = call.pending[0]
        call.pending = None
        await self.link.send(
            "turn.agent", call_id=call.id, turn_id=turn_id, item_id=turn_id + "-final", text=text[:MAX_TEXT], final=True
        )
        start = max(time.monotonic(), call.speaking_until)
        call.speaking_until = start + speech_time(text)
        return True

    async def _finish(self, call: _Call, say: str) -> None:
        if say:
            await self._speak(call, say)
        wait = call.speaking_until - time.monotonic()
        if wait > 0 and not call.ended:
            await asyncio.sleep(wait)
        if not call.ended:
            call.ended = True
            await self.link.send("call.end", call_id=call.id, reason="done")
        self._forget(call)

    def _forget(self, call: _Call) -> None:
        self._routes.pop(call.id, None)
        if self._live is call:
            self._live = None

    def _current(self) -> _Call:
        if not self._live or self._live.ended:
            raise NoCall()
        return self._live

    async def turn(self, say: str) -> dict:
        async with self._one_call:
            call = self._current()
            spoken = await self._speak(call, say)
            heard = await self._next_turn(call, ANSWER_WAIT)
            if call.ended:
                self._forget(call)
            return {"spoken": spoken, "user_said": heard, "ended": call.ended}

    async def progress(self, text: str) -> bool:
        """Speak in the pending turn without ending it, for example "Let me check."."""
        async with self._one_call:
            call = self._current()
            if not call.pending or call.ended or not text.strip():
                return False
            call.progress += 1
            turn_id = call.pending[0]
            await self.link.send(
                "turn.agent",
                call_id=call.id,
                turn_id=turn_id,
                item_id=f"{turn_id}-p{call.progress}",
                text=text[:MAX_TEXT],
                final=False,
            )
            return True

    async def end(self, say: str = "") -> None:
        async with self._one_call:
            if self._live and not self._live.ended:
                await self._finish(self._live, say)

    async def notify(self, reason: str, message: str, urgency: str = "") -> int:
        await self.link.send(
            "notify",
            notice_id=new_id("notice"),
            reason=reason[:MAX_REASON],
            urgency=urgency or "normal",
            body={"message": message[:MAX_TEXT]},
        )
        return 1


def speech_time(text: str) -> float:
    """About how long the app takes to say this. A goodbye needs this long before the hang-up."""
    return min(1.5 + len(text) / 14, 20.0)


_NUMBERS = {
    "one": 0, "first": 0, "1": 0,
    "two": 1, "second": 1, "2": 1,
    "three": 2, "third": 2, "3": 2,
    "four": 3, "fourth": 3, "4": 3,
    "five": 4, "fifth": 4, "5": 4,
}  # fmt: skip
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def match_choice(answer: str, choices: list[str]) -> dict | None:
    """The choice the user named, by its words or by its position."""
    if not choices or not answer:
        return None
    heard = _NON_WORD.sub(" ", answer.lower())
    named = [i for i, choice in enumerate(choices) if choice.strip() and choice.strip().lower() in heard]
    if len(named) == 1:
        return {"index": named[0], "label": choices[named[0]]}
    if not named:
        for word in heard.split():
            if word in _NUMBERS and _NUMBERS[word] < len(choices):
                i = _NUMBERS[word]
                return {"index": i, "label": choices[i]}
    return None
