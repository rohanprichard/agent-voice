"""Reading a thread that another process owns.

The record shapes here were taken from real rollout files rather than from
documentation, because the rollout format is the only view of a held thread and an
assumption about it fails silently: a call would simply never speak.
"""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from talktome import attach


def record(**payload):
    return {"type": "event_msg", "payload": payload}


def item_completed(item):
    return record(type="item_completed", thread_id="t-1", turn_id="turn-1", item=item)


def agent_message(text, phase="commentary", item_id="msg-1"):
    return item_completed(
        {
            "type": "AgentMessage",
            "id": item_id,
            "content": [{"type": "Text", "text": text}],
            "phase": phase,
        }
    )


def queued_user_message(text="hello"):
    return item_completed(
        {"type": "UserMessage", "id": "queued-1", "content": [{"type": "text", "text": text}]}
    )


def rollout_file(tmp_path, name="rollout-2026-09-24T10-00-00-abc.jsonl"):
    directory = tmp_path / ".codex" / "sessions" / "2026" / "09" / "24"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / name


def write(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


# --------------------------------------------------------------- finding it


def test_the_newest_rollout_for_a_thread_is_found(tmp_path):
    older = rollout_file(tmp_path, "rollout-2026-09-24T09-00-00-thread-9.jsonl")
    newer = rollout_file(tmp_path, "rollout-2026-09-24T10-00-00-thread-9.jsonl")
    write(older, [agent_message("old")])
    write(newer, [agent_message("new")])
    assert attach.rollout_path("thread-9", tmp_path / ".codex" / "sessions") == newer


def test_a_thread_with_no_rollout_yet_reports_nothing(tmp_path):
    assert attach.rollout_path("missing", tmp_path / ".codex" / "sessions") is None
    assert attach.Rollout.open("missing", tmp_path / ".codex" / "sessions") is None


def test_the_call_uses_the_codex_session_name(tmp_path):
    database = tmp_path / "state_5.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT)")
        connection.execute(
            "INSERT INTO threads VALUES (?, ?, ?)",
            ("thread-9", "  Review   call UI  ", "Old title"),
        )
    assert attach.session_name("thread-9", tmp_path) == "Review call UI"
    assert attach.session_name("other", tmp_path) is None


def test_the_call_uses_the_session_title_when_the_name_is_empty(tmp_path):
    database = tmp_path / "state_5.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT)")
        connection.execute("INSERT INTO threads VALUES (?, ?, ?)", ("thread-9", "", "Call plan"))
    assert attach.session_name("thread-9", tmp_path) == "Call plan"


# ------------------------------------------------------------- reading it


def test_only_records_written_since_the_last_read_are_returned(tmp_path):
    path = rollout_file(tmp_path)
    write(path, [agent_message("first")])
    rollout = attach.Rollout(path)
    assert len(rollout.read_new()) == 1
    assert rollout.read_new() == []
    with path.open("a") as handle:
        handle.write(json.dumps(agent_message("second")) + "\n")
    assert len(rollout.read_new()) == 1


def test_attaching_mid_conversation_does_not_replay_the_history(tmp_path):
    # A rollout holds every turn the thread has ever had. A call should hear what
    # is said on the call, not the whole transcript read back.
    path = rollout_file(tmp_path)
    write(path, [agent_message("long ago"), agent_message("also long ago")])
    rollout = attach.Rollout(path)
    rollout.skip_history()
    assert rollout.read_new() == []
    with path.open("a") as handle:
        handle.write(json.dumps(agent_message("just now")) + "\n")
    assert len(rollout.read_new()) == 1


def test_a_partly_written_record_is_left_for_the_next_read(tmp_path):
    # The file grows while it is being read, so the last line is often incomplete.
    path = rollout_file(tmp_path)
    whole = json.dumps(agent_message("complete"))
    partial = json.dumps(agent_message("still being written"))
    path.write_text(whole + "\n" + partial[: len(partial) // 2])
    rollout = attach.Rollout(path)

    assert len(rollout.read_new()) == 1

    path.write_text(whole + "\n" + partial + "\n")
    records = rollout.read_new()
    assert len(records) == 1
    assert attach.spoken_message(records[0])["text"] == "still being written"


def test_an_unreadable_record_does_not_stop_the_thread(tmp_path):
    path = rollout_file(tmp_path)
    write(path, [{}])
    with path.open("a") as handle:
        handle.write("this is not json\n")
        handle.write(json.dumps(agent_message("survived")) + "\n")
    # The unparseable line is not a record and is dropped; the next one survives.
    records = attach.Rollout(path).read_new()
    assert [attach.spoken_message(r) for r in records] == [
        None,
        {"id": "msg-1", "text": "survived", "kind": "commentary"},
    ]


def test_a_missing_file_after_attaching_reads_as_nothing(tmp_path):
    path = rollout_file(tmp_path)
    write(path, [agent_message("hello")])
    rollout = attach.Rollout(path)
    path.unlink()
    assert rollout.read_new() == []


# ------------------------------------------------------- what gets spoken


def test_an_agent_message_is_spoken_with_its_phase():
    assert attach.spoken_message(agent_message("Done.", phase="final_answer")) == {
        "id": "msg-1",
        "text": "Done.",
        "kind": "final_answer",
    }


def test_reasoning_and_tool_records_are_never_spoken():
    # These share the stream with the agent's replies. Reading them aloud would put
    # command output and private reasoning into the user's ears.
    reasoning = item_completed({"type": "Reasoning", "id": "r-1", "raw_content": []})
    command = item_completed(
        {"type": "CommandExecution", "id": "e-1", "command": "ls", "stdout": "a\nb"}
    )
    change = item_completed({"type": "FileChange", "id": "f-1", "changes": {"a.py": {}}})
    assert attach.spoken_message(reasoning) is None
    assert attach.spoken_message(command) is None
    assert attach.spoken_message(change) is None
    assert attach.spoken_message({"type": "session_meta", "payload": {}}) is None


def test_a_user_message_is_not_read_back_to_the_user():
    # The queued message is the user's own speech. Hearing it repeated would make
    # the agent look like it was parroting them.
    echo = item_completed(
        {"type": "UserMessage", "id": "u-1", "content": [{"type": "text", "text": "hello"}]}
    )
    assert attach.spoken_message(echo) is None


def test_an_empty_agent_message_is_not_spoken():
    assert attach.spoken_message(agent_message("   ")) is None
    assert attach.spoken_message(item_completed({"type": "AgentMessage", "id": "m"})) is None


def test_a_tool_record_becomes_one_short_phrase():
    command = attach.tool_activity(
        item_completed({"type": "CommandExecution", "id": "e-1", "parsed_cmd": "pytest -q"})
    )
    assert command["text"] == "Ran pytest -q"
    change = attach.tool_activity(
        item_completed({"type": "FileChange", "id": "f-1", "changes": {"a": {}, "b": {}}})
    )
    assert change["text"] == "Edited 2 files"
    one = attach.tool_activity(
        item_completed({"type": "FileChange", "id": "f-1", "changes": {"a": {}}})
    )
    assert one["text"] == "Edited 1 file"


def test_a_command_with_no_text_is_skipped():
    assert (
        attach.tool_activity(
            item_completed({"type": "CommandExecution", "id": "e-1", "command": "  "})
        )
        is None
    )


# ------------------------------------------------------------ the turn end


def test_task_complete_reports_the_turn_and_its_final_message():
    finished = attach.turn_finished(
        record(type="task_complete", turn_id="turn-9", last_agent_message="All done.")
    )
    assert finished == {"turn_id": "turn-9", "last_message": "All done."}


def test_other_records_do_not_look_like_a_finished_turn():
    assert attach.turn_finished(agent_message("still going")) is None
    assert attach.turn_finished({"type": "turn_context", "payload": {}}) is None


# -------------------------------------------------------------- the queue


def test_the_queue_command_does_not_claim_the_thread():
    # Without `queue` this would have to resume the thread, which takes the writer
    # away from the terminal the user is sitting in.
    argv = attach.queue_argv("/usr/local/bin/codex", "t-1", "hello")
    assert argv == ["/usr/local/bin/codex", "queue", "--thread", "t-1", "--message=hello"]


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_a_message_is_delivered_without_a_writer(monkeypatch):
    monkeypatch.setattr(attach, "find_command", lambda name: "/usr/local/bin/codex")
    seen = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        return Result()

    attach.queue_message("t-1", "hello", cwd="/tmp", run=run)
    assert seen["argv"][:4] == ["/usr/local/bin/codex", "queue", "--thread", "t-1"]


def test_a_rejected_message_explains_itself(monkeypatch):
    monkeypatch.setattr(attach, "find_command", lambda name: "/usr/local/bin/codex")

    with pytest.raises(ValueError) as error:
        attach.queue_message(
            "t-1", "hello", run=lambda *a, **k: Result(returncode=1, stderr="no such thread\n")
        )
    assert "no such thread" in str(error.value)


def test_joining_a_session_without_codex_says_so(monkeypatch):
    # The message has to name the thing the user can act on. "Not installed" was
    # what the app said while Codex sat in front of them, because it was asking
    # about its own PATH rather than theirs.
    monkeypatch.setattr(attach, "find_command", lambda name: None)
    with pytest.raises(ValueError) as error:
        attach.queue_message("t-1", "hello")
    assert "could not be found" in str(error.value)
    assert "reopen" in str(error.value)


def test_a_rollout_directory_is_not_assumed_to_exist():
    # The path is only read, never created: a rollout belongs to Codex.
    assert attach.rollout_path("t-1", Path("/nonexistent/nothing")) is None


# ------------------------------------------------- following a whole turn


class FakeRollout:
    """A rollout that hands over prepared records, one batch per read."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.skipped = False
        self.reads = 0
        # No file, so the write watcher falls back to polling.
        self.path = Path("/nonexistent/rollout.jsonl")

    def skip_history(self):
        self.skipped = True

    def read_new(self):
        self.reads += 1
        return self.batches.pop(0) if self.batches else []




def adapter(monkeypatch, batches, delivered=None):
    built = attach.AttachedAdapter("t-1", "/tmp/project")
    built.poll = 0.001
    built.ack_timeout = 2
    built.rollout = FakeRollout([[], *batches])
    # Always stubbed: the real one runs the Codex binary, which has no thread to
    # deliver to in a test.
    recorded = delivered if delivered is not None else []

    def deliver(*args, **kwargs):
        recorded.append(args)

    built.deliver = deliver
    return built


def recorder():
    emitted = []

    async def emit(event_type, **data):
        emitted.append((event_type, data))

    return emitted, emit


async def collect(adapter, text="hello"):
    """Run one turn and return everything the adapter reported."""
    emitted, emit = recorder()
    try:
        async with asyncio.timeout(3):
            await adapter.run(text, emit, lambda *a: None)
    finally:
        await adapter.close()
    return emitted


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.002)


def spoken(emitted):
    return [data["text"] for event, data in emitted if event == "message.done"]


async def test_a_queued_message_is_delivered_into_the_thread(monkeypatch):
    delivered = []
    built = adapter(
        monkeypatch,
        [[queued_user_message("what changed?"), record(type="task_complete", turn_id="turn-1")]],
        delivered,
    )
    await collect(built, "what changed?")
    assert delivered == [("t-1", "what changed?", "/tmp/project")]


async def test_the_agent_reply_is_spoken_with_its_phase():
    built = adapter(
        None,
        [
            [queued_user_message(), agent_message("Looking now.", phase="commentary")],
            [record(type="task_complete", turn_id="turn-1", last_agent_message="Looking now.")],
        ],
    )
    emitted = await collect(built)
    assert emitted == [
        ("turn.queue_start", {}),
        ("turn.queued", {}),
        ("turn.accepted", {}),
        ("message.done", {"item_id": "msg-1", "text": "Looking now.", "kind": "commentary"})
    ]


async def test_tool_work_is_reported_without_being_read_aloud():
    built = adapter(
        None,
        [
            [
                queued_user_message(),
                item_completed(
                    {
                        "type": "CommandExecution",
                        "id": "e-1",
                        "parsed_cmd": "pytest -q",
                        "stdout": "a very long output that must never be spoken",
                    }
                ),
                agent_message("Tests pass.", phase="final_answer"),
            ],
            [record(type="task_complete", turn_id="turn-1")],
        ],
    )
    emitted = await collect(built)
    kinds = [event for event, _ in emitted]
    assert kinds == [
        "turn.queue_start",
        "turn.queued",
        "turn.accepted",
        "tool.status",
        "message.done",
    ]
    assert emitted[3][1]["text"] == "Ran pytest -q"
    assert "long output" not in json.dumps(emitted)


async def test_a_turn_ends_when_the_thread_says_it_did():
    built = adapter(
        None,
        [
            [
                queued_user_message(),
                agent_message("All done.", phase="final_answer"),
                record(type="task_complete", turn_id="turn-1"),
            ]
        ],
    )
    emitted = await collect(built)
    assert spoken(emitted) == ["All done."]
    assert built.waiting == []


async def test_an_earlier_turn_does_not_take_the_new_question():
    built = adapter(
        None,
        [
            [
                agent_message("The call connected.", phase="final_answer"),
                record(type="task_complete", turn_id="earlier"),
            ],
            [queued_user_message(), agent_message("This is the answer.", phase="final_answer")],
            [record(type="task_complete", turn_id="turn-1")],
        ],
    )
    emitted = await collect(built)
    assert emitted == [
        ("turn.queue_start", {}),
        ("turn.queued", {}),
        ("turn.accepted", {}),
        (
            "message.done",
            {"item_id": "msg-1", "text": "This is the answer.", "kind": "final_answer"},
        ),
    ]


async def test_a_busy_terminal_is_a_status_and_its_late_reply_is_spoken():
    # The terminal reads a queued message only after its current work. That is
    # a wait, not a failure, and the reply that comes later is still the answer.
    built = adapter(None, [])
    built.ack_timeout = 0.01
    emitted, emit = recorder()
    turn = asyncio.create_task(built.run("hello", emit, None))
    await until(lambda: ("tool.status", {"text": "Waiting for the terminal", "status": "active"}) in emitted)
    assert not turn.done()
    built.rollout.batches.append(
        [queued_user_message(), agent_message("Sorry, I was busy.", phase="final_answer")]
    )
    built.rollout.batches.append([record(type="task_complete", turn_id="turn-1")])
    async with asyncio.timeout(3):
        await turn
    await built.close()
    assert spoken(emitted) == ["Sorry, I was busy."]
    assert ("turn.accepted", {}) in emitted


async def test_a_follow_up_during_work_keeps_the_first_reply():
    # A second utterance replaces the first run. The first turn still ends later,
    # and its reply plays in the call through the run that is live then.
    built = adapter(None, [])
    first_events, first = recorder()
    second_events, second = recorder()
    first_run = asyncio.create_task(built.run("first", first, None))
    built.rollout.batches.append([
        item_completed(
            {"type": "UserMessage", "id": "u-1", "content": [{"type": "text", "text": "first"}]}
        ),
        agent_message("Working on the first.", item_id="m-1"),
    ])
    await until(lambda: spoken(first_events) == ["Working on the first."])
    first_run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_run
    second_run = asyncio.create_task(built.run("second", second, None))
    await until(lambda: len(built.waiting) == 2)
    built.rollout.batches.append([
        agent_message("The first is done.", phase="final_answer", item_id="m-2"),
        record(type="task_complete", turn_id="turn-1"),
    ])
    built.rollout.batches.append([
        record(
            type="item_completed",
            turn_id="turn-2",
            item={"type": "UserMessage", "id": "u-2", "content": [{"type": "text", "text": "second"}]},
        ),
        record(
            type="item_completed",
            turn_id="turn-2",
            item={
                "type": "AgentMessage",
                "id": "m-3",
                "content": [{"type": "Text", "text": "And the second."}],
                "phase": "final_answer",
            },
        ),
        record(type="task_complete", turn_id="turn-2"),
    ])
    async with asyncio.timeout(3):
        await second_run
    await built.close()
    assert spoken(second_events) == ["The first is done.", "And the second."]


async def test_one_merged_message_answers_every_queued_one():
    # A terminal can join messages that were queued while it worked into one
    # user message. Each queued message is answered by that one turn.
    built = adapter(None, [])
    _, first = recorder()
    second_events, second = recorder()
    first_run = asyncio.create_task(built.run("Check the tests", first, None))
    await until(lambda: len(built.waiting) == 1)
    first_run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_run
    second_run = asyncio.create_task(built.run("and the  docs", second, None))
    await until(lambda: len(built.waiting) == 2)
    built.rollout.batches.append([
        queued_user_message("Check the tests\n\nand the docs"),
        agent_message("Both look fine.", phase="final_answer"),
        record(type="task_complete", turn_id="turn-1"),
    ])
    async with asyncio.timeout(3):
        await second_run
    await built.close()
    assert spoken(second_events) == ["Both look fine."]
    assert built.waiting == []


async def test_a_stopped_reply_is_not_spoken_when_the_rest_arrives():
    built = adapter(None, [[queued_user_message(), agent_message("First part.")]])
    emitted, emit = recorder()
    turn = asyncio.create_task(built.run("hello", emit, None))
    await until(lambda: spoken(emitted) == ["First part."])
    built.stop_speaking()
    built.rollout.batches.append([
        agent_message("Second part.", item_id="m-2"),
        record(type="task_complete", turn_id="turn-1"),
    ])
    async with asyncio.timeout(3):
        await turn
    await built.close()
    assert spoken(emitted) == ["First part."]


async def test_other_rollout_activity_does_not_acknowledge_the_question(monkeypatch):
    built = adapter(monkeypatch, [[{"type": "event_msg", "payload": {"type": "token_count"}}], []])
    built.ack_timeout = 0.02
    emitted, emit = recorder()
    turn = asyncio.create_task(built.run("hello", emit, None))
    await until(lambda: any(event == "tool.status" for event, _ in emitted))
    assert ("turn.accepted", {}) not in emitted
    turn.cancel()
    await built.close()


async def test_a_queue_failure_is_still_an_error():
    built = adapter(None, [])

    def refuse(*args):
        raise ValueError("Codex would not accept the message for this session.")

    built.deliver = refuse
    with pytest.raises(ValueError, match="would not accept"):
        await collect(built)
    assert built.waiting == []


async def test_joining_needs_a_transcript_to_follow(monkeypatch):
    built = attach.AttachedAdapter("nope", "/tmp")
    monkeypatch.setattr(attach.Rollout, "open", classmethod(lambda cls, *a, **k: None))
    with pytest.raises(ValueError) as error:
        await built.start()
    assert "no Codex transcript yet" in str(error.value)
    # A Claude session called with the default agent lands here, so the message
    # names the flag that fixes it.
    assert "--agent claude" in str(error.value)


async def test_attaching_skips_the_conversation_so_far(monkeypatch):
    rollout = FakeRollout([[]])
    monkeypatch.setattr(attach.Rollout, "open", classmethod(lambda cls, *a, **k: rollout))
    built = attach.AttachedAdapter("t-1", "/tmp")
    await built.start()
    assert rollout.skipped is True
    await built.close()


async def test_closing_leaves_the_terminal_alone():
    # Nothing was claimed, so there is nothing to release.
    built = attach.AttachedAdapter("t-1", "/tmp")
    built.rollout = FakeRollout([])
    await built.close()
    assert built.rollout is None


class FakeProxy:
    def __init__(self):
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdin = None

    def terminate(self):
        self.returncode = -15
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    kill = terminate

    async def wait(self):
        return self.returncode


async def test_a_queue_proxy_that_exited_is_started_again(monkeypatch):
    from talktome import codex_queue

    started = []

    async def spawn(*args, **kwargs):
        started.append(FakeProxy())
        return started[-1]

    async def answer(*args, **kwargs):
        return {}

    monkeypatch.setattr(codex_queue, "find_command", lambda name: "/usr/local/bin/codex")
    monkeypatch.setattr(codex_queue.asyncio, "create_subprocess_exec", spawn)
    transport = codex_queue.CodexQueueTransport()
    monkeypatch.setattr(transport, "_request", answer)
    monkeypatch.setattr(transport, "_notify", answer)
    await transport.start()
    await transport.start()
    assert len(started) == 1
    started[0].terminate()
    await transport.start()
    assert len(started) == 2
    assert transport.process is started[1]
    await transport.close()
