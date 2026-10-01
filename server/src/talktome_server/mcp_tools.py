"""The call tools over MCP, for Claude Code, Codex, and other MCP hosts. They
reach the running server through its local socket."""

import asyncio
import json
import os

from mcp.server.fastmcp import FastMCP

from . import paths
from .api import Client

INSTRUCTIONS = """talktome lets you reach your user by voice. Their computer rings, and they answer.

Call the user when you need a decision you cannot make yourself, when you are
blocked, or when they asked you to report back. Do not call for things you can
decide, and do not call to report progress nobody asked for. Use notify_user for
news that needs no answer.

For one decision, call call_user with a question, and choices when there are a
few clear options. The call ends by itself, and the result is their answer.
For a conversation, call call_user without a question, then use call_turn for
each thing you say, and end_call at the end.

When the user asks you to do some work and then call them, do the work first, and
call once, with the result. Do not call to say that you are starting.

If the user asks during a call for work that needs more than about a minute, do not
keep them waiting on the line. Say "I'll call you back when I'm done with that", end
the call, do the work, and call again with the result in the greeting.

Everything you pass is spoken aloud. Write it as short, plain speech, with no
markdown, code, file paths, or URLs."""

CALL_TIMEOUT = 240
TURN_TIMEOUT = 150


def _post(route: str, body: dict, timeout: float = 30) -> dict:
    return Client(paths.socket_path()).request("POST", route, body, timeout)


def call_tools() -> FastMCP:
    server = FastMCP("talktome", instructions=INSTRUCTIONS)

    @server.tool()
    async def call_user(
        reason: str, question: str = "", choices: list[str] | None = None, greeting: str = "", urgency: str = "normal"
    ) -> dict:
        """Ring the user. With a question, the call asks it, waits for the spoken answer, and hangs up; the
        result holds the answer and the matching choice. Without a question, the call stays open for call_turn.
        Returns answered: false when the user declines, does not pick up, or is not connected.

        reason: a few words the user sees while it rings, such as Needs a decision on the migration.
        question: one question to ask. The call ends after the answer.
        choices: short options for the question. The user can name one or say its number.
        greeting: the first sentence of a conversation, when there is no question.
        urgency: normal or urgent."""
        body = {
            "reason": reason,
            "question": question,
            "choices": choices or [],
            "greeting": greeting,
            "urgency": urgency,
        }
        return await asyncio.to_thread(_post, "/v1/call", body, CALL_TIMEOUT)

    @server.tool()
    async def call_turn(say: str) -> dict:
        """Say something in the open call, then return what the user says next. user_said is null when the
        user said nothing in time. ended is true when they hung up."""
        return await asyncio.to_thread(_post, "/v1/turn", {"say": say}, TURN_TIMEOUT)

    @server.tool()
    async def end_call(say: str = "") -> dict:
        """End the open call. Pass say for a short goodbye, which plays before the hang-up."""
        return await asyncio.to_thread(_post, "/v1/end", {"say": say})

    @server.tool()
    async def notify_user(reason: str, message: str, urgency: str = "normal") -> dict:
        """Show a notice to the user without ringing. Use it for news that needs no answer, such as a
        finished task. The message is shown, not spoken."""
        body = {"reason": reason, "message": message, "urgency": urgency}
        return await asyncio.to_thread(_post, "/v1/notify", body)

    return server


def permission_tool() -> FastMCP:
    """Claude Code's permission prompt tool during a call from the user. It asks
    the user in that call, and answers in the form Claude expects:
    {"behavior": "allow", "updatedInput": ...} or {"behavior": "deny", "message": ...}."""
    server = FastMCP("talktome_permission")
    call_id = os.environ.get("TALKTOME_CALL_ID", "")

    @server.tool()
    async def approve(tool_name: str, input: dict, tool_use_id: str = "") -> str:
        """Ask the user in the live talktome call whether a tool may run."""
        try:
            result = await asyncio.to_thread(
                _post, "/v1/permission", {"call_id": call_id, "tool": tool_name, "input": input}, 150
            )
        except Exception as exc:  # noqa: BLE001 - any failure is a denial
            return json.dumps({"behavior": "deny", "message": str(exc)})
        if result.get("allow"):
            return json.dumps({"behavior": "allow", "updatedInput": input})
        return json.dumps({"behavior": "deny", "message": result.get("message", "")})

    return server
