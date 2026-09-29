"""Keep one experimental Codex queue connection for one call."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from uuid import uuid4

from .agents import find_command

INITIALIZE_TIMEOUT = 10
QUEUE_TIMEOUT = 120
STOP_TIMEOUT = 2


class QueueTransportError(ValueError):
    """The queue transport cannot deliver a message."""


class QueueTransportUnsupported(QueueTransportError):
    """The server rejected the queue method before it accepted a message."""


class QueueTransportAmbiguous(QueueTransportError):
    """The connection failed after a message write started."""


class _ServerError(Exception):
    def __init__(self, code, message, data):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


@dataclass
class _Pending:
    future: asyncio.Future
    can_deliver: bool


class CodexQueueTransport:
    """Send queue requests without taking ownership of a terminal thread.

    The installed Codex schema requires `thread/queue/add` with `threadId`,
    `input`, and `clientUserMessageId`. The client enables `experimentalApi`
    during initialize. This class never starts, resumes, steers, or interrupts
    a turn.
    """

    def __init__(self):
        self.process = None
        self.reader_task = None
        self.stderr_task = None
        self.pending = {}
        self.next_id = 1
        self.write_lock = asyncio.Lock()
        self.closed = False
        self.stderr = []

    async def start(self, cwd: str | None = None):
        """Start the proxy and initialize its experimental queue API."""
        if self.closed:
            raise QueueTransportError("The Codex queue transport is closed.")
        if self.process and self.process.returncode is None:
            return
        # A proxy that exited cannot deliver anything. Start a new one.
        await self._stop()
        binary = await asyncio.to_thread(find_command, "codex")
        if not binary:
            raise QueueTransportError("Codex could not be found.")
        try:
            self.process = await asyncio.create_subprocess_exec(
                binary,
                "app-server",
                "proxy",
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self.reader_task = asyncio.create_task(self._read_stdout())
            self.stderr_task = asyncio.create_task(self._read_stderr())
            await self._request(
                "initialize",
                {
                    "clientInfo": {"name": "TalkToMe", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
                INITIALIZE_TIMEOUT,
                can_deliver=False,
            )
            await self._notify("initialized")
        except _ServerError as error:
            await self.close()
            raise QueueTransportError(
                f"Codex did not initialize the queue transport. {error.message}"
            ) from None
        except BaseException:
            await self.close()
            raise

    async def send(self, thread_id: str, text: str, cwd: str | None = None) -> dict:
        """Queue one text message without starting or resuming a turn."""
        await self.start(cwd)
        message_id = str(uuid4())
        try:
            result = await self._request(
                "thread/queue/add",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": text}],
                    "clientUserMessageId": message_id,
                },
                QUEUE_TIMEOUT,
                can_deliver=True,
            )
        except _ServerError as error:
            if self._unsupported(error):
                await self.close()
                raise QueueTransportUnsupported(
                    "This Codex server does not support the queue method."
                ) from None
            raise QueueTransportError(
                f"Codex rejected the queued message. {error.message}"
            ) from None
        except TimeoutError:
            await self.close()
            raise QueueTransportAmbiguous(
                "Codex did not confirm the queued message. Its delivery is unknown."
            ) from None
        except QueueTransportAmbiguous:
            await self.close()
            raise
        except asyncio.CancelledError:
            await asyncio.shield(self.close())
            raise

        queued = result.get("queuedSubmission") if isinstance(result, dict) else None
        if not isinstance(queued, dict):
            await self.close()
            raise QueueTransportAmbiguous(
                "Codex returned an invalid queue response. Its delivery is unknown."
            )
        if queued.get("clientUserMessageId") != message_id or not queued.get("id"):
            await self.close()
            raise QueueTransportAmbiguous(
                "Codex returned an unmatched queue response. Its delivery is unknown."
            )
        return queued

    async def close(self):
        """Stop the proxy and release pending request waiters."""
        if self.closed:
            return
        self.closed = True
        await self._stop()

    async def _stop(self):
        for pending in self.pending.values():
            if not pending.future.done():
                pending.future.set_exception(QueueTransportError("The queue transport closed."))
        self.pending.clear()
        process = self.process
        self.process = None
        for task in (self.reader_task, self.stderr_task):
            if task:
                task.cancel()
        self.reader_task = None
        self.stderr_task = None
        if not process:
            return
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), STOP_TIMEOUT)
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), STOP_TIMEOUT)

    async def _request(self, method, params, timeout, *, can_deliver):
        if not self.process or not self.process.stdin:
            raise QueueTransportError("The Codex queue transport is not running.")
        request_id = self.next_id
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        pending = _Pending(future=future, can_deliver=can_deliver)
        self.pending[request_id] = pending
        request = {"id": request_id, "method": method, "params": params}
        try:
            async with self.write_lock:
                # A write can reach Codex before drain reports a broken pipe.
                self.process.stdin.write(json.dumps(request).encode() + b"\n")
                await self.process.stdin.drain()
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except TimeoutError:
            self.pending.pop(request_id, None)
            raise
        except (BrokenPipeError, ConnectionError, OSError) as error:
            self.pending.pop(request_id, None)
            if can_deliver:
                raise QueueTransportAmbiguous(
                    "The Codex connection failed. The message delivery is unknown."
                ) from error
            raise QueueTransportError("The Codex queue transport could not start.") from error
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def _notify(self, method):
        if not self.process or not self.process.stdin:
            raise QueueTransportError("The Codex queue transport is not running.")
        async with self.write_lock:
            self.process.stdin.write(json.dumps({"method": method}).encode() + b"\n")
            await self.process.stdin.drain()

    async def _read_stdout(self):
        try:
            while self.process and self.process.stdout:
                line = await self.process.stdout.readline()
                if not line:
                    break
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    self._fail_pending("Codex sent an invalid queue response.")
                    return
                request_id = response.get("id") if isinstance(response, dict) else None
                pending = self.pending.get(request_id)
                if not pending or pending.future.done():
                    continue
                if "error" in response:
                    error = response["error"]
                    if isinstance(error, dict):
                        pending.future.set_exception(
                            _ServerError(error.get("code"), error.get("message", "Codex error"), error.get("data"))
                        )
                    else:
                        pending.future.set_exception(_ServerError(None, "Codex error", None))
                elif "result" in response:
                    pending.future.set_result(response["result"])
                else:
                    self._fail_pending("Codex sent an invalid queue response.")
                    return
            self._fail_pending("The Codex queue connection closed.")
        except asyncio.CancelledError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            self._fail_pending("The Codex queue connection failed.", error)

    async def _read_stderr(self):
        while self.process and self.process.stderr:
            line = await self.process.stderr.readline()
            if not line:
                return
            self.stderr.append(line.decode(errors="replace").strip())
            if len(self.stderr) > 20:
                self.stderr.pop(0)

    def _fail_pending(self, message, error=None):
        for pending in self.pending.values():
            if pending.future.done():
                continue
            if pending.can_deliver:
                pending.future.set_exception(QueueTransportAmbiguous(f"{message} Delivery is unknown."))
            else:
                pending.future.set_exception(QueueTransportError(message))

    @staticmethod
    def _unsupported(error: _ServerError) -> bool:
        return error.code == -32601
