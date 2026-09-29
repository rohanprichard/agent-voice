import asyncio
import contextlib
import json

from .agents import find_command

# One stream-json line can hold a whole tool result.
LINE_LIMIT = 16 * 1024 * 1024
STOP_TIMEOUT = 2


class ClaudeResumeAdapter:
    """Run one `claude -p --resume` process for each turn of a call back.

    Print mode has no one to ask, so a tool that needs permission is denied
    unless the user's Claude settings already allow it.
    """

    agent_name = "Claude"

    def __init__(self, session_id, cwd):
        self.session_id = session_id
        self.cwd = cwd
        self.binary = None
        self.process = None
        self.capabilities = {"text_stream": True, "tool_status": True, "stop": True, "resume": True}

    async def start(self):
        self.binary = await asyncio.to_thread(find_command, "claude")
        if not self.binary:
            raise ValueError(
                "Claude Code could not be found. If it is installed, quit and reopen "
                "TalkToMe so it can see your shell's PATH."
            )

    def argv(self):
        return [
            self.binary, "-p", "--resume", self.session_id,
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        ]

    async def run(self, text, emit, approve):
        process = await asyncio.create_subprocess_exec(
            *self.argv(),
            cwd=self.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=LINE_LIMIT,
        )
        self.process = process
        errors = asyncio.create_task(process.stderr.read())
        try:
            process.stdin.write(text.encode())
            await process.stdin.drain()
            process.stdin.close()
            result = await self._read(process.stdout, emit)
            await process.wait()
            if result is None or result.get("is_error") or process.returncode:
                detail = (result or {}).get("result") or (await errors).decode(errors="replace").strip()
                lines = detail.splitlines()
                raise RuntimeError(f"Claude Code stopped. {lines[-1] if lines else ''}".strip())
        finally:
            errors.cancel()
            await self._stop(process)

    async def _read(self, stdout, emit):
        message_id = ""
        blocks = {}
        while line := await stdout.readline():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("parent_tool_use_id"):
                # A subagent's stream is not what the user hears.
                continue
            kind = record.get("type")
            if kind == "system" and record.get("subtype") == "init" and record.get("session_id"):
                self.session_id = record["session_id"]
            elif kind == "stream_event":
                event = record.get("event") or {}
                name = event.get("type")
                index = event.get("index")
                if name == "message_start":
                    message_id = (event.get("message") or {}).get("id") or ""
                elif name == "content_block_start":
                    block = event.get("content_block") or {}
                    blocks[index] = block.get("type")
                    if block.get("type") == "tool_use":
                        await emit("tool.status", text=f"Using {block.get('name') or 'a tool'}", status="active")
                elif name == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        await emit("message.delta", item_id=f"claude:{message_id}:{index}", text=delta["text"])
                elif name == "content_block_stop" and blocks.get(index) == "text":
                    await emit("message.done", item_id=f"claude:{message_id}:{index}")
            elif kind == "user":
                # A tool result comes back to the model as a user message.
                await emit("tool.status", text="Tool finished", status="done")
            elif kind == "result":
                if record.get("permission_denials"):
                    await emit(
                        "tool.status",
                        text="Claude skipped a tool that needs permission.",
                        status="done",
                    )
                return record
        return None

    async def _stop(self, process):
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), STOP_TIMEOUT)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        if self.process is process:
            self.process = None

    async def close(self):
        if self.process is not None:
            await self._stop(self.process)
