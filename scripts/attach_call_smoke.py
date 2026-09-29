"""Prove the whole attachment loop against a real Codex session.

Everything here is real: a real Codex app server holds a real thread, the real
`talktome call` command rings the app, the app delivers the user's speech with
`codex queue`, and the agent's answer is read back out of the thread's rollout file
and spoken.

This is the check that matters for attachment, because every part of it is a place
where an assumption could be wrong in a way that fails silently: the queue command
might not reach a held thread, the rollout might not be where it is expected, and
the records in it might not be shaped the way they were read.

It sends a few short model requests and can incur agent service charges.

    npm run test:attach-call
"""

import argparse
import asyncio
import contextlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import attach_smoke

SPEECH = 90

# The command under test. The checkout's entry point is the default, but a built
# bundle serves the same command from a single binary with no interpreter inside it,
# and that is the copy an agent actually runs. Pointing this at one is the only way
# to test the packaged path without installing it:
#
#   TALKTOME_COMMAND="/Applications/TalkToMe.app/Contents/Resources/talktome-server/talktome-server -m talktome" \
#     npm run test:attach-call
COMMAND = shlex.split(
    os.environ.get("TALKTOME_COMMAND") or str(ROOT / ".venv" / "bin" / "talktome")
)


async def wait_for_health(client, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(httpx.RequestError):
            if (await client.get("/v1/health")).status_code == 200:
                return
        await asyncio.sleep(0.25)
    raise RuntimeError("The local server did not start.")


async def wait_for_state(client, predicate, timeout=SPEECH):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(httpx.RequestError):
            state = (await client.get("/v1/state")).json()
            if predicate(state):
                return state
        await asyncio.sleep(0.3)
    return None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep the temporary folder")
    args = parser.parse_args()

    report = []

    def record(name, ok, detail=""):
        report.append((name, bool(ok), str(detail)))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} {detail}", flush=True)

    workdir = Path(tempfile.mkdtemp(prefix="talktome-attach-call-"))
    directory = Path(tempfile.mkdtemp(prefix="talktome-attach-data-"))
    (directory / "settings.json").write_text("{}")
    port = 8801 + (os.getpid() % 400)
    origin = f"http://127.0.0.1:{port}"
    server = None
    app = None
    try:
        # The app's own server, headless. Electron is not needed for this path.
        app = subprocess.Popen(  # noqa: ASYNC220 - a sequential smoke test, not a server.
            [
                str(ROOT / ".venv" / "bin" / "python"),
                "-m",
                "talktome",
                "serve",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "TALKTOME_DATA_DIR": str(directory),
                "TALKTOME_URL": origin,
                "PYTHONUNBUFFERED": "1",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        token = (directory / "token").read_text().strip() if (directory / "token").exists() else ""
        async with httpx.AsyncClient(base_url=origin, timeout=60) as client:
            await wait_for_health(client)
            token = (directory / "token").read_text().strip()
            client.headers["Authorization"] = f"Bearer {token}"

            # A terminal session, held open exactly as a user's terminal would hold it.
            server = attach_smoke.AppServer(str(workdir))
            await server.start()
            thread = await server.request(
                "thread/start",
                {"cwd": str(workdir), "approvalPolicy": "never", "sandbox": "read-only"},
            )
            thread_id = thread["thread"]["id"]
            warm, _, _, _ = await attach_smoke.run_turn(
                server, thread_id, "Reply with exactly: READY"
            )
            record(
                "a Codex session exists and has answered", "READY" in warm.upper(), repr(warm[:40])
            )

            # The agent rings in, exactly as the skill instructs it to.
            rung = subprocess.run(  # noqa: ASYNC221, PLW1510 - the exit code is the result.
                [
                    *COMMAND,
                    "call",
                    "--thread",
                    thread_id,
                    "--cwd",
                    str(workdir),
                    "--greeting",
                    "Hey, I am here. What do you need?",
                    "--name",
                    "Attach test",
                    # This part of the test answers the ring itself, so it must not
                    # sit waiting for that answer.
                    "--no-wait",
                ],
                cwd=ROOT,
                env={**os.environ, "TALKTOME_DATA_DIR": str(directory), "TALKTOME_URL": origin},
                capture_output=True,
                text=True,
                timeout=90,
            )
            record("talktome call rings the app", rung.returncode == 0, rung.stderr.strip()[:60])

            state = (await client.get("/v1/state")).json()
            record(
                "ringing asks before it connects",
                state["managed"]["status"] == "ringing" and not state["room"]["call_id"],
                f"status={state['managed']['status']} call={bool(state['room']['call_id'])}",
            )
            record(
                "the ring says who is calling",
                (state["managed"].get("ring") or {}).get("name") == "Attach test",
                repr((state["managed"].get("ring") or {}).get("name")),
            )
            record(
                "nothing is said until it is answered",
                not state["room"]["messages"],
                f"{len(state['room']['messages'])} message(s)",
            )

            # The user answers, which is when the greeting is heard.
            answered = (await client.post("/v1/attach/accept", json={})).json()
            call_id = (
                answered["session_id"] and (await client.get("/v1/state")).json()["room"]["call_id"]
            )
            record("answering opens the call", bool(call_id), call_id or "no call")
            state = (await client.get("/v1/state")).json()
            texts = [m["text"] for m in state["room"]["messages"]]
            record(
                "the agent's own greeting is the first thing in it",
                bool(texts) and texts[0] == "Hey, I am here. What do you need?",
                repr(texts[0][:44]) if texts else "nothing",
            )
            greeting_audio = None
            for _ in range(60):
                events = (await client.get("/v1/events", params={"after": 0, "timeout": 0})).json()
                greeting_audio = next(
                    (
                        event
                        for event in events["events"]
                        if event["type"] == "agent.audio" and event.get("kind") == "greeting"
                    ),
                    None,
                )
                if greeting_audio:
                    break
                await asyncio.sleep(0.2)
            record("the greeting has a playable audio event", greeting_audio is not None)

            # The user speaks. The app cannot start a turn, so this has to travel
            # through `codex queue` into the thread the app server is holding.
            await client.post(
                "/v1/call/text",
                json={"call_id": call_id, "text": "Reply with exactly: BANANA"},
            )
            after = await wait_for_state(
                client,
                lambda s: any(
                    m["role"] == "agent" and "BANANA" in m["text"].upper()
                    for m in s["room"]["messages"]
                ),
            )
            agent_text = ""
            if after:
                agent_text = [
                    m["text"]
                    for m in after["room"]["messages"]
                    if m["role"] == "agent" and "BANANA" in m["text"].upper()
                ][-1]
            record(
                "speech reaches the session and the answer comes back",
                bool(agent_text),
                repr(agent_text[:50]) if agent_text else "no reply within the wait",
            )

            if after:
                spoken = [m for m in after["room"]["messages"] if m["role"] == "agent"]
                record(
                    "the answer is in the transcript to be spoken",
                    len(spoken) >= 2,
                    f"{len(spoken)} agent message(s)",
                )
                timing = after["room"].get("timing") or {}
                queued = timing.get("queued_ms")
                message = timing.get("first_message_ms")
                record(
                    "the real call marks the queue and first message",
                    bool(queued and message and message >= queued),
                    f"{message - queued:.0f} ms" if queued and message else "no marks",
                )

            # The previous call has to be gone before another can ring: one at a
            # time is the whole design.
            await client.post("/v1/hangup", json={})
            await asyncio.sleep(1)

            # And the waiting form: the command reports what happened to the ring
            # rather than leaving the agent to guess between an unanswered call and
            # one happening quietly.
            waiting = subprocess.Popen(  # noqa: ASYNC220 - a sequential smoke test.
                [
                    *COMMAND,
                    "call",
                    "--thread",
                    thread_id,
                    "--cwd",
                    str(workdir),
                    "--name",
                    "Wait test",
                ],
                cwd=ROOT,
                env={**os.environ, "TALKTOME_DATA_DIR": str(directory), "TALKTOME_URL": origin},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            await asyncio.sleep(2)
            await client.post("/v1/attach/accept", json={})
            out, errors = waiting.communicate(timeout=60)
            record(
                "the command reports that the call was answered",
                '"answered": true' in out,
                (out.strip().splitlines()[-1][:44] if out.strip() else errors.strip()[:60])
                or "no output",
            )
            await client.post("/v1/hangup", json={})

            # The terminal ends it, with no call identifier to look up first.
            ended = subprocess.run(  # noqa: ASYNC221, PLW1510 - the exit code is the result.
                [*COMMAND, "end"],
                cwd=ROOT,
                env={**os.environ, "TALKTOME_DATA_DIR": str(directory), "TALKTOME_URL": origin},
                capture_output=True,
                text=True,
                timeout=90,
            )
            record(
                "talktome end hangs up from the terminal",
                ended.returncode == 0,
                ended.stderr.strip()[:60],
            )
            try:
                thread_after = await server.request("thread/read", {"threadId": thread_id})
                alive = bool(thread_after.get("thread") or thread_after.get("turns"))
            except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise.
                alive = False
                record("the session survives the call", False, str(exc)[:60])
            else:
                record("the session survives the call", alive, f"{thread_id[:8]}…")
    finally:
        if server:
            with contextlib.suppress(Exception):
                await server.close()
        if app:
            app.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                app.wait(timeout=10)
            if app.poll() is None:
                app.kill()
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)
            shutil.rmtree(directory, ignore_errors=True)

    passed = sum(1 for _, ok, _ in report if ok)
    print(f"\n{passed}/{len(report)} checks passed")
    if args.keep:
        print(f"kept {workdir}")
    return 0 if passed == len(report) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
