import asyncio
import io
import json
import os

from conftest import FakeApp

from talktome_server import hook, inbound, paths
from talktome_server.api import Client
from talktome_server.server import serve
from talktome_server.targets import discover


def claude_project(home, folder):
    folder.mkdir(parents=True, exist_ok=True)
    sessions = home / ".claude" / "projects" / "p"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "s.jsonl").write_text(json.dumps({"cwd": str(folder), "sessionId": "s1"}) + "\n")


async def targets_with(app, check):
    while True:
        found = (await app.next("targets"))["targets"]
        if check(found):
            return found


class EchoRunner:
    def __init__(self, world=None, ask=False):
        self.world, self.ask, self.call_id = world, ask, ""

    def bind_call(self, call_id, approver):
        self.call_id = call_id

    async def turn(self, text):
        if self.ask:
            result = await self.world.post(
                "/v1/permission", {"call_id": self.call_id, "tool": "Bash", "input": {"command": "date"}}, 150
            )
            if not result["allow"]:
                return "I did not run it. " + result.get("message", "")
        return f"You said **{text}**"


def hook_output(host, given):
    out = io.StringIO()
    hook.run(host, stdin=io.StringIO(json.dumps(given)), stdout=out)
    return json.loads(out.getvalue()) if out.getvalue() else None


async def run_hook(host, **given):
    return await asyncio.to_thread(hook_output, host, given)


async def test_a_call_into_a_project_runs_the_host_and_speaks_the_reply(world):
    app = world.app
    project = world.home / "code" / "app"
    claude_project(world.home, project)
    world.runners["make"] = lambda host, folder, mode, session: EchoRunner()
    app.send("call.incoming", call_id="c1", target_id="nope", mode="new")
    rejected = await app.next("call.reject")
    assert rejected["call_id"] == "c1"

    world_targets = discover(world.home)
    app.send("call.incoming", call_id="c2", target_id=world_targets[0].id, mode="continue")
    await app.next("call.accept")
    app.send("turn.user", call_id="c2", turn_id="t1", text="hello")
    reply = await app.next("turn.agent")
    assert (reply["turn_id"], reply["text"], reply["final"]) == ("t1", "You said hello", True)


async def test_a_permission_question_is_asked_in_the_call(world):
    app = world.app
    claude_project(world.home, world.home / "code" / "app")
    world.runners["make"] = lambda *a: EchoRunner(world, ask=True)
    app.send("call.incoming", call_id="c1", target_id=discover(world.home)[0].id, mode="new")
    await app.next("call.accept")
    app.send("turn.user", call_id="c1", turn_id="t1", text="What time is it?")
    question = await app.next("turn.agent")
    assert question["text"] == "Claude wants to run the command: date. Should I allow it?"
    app.send("turn.user", call_id="c1", turn_id="t2", text="No, don't.")
    answer = await app.next("turn.agent")
    assert answer["turn_id"] == "t2"
    assert answer["text"] == "I did not run it. The user said no in the voice call."


async def test_a_call_joins_an_open_session_through_the_hooks(world):
    app = world.app
    project = world.home / "code" / "site"
    project.mkdir(parents=True)
    base = {"session_id": "open1", "cwd": str(project)}
    assert await run_hook("claude", hook_event_name="SessionStart", **base) is None
    await run_hook("claude", hook_event_name="UserPromptSubmit", **base)
    found = await targets_with(app, lambda ts: any(t["joinable"] for t in ts))
    target = next(t for t in found if t["joinable"])
    assert target["project"] == "site (open session)"

    app.send("call.incoming", call_id="c1", target_id=target["target_id"], mode="join")
    await app.next("call.accept")

    # While the agent works, the user's words come back after its next tool call.
    app.send("turn.user", call_id="c1", turn_id="t1", text="Skip the docs.")
    passed = await app.next("turn.agent")
    assert (passed["text"], passed["final"]) == ("I'll pass that on.", False)
    context = await run_hook("claude", hook_event_name="PostToolUse", **base)
    assert '"Skip the docs."' in context["hookSpecificOutput"]["additionalContext"]

    # A tool that needs permission is asked about in the call.
    asking = asyncio.create_task(
        run_hook(
            "claude",
            hook_event_name="PermissionRequest",
            tool_name="Write",
            tool_input={"file_path": "/x/notes.txt"},
            **base,
        )
    )
    question = await app.next("turn.agent")
    assert question["text"] == "Claude wants to change the file notes.txt. Should I allow it?"
    app.send("turn.user", call_id="c1", turn_id="t2", text="Yes, go ahead.")
    allowed = await asking
    assert allowed["hookSpecificOutput"]["decision"] == {"behavior": "allow"}

    # At the end of its turn, the last message is spoken, and the Stop hook
    # waits for the user's next words.
    stopping = asyncio.create_task(
        run_hook("claude", hook_event_name="Stop", last_assistant_message="Done. **Tests pass.**", **base)
    )
    spoken = await app.next("turn.agent")
    assert (spoken["text"], spoken["turn_id"], spoken["final"]) == ("Done. Tests pass.", "t2", True)
    app.send("turn.user", call_id="c1", turn_id="t3", text="Now commit it.")
    blocked = await stopping
    assert blocked["decision"] == "block" and '"Now commit it."' in blocked["reason"]

    # After the user hangs up, the next Stop lets the agent finish.
    stopping = asyncio.create_task(
        run_hook("claude", hook_event_name="Stop", last_assistant_message="Committed.", **base)
    )
    await app.next("turn.agent")
    app.send("call.ended", call_id="c1", reason="hung up", by="device")
    assert await asyncio.wait_for(stopping, 5) is None


async def test_a_question_in_a_joined_call_stops_when_the_call_ends(world):
    app = world.app
    project = world.home / "code" / "api"
    project.mkdir(parents=True)
    base = {"session_id": "open2", "cwd": str(project)}
    await run_hook("codex", hook_event_name="SessionStart", **base)
    await run_hook("codex", hook_event_name="UserPromptSubmit", **base)
    found = await targets_with(app, lambda ts: any(t["joinable"] for t in ts))
    app.send("call.incoming", call_id="c1", target_id=found[0]["target_id"], mode="join")
    await app.next("call.accept")
    asking = asyncio.create_task(
        run_hook(
            "codex",
            hook_event_name="PermissionRequest",
            tool_name="Bash",
            tool_input={"command": ["git", "push"]},
            **base,
        )
    )
    question = await app.next("turn.agent")
    assert question["text"] == "Codex wants to run the command: git push. Should I allow it?"
    app.send("call.ended", call_id="c1", reason="hung up", by="device")
    assert await asyncio.wait_for(asking, 5) is None


async def test_a_hook_with_no_server_is_silent(monkeypatch, tmp_path):
    monkeypatch.setenv("TALKTOME_DIR", str(tmp_path))
    assert await run_hook("claude", hook_event_name="Stop", session_id="s", cwd="/") is None
    monkeypatch.setenv("TALKTOME_CALL_RUN", "1")
    assert await run_hook("claude", hook_event_name="Stop", session_id="s", cwd="/") is None


async def test_a_new_server_takes_over_from_a_running_one(world):
    second = FakeApp()
    task = asyncio.create_task(serve(second.link, home=world.home, socket_path=paths.socket_path()))
    await second.next("hello")
    status = await asyncio.to_thread(Client(paths.socket_path()).request, "GET", "/v1/status")
    assert status["connected"] is True
    assert os.path.exists(paths.socket_path())
    second.close()
    await asyncio.gather(task, return_exceptions=True)


def test_spoken_answers_and_tool_descriptions():
    assert inbound.is_yes("Yes, go ahead.") and inbound.is_yes("sure")
    assert not inbound.is_yes("No, don't.") and not inbound.is_yes("Wait, what is it?") and not inbound.is_yes("Hmm.")
    assert inbound.describe("mcp__github__create_pr", {}) == "use the create pr tool"
    assert inbound.describe("WebFetch", {}) == "open a web page"
    assert inbound.describe("Bash", '{"command": "npm   test"}') == "run the command: npm test"
