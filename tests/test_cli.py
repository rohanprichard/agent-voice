"""The command an agent runs to ring the app.

Two things are worth testing here and both were learned the hard way. The command
must report what actually happened, because a call that starts while the command
reports failure makes the agent tell the user it did not work when it did. And the
command must not start a second copy of the app: the version that asked the network
whether the app was up started one on every sandboxed run, and the user read about a
port collision instead of hearing a ring.
"""

import httpx
import pytest

from talktome import cli, inbox


def answering(monkeypatch, result=None, error=None, seen=None):
    """Stand in for an app that is up and answering its inbox."""
    original = inbox.ask

    def ask(command, payload=None, root=None):
        if seen is not None:
            seen.update({"command": command, "payload": payload})
        request = original(command, payload, root=root)
        inbox.answer(request, result=result, error=error)
        return request

    monkeypatch.setattr(inbox, "ask", ask)
    monkeypatch.setattr(cli, "wake", lambda *a, **k: True)


def silent(monkeypatch):
    """Stand in for an app that is up but never answers."""
    monkeypatch.setattr(inbox, "reply_for", lambda request: None)
    monkeypatch.setattr(cli, "wake", lambda *a, **k: True)
    # Waited out rather than slept through: the point of these tests is what the
    # command says when nothing comes back, not how long it is willing to wait.
    monkeypatch.setattr(cli, "REQUEST_TIMEOUT", 0)


def test_a_started_call_returns_what_the_app_reported(monkeypatch):
    answering(monkeypatch, result={"status": "ready", "session_id": "t-1"})
    assert cli.call("t-1", "hello", "/tmp/project") == {"status": "ready", "session_id": "t-1"}


def test_the_call_carries_the_session_and_the_greeting(monkeypatch):
    seen = {}
    answering(monkeypatch, result={}, seen=seen)
    cli.call("t-1", "hey", "/tmp/project")
    assert seen == {
        "command": "call",
        "payload": {
            "thread": "t-1",
            "cwd": "/tmp/project",
            "greeting": "hey",
            "name": None,
            "wait": True,
            "agent": "codex",
            "connection": "auto",
        },
    }


def test_the_caller_name_is_sent_so_the_ring_can_say_who_it_is(monkeypatch):
    seen = {}
    answering(monkeypatch, result={}, seen=seen)
    cli.call("t-1", "hey", "/tmp/project", "Auth refactor")
    assert seen["payload"]["name"] == "Auth refactor"


def test_not_waiting_is_asked_for_at_the_far_end(monkeypatch):
    # The app is the side that can see the ring, so "do not wait" has to travel
    # with the request rather than being something this side decides alone.
    seen = {}
    answering(monkeypatch, result={}, seen=seen)
    assert "answered" not in cli.call("t-1", "hi", "/tmp", wait=False)
    assert seen["payload"]["wait"] is False


def test_a_refused_call_repeats_the_reason(monkeypatch):
    answering(monkeypatch, error="That session has no transcript yet.")
    with pytest.raises(ValueError) as error:
        cli.call("t-1", None, "/tmp")
    assert "no transcript yet" in str(error.value)


def test_a_refusal_without_a_reason_is_still_readable(monkeypatch):
    answering(monkeypatch, error="")
    with pytest.raises(ValueError) as error:
        cli.call("t-1", None, "/tmp")
    assert "refused" in str(error.value)


def test_the_command_reports_whether_anyone_answered(monkeypatch):
    # Without it the agent cannot tell a call nobody answered from one happening
    # quietly, so it cannot tell the user which of the two occurred.
    answering(monkeypatch, result={"status": "ringing", "answered": True})
    assert cli.call("t-1", "hi", "/tmp")["answered"] is True


def test_ending_a_call_needs_no_identifier(monkeypatch):
    # A terminal has no call id to hand, and looking one up first is the
    # difference between a command someone uses and one they do not.
    monkeypatch.setattr(cli, "server_up", lambda: True)
    seen = {}
    answering(monkeypatch, result={"status": "idle"}, seen=seen)
    assert cli.end() == {"status": "idle"}
    assert seen["command"] == "end"


def test_ending_while_the_app_is_closed_does_nothing_quietly(monkeypatch):
    # A call cannot exist without the app, so starting a sleeping one to end a
    # call it cannot be holding would be theatre.
    monkeypatch.setattr(cli, "server_up", lambda: False)
    monkeypatch.setattr(cli, "running", lambda *a, **k: False)

    def refuse(*args, **kwargs):
        raise AssertionError("ending a call must not wake the app")

    monkeypatch.setattr(cli, "ask", refuse)
    assert cli.end() == {"status": "idle"}


def test_a_request_is_left_before_the_app_is_started(monkeypatch):
    # The app reads its inbox as it comes up, so a command that has to wake a
    # sleeping app must not be waiting on a health check to be heard.
    order = []
    original = inbox.ask

    def ask(command, payload=None, root=None):
        order.append("ask")
        return original(command, payload, root=root)

    monkeypatch.setattr(inbox, "ask", ask)
    monkeypatch.setattr(
        inbox, "reply_for", lambda request_id, root=None: {"ok": True, "result": {}}
    )
    monkeypatch.setattr(cli, "wake", lambda *a, **k: (order.append("wake"), True)[1])
    cli.call("t-1", "hey", "/tmp")
    assert order == ["ask", "wake"]


@pytest.mark.parametrize("reply", [{"ok": True, "result": {}}, None])
def test_a_request_is_cleaned_up_whether_it_worked_or_not(monkeypatch, reply):
    # A request left behind would ring the user the next time the app opened, for
    # a command that finished long ago.
    collected = []
    monkeypatch.setattr(inbox, "ask", lambda command, payload=None, root=None: "r-1")
    monkeypatch.setattr(
        inbox, "collect", lambda request_id, root=None: collected.append(request_id)
    )
    monkeypatch.setattr(inbox, "reply_for", lambda request_id, root=None: reply)
    monkeypatch.setattr(cli, "wake", lambda *a, **k: True)
    if reply is None:
        with pytest.raises(ValueError):
            cli.ask("call", {}, timeout=0, sleep=lambda _: None)
    else:
        cli.ask("call", {})
    assert collected == ["r-1"]


# ------------------------------------------------- waking a sleeping app


def test_an_agent_can_start_the_app_when_it_is_closed(monkeypatch):
    # The user should not have to know the app is closed before asking their agent
    # to talk to them.
    started = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kwargs: started.append(argv))
    answered = iter([False, True])
    assert cli.wake(
        "/Applications/TalkToMe.app",
        sleep=lambda _: None,
        check=lambda: next(answered),
        up=lambda: False,
    )
    assert started == [["/Applications/TalkToMe.app"]]


def test_an_app_that_is_already_up_is_never_started_a_second_time(monkeypatch):
    # This is the bug the user hit. A sandboxed command got no answer from a
    # running app, concluded it was closed, started a second copy, and the second
    # copy found the port taken. Whatever the network says, a live server process
    # means there is nothing to start.
    def refuse(argv, **kwargs):
        raise AssertionError("a second copy must not be started")

    monkeypatch.setattr(cli.subprocess, "Popen", refuse)
    assert cli.wake("/app", sleep=lambda _: None, check=lambda: False, up=lambda: True) is True


def test_an_unreachable_app_is_still_started(monkeypatch):
    # The lock decides, not the health check. A sandboxed command cannot reach the
    # app even when it is up, so the two answers disagree and the launcher is what
    # the command falls back on.
    started = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kwargs: started.append(argv))
    cli.wake("/app", timeout=0, sleep=lambda _: None, check=lambda: False, up=lambda: False)
    assert started == [["/app"]]


def test_the_app_is_started_detached_and_without_focus(monkeypatch):
    # Detached so it outlives the command, and without focus because the ring is
    # what asks for attention, not a window appearing over the user's work.
    import subprocess as real
    from unittest import mock

    seen = {}

    def popen(argv, **kwargs):
        seen.update(kwargs)

    with mock.patch.object(cli.subprocess, "Popen", popen):
        cli.wake(
            "open -g -b app.talktome",
            sleep=lambda _: None,
            check=lambda: True,
            up=lambda: False,
        )
    assert seen["start_new_session"] is True
    assert seen["stdout"] is real.DEVNULL


def test_a_launcher_is_read_from_the_environment_the_app_wrote(monkeypatch):
    monkeypatch.setenv("TALKTOME_LAUNCH", "/path/to/Electron /path/to/repo")
    started = []
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kwargs: started.append(argv))
    cli.wake(sleep=lambda _: None, check=lambda: True, up=lambda: False)
    assert started == [["/path/to/Electron", "/path/to/repo"]]


def test_without_a_known_launcher_it_does_not_pretend_to_have_tried(monkeypatch):
    monkeypatch.delenv("TALKTOME_LAUNCH", raising=False)
    assert cli.wake(sleep=lambda _: None, check=lambda: True, up=lambda: False) is False


def test_a_launcher_is_not_used_when_the_app_is_already_up(monkeypatch):
    # Checked before the launcher is even looked for, so a missing launcher can
    # never turn a running app into a refusal.
    monkeypatch.delenv("TALKTOME_LAUNCH", raising=False)
    assert cli.wake(sleep=lambda _: None, check=lambda: False, up=lambda: True) is True


def test_waking_gives_up_rather_than_hanging(monkeypatch):
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kwargs: None)
    assert (
        cli.wake("/app", timeout=0, sleep=lambda _: None, check=lambda: False, up=lambda: False)
        is False
    )


def test_an_app_that_cannot_be_started_says_what_to_do(monkeypatch):
    silent(monkeypatch)
    monkeypatch.setattr(cli, "wake", lambda *a, **k: False)
    with pytest.raises(ValueError) as error:
        cli.call("t-1", "hello", "/tmp")
    assert "could not start it" in str(error.value)


def test_an_agent_is_not_told_to_ask_for_network_access_any_more(monkeypatch):
    # The old message sent the agent off to ask for a permission that does not
    # exist, and the user approved it twice for no effect. There is nothing to
    # grant: what the command leaves is a file.
    silent(monkeypatch)
    monkeypatch.setattr(cli, "wake", lambda *a, **k: False)
    with pytest.raises(ValueError) as error:
        cli.call("t-1", "hello", "/tmp")
    assert "network" not in str(error.value)


def test_an_app_that_does_not_read_its_inbox_says_how_to_fix_it(monkeypatch):
    # The app is up, so no second one is started, and nothing is coming back. The
    # only useful thing to say is that the app is older than the command.
    silent(monkeypatch)
    with pytest.raises(ValueError) as error:
        cli.call("t-1", "hello", "/tmp")
    assert "did not answer" in str(error.value)
    assert "Restart the desktop app" in str(error.value)


# ------------------------------------------------- the health check, as a fallback


def test_the_health_check_is_still_asked(monkeypatch):
    # A platform without `fcntl` has no lock to read, and falls back to asking
    # over the loopback interface as it did before.
    monkeypatch.setattr(cli.httpx, "get", lambda *a, **k: httpx.Response(200, json={}))
    assert cli.running() is True


def test_a_refused_connection_is_not_treated_as_an_app(monkeypatch):
    def get(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(cli.httpx, "get", get)
    assert cli.running() is False
