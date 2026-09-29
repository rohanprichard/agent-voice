"""Map what a second process can do with a Codex thread it did not create.

This is the bounded experiment for session attachment. Codex refuses to let two
connections write one thread, so the questions are: what still works while
another process holds a thread, and what works only once it is released?

It answers:

  1. Can a second process list threads and find one by project folder?
  2. Can it read a thread's history while another process holds it?
  3. Can it resume a thread while another process holds it?
  4. Can `codex queue` deliver a message into a held thread?
  5. Does a reply appear in the thread's rollout file?
  6. Can it resume the thread once the first process releases it?
  7. Can the agent see its own thread identifier, so a skill can hand it over?

It sends a few short model requests and can incur agent service charges.

    uv run python scripts/attach_smoke.py
"""

import argparse
import asyncio
import contextlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

TIMEOUT = 240
FIXTURE = "The launch code is ORCHID-7.\n"


class AppServer:
    """A minimal client for the Codex app server's JSON-RPC over stdio."""

    def __init__(self, cwd):
        self.cwd = cwd
        self.process = None
        self.next_id = 0
        self.pending = {}
        self.events = asyncio.Queue()
        self.reader = None
        self.methods = []
        self.errors = []
        self.item_types = set()

    async def start(self):
        binary = shutil.which("codex")
        if not binary:
            raise RuntimeError("Codex is not on PATH. Install it and sign in first.")
        self.process = await asyncio.create_subprocess_exec(
            binary,
            "app-server",
            cwd=self.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=8 * 1024 * 1024,
        )
        self.reader = asyncio.create_task(self._read())
        await self.request(
            "initialize",
            {
                "clientInfo": {"name": "talktome-attach-smoke", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.write({"method": "initialized"})

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "id" in message and "method" in message:
                    await self.events.put(message)
                    await self.write({"id": message["id"], "result": {"decision": "decline"}})
                elif "method" in message:
                    await self.events.put(message)
                elif (future := self.pending.pop(message.get("id"), None)) and not future.done():
                    if "error" in message:
                        future.set_exception(
                            RuntimeError(message["error"].get("message", "failed"))
                        )
                    else:
                        future.set_result(message.get("result", {}))
        except (ValueError, OSError) as error:
            await self.events.put({"method": "host/error", "params": {"message": str(error)}})
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("The app server stopped."))
            await self.events.put({"method": "host/closed", "params": {}})

    async def write(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.write({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, TIMEOUT)
        finally:
            self.pending.pop(request_id, None)

    async def close(self):
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader
        if self.process and self.process.returncode is None:
            self.process.terminate()
            with contextlib.suppress(ProcessLookupError, asyncio.TimeoutError):
                await asyncio.wait_for(self.process.wait(), 10)


async def collect(server, timeout):
    """Drain notifications until a turn completes or the deadline passes."""
    chunks = []
    first_delta = None
    started = time.monotonic()
    while True:
        try:
            note = await asyncio.wait_for(server.events.get(), timeout)
        except TimeoutError:
            return "".join(chunks).strip(), first_delta, time.monotonic() - started, False
        method = note.get("method", "")
        params = note.get("params", {}) or {}
        server.methods.append(method)
        if method == "host/error":
            raise RuntimeError(params.get("message", "host error"))
        delta = params.get("delta")
        if isinstance(delta, str) and "agentmessage" in method.lower():
            if first_delta is None:
                first_delta = time.monotonic() - started
            chunks.append(delta)
        if method == "error":
            server.errors.append(params)
        item = params.get("item") or {}
        if item.get("type"):
            server.item_types.add(str(item["type"]))
        if method == "item/completed" and str(item.get("type", "")).startswith("agent"):
            text = item.get("text") or ""
            if text and not chunks:
                chunks.append(text)
        if method == "turn/completed":
            return "".join(chunks).strip(), first_delta, time.monotonic() - started, True


async def run_turn(server, thread_id, text):
    await server.request(
        "turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": text}]}
    )
    return await collect(server, TIMEOUT)


def rollout_for(thread_id):
    root = Path.home() / ".codex" / "sessions"
    if not root.is_dir():
        return None
    matches = sorted(root.rglob(f"*{thread_id}*.jsonl"))
    return matches[-1] if matches else None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=None, help="Model identifier. The host default is used when omitted."
    )
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="talktome-attach-"))
    (workdir / "notes.txt").write_text(FIXTURE)
    report = []

    def record(name, ok, detail=""):
        report.append((name, bool(ok), str(detail)))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:44s} {detail}", flush=True)

    server = AppServer(str(workdir))
    thread_id = None
    try:
        await server.start()
        started = await server.request(
            "thread/start",
            {
                "cwd": str(workdir),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "developerInstructions": "Answer in as few words as possible.",
                **({"model": args.model} if args.model else {}),
            },
        )
        thread_id = started["thread"]["id"]
        print(f"\nthread {thread_id}\n")

        text, _, total, done = await run_turn(
            server, thread_id, "Remember the word ORCHID. Reply: ok"
        )
        detail = f"{text!r} in {total:.1f}s"
        if not text:
            detail += f" | errors={json.dumps(server.errors[:2])[:200]}"
            detail += f" | items={sorted(server.item_types)}"
        record("push a turn into a new thread", done and bool(text), detail)

        text2, _, _, _ = await run_turn(server, thread_id, "What is the word? Reply with just it.")
        record("the thread keeps context", "ORCHID" in text2.upper(), repr(text2))

        text3, _, _, _ = await run_turn(
            server,
            thread_id,
            "Run the shell command: echo $CODEX_THREAD_ID   Then reply with its exact output.",
        )
        record(
            "the agent sees its own thread id",
            thread_id in text3 or thread_id[:8] in text3,
            repr(text3.strip()[:70]),
        )

        listing = await server.request(
            "thread/list", {"cwd": str(workdir), "limit": 10, "useStateDbOnly": False}
        )
        ids = [entry.get("id") or entry.get("threadId") for entry in listing.get("data", [])]
        record("thread/list finds it by folder", thread_id in ids, f"{len(ids)} thread(s)")

        # Everything below happens while this connection still holds the thread.
        try:
            read = await server.request("thread/read", {"threadId": thread_id})
            turns = (read.get("thread") or {}).get("turns") or read.get("turns") or []
            record("read history from the holding connection", bool(turns), f"{len(turns)} turn(s)")
        except Exception as error:  # noqa: BLE001 - a smoke test reports failures, it does not raise them.
            record("read history from the holding connection", False, error)

        second = AppServer(str(workdir))
        try:
            await second.start()
            try:
                await second.request(
                    "thread/resume",
                    {
                        "threadId": thread_id,
                        "cwd": str(workdir),
                        "approvalPolicy": "never",
                        "sandbox": "read-only",
                    },
                )
                record("resume while another process holds it", True, "accepted")
            except Exception as error:  # noqa: BLE001 - a smoke test reports failures, it does not raise them.
                record("resume while another process holds it", False, error)
        finally:
            await second.close()

        # Push without becoming a writer, using the documented CLI.
        binary = shutil.which("codex")
        queued = await asyncio.create_subprocess_exec(
            binary,
            "queue",
            "--thread",
            thread_id,
            "--message",
            "What is the word? Reply with just it.",
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(queued.communicate(), 120)
        record(
            "codex queue accepted the message", queued.returncode == 0, out.decode().strip()[:70]
        )

        text4, _, _, delivered = await collect(server, 180)
        record(
            "the held connection saw the queued turn",
            delivered and "ORCHID" in text4.upper(),
            repr(text4[:60]),
        )

        path = rollout_for(thread_id)
        if path:
            body = path.read_text(errors="replace")
            record("the rollout file has the conversation", "ORCHID" in body, path.name[:52])
        else:
            record("the rollout file has the conversation", False, "no rollout file found")
    finally:
        await server.close()
        shutil.rmtree(workdir, ignore_errors=True)

    if thread_id:
        third = AppServer(str(Path.home()))
        try:
            await third.start()
            try:
                resumed = await third.request(
                    "thread/resume",
                    {
                        "threadId": thread_id,
                        "approvalPolicy": "never",
                        "sandbox": "read-only",
                    },
                )
                found = (resumed.get("thread") or {}).get("id") or resumed.get("threadId")
                record("resume after the writer released it", found == thread_id, str(found))
                text5, _, _, _ = await run_turn(
                    third, thread_id, "What is the word? Reply with just it."
                )
                record(
                    "the resumed thread still had context", "ORCHID" in text5.upper(), repr(text5)
                )
            except Exception as error:  # noqa: BLE001 - a smoke test reports failures, it does not raise them.
                record("resume after the writer released it", False, error)
        finally:
            await third.close()

    passed = sum(1 for _, ok, _ in report if ok)
    print(f"\n{passed}/{len(report)} checks passed")
    print("notification methods seen:", ", ".join(sorted(set(server.methods))) or "none")
    return 0 if passed == len(report) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
