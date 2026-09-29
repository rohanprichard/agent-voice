"""The file a command leaves for the app, and the answer the app leaves back.

This is the contract between two processes, so what it is worth testing is the shape
of the exchange rather than any one caller: a request nobody can misread, an answer
that arrives whole, and nothing left behind for the next run to trip on.

The other half of it is where the file goes. Two rounds of this feature were broken
by not asking what the sandbox permits — first the network, then the app's own
folder — so the fallback is tested as the reason it exists, not as an edge case.
"""

import json
import os
import time
from pathlib import Path

import pytest

from talktome import inbox
from talktome.inbox import shared as computed_shared


def test_a_request_can_be_read_back(tmp_path):
    request = inbox.ask("call", {"thread": "t-1"}, root=tmp_path)
    assert inbox.pending(root=tmp_path) == [request]
    assert request.command == "call"
    assert request.payload == {"thread": "t-1"}


def test_an_answer_travels_back_the_same_way_as_a_result(tmp_path):
    request = inbox.ask("call", root=tmp_path)
    inbox.answer(request, result={"status": "ringing"})
    assert inbox.reply_for(request) == {
        "id": request.id,
        "ok": True,
        "result": {"status": "ringing"},
        "error": None,
    }


def test_a_refusal_carries_its_reason_so_the_agent_can_repeat_it(tmp_path):
    request = inbox.ask("call", root=tmp_path)
    inbox.answer(request, error="That session has no transcript yet.")
    reply = inbox.reply_for(request)
    assert reply["ok"] is False
    assert reply["error"] == "That session has no transcript yet."


def test_an_unanswered_request_reads_as_no_reply_rather_than_nothing(tmp_path):
    request = inbox.ask("call", root=tmp_path)
    (request.reply_path).unlink(missing_ok=True)
    assert inbox.reply_for(request) is None


def test_a_half_written_answer_is_never_readable(tmp_path):
    # The app writes the file whole and renames it into place. Without that the
    # command could open a reply mid-write, read it as broken, and report a
    # failure that did not happen.
    request = inbox.ask("call", root=tmp_path)
    request.reply_path.write_text('{"id": "x", "ok": tr')
    assert inbox.reply_for(request) is None


def test_a_request_is_not_handed_out_twice_once_it_is_retired(tmp_path):
    # Retiring is also the claim on it: a ring takes ten seconds to resolve, and
    # the next pass over the folder must not start it again.
    request = inbox.ask("call", root=tmp_path)
    inbox.pending(root=tmp_path)
    inbox.retire(request)
    assert inbox.pending(root=tmp_path) == []


def test_retiring_keeps_the_answer_for_whoever_asked(tmp_path):
    request = inbox.ask("call", root=tmp_path)
    inbox.answer(request, result={"status": "ringing"})
    inbox.retire(request)
    assert inbox.reply_for(request)["result"] == {"status": "ringing"}


def test_collecting_removes_both_halves(tmp_path):
    request = inbox.ask("call", root=tmp_path)
    inbox.answer(request, result={})
    inbox.collect(request)
    assert inbox.reply_for(request) is None
    assert inbox.pending(root=tmp_path) == []


def test_requests_are_handled_oldest_first(tmp_path):
    second = inbox.ask("end", root=tmp_path)
    first = inbox.ask("call", root=tmp_path)
    older = time.time() - 10
    os.utime(first.path, (older, older))
    assert [found.id for found in inbox.pending(root=tmp_path)] == [first.id, second.id]


def test_the_identifier_comes_from_the_file_name(tmp_path):
    # So a note written badly is still named well enough to retire.
    place = inbox.folder(tmp_path)
    place.mkdir(parents=True, exist_ok=True)
    (place / f"abc{inbox.REQUEST}").write_text(json.dumps({"command": "call"}))
    assert [found.id for found in inbox.pending(root=tmp_path)] == ["abc"]


# ------------------------------------------- where the note can actually go


def test_a_request_is_left_in_the_apps_own_folder_when_it_can_be(tmp_path):
    # The private folder is the right place for it, and the fallback is only for
    # when a sandbox is in the way.
    request = inbox.ask("call", root=tmp_path)
    assert request.place == inbox.folder(tmp_path)


def test_a_command_that_cannot_write_the_apps_folder_still_leaves_a_request(tmp_path, monkeypatch):
    """The failure this exists for.

    Codex allows a command to write its workspace and the temporary folder and
    nothing else, so `~/Library/Application Support` is refused outright. Left as
    the only place to put a request, that refusal reached the user as a traceback
    out of a bundled binary, and the call simply never happened.
    """
    private = inbox.folder(tmp_path)
    allowed = inbox.prepare

    monkeypatch.setattr(
        inbox,
        "prepare",
        lambda place: False if place == private else allowed(place),
    )
    request = inbox.ask("call", {"thread": "t-1"}, root=tmp_path)
    assert request.place == inbox.shared()
    assert request.command == "call"


def test_a_note_that_cannot_be_written_moves_on_to_the_next_folder(tmp_path, monkeypatch):
    # A sandbox may allow the folder to be prepared and refuse the write itself, so
    # the failure has to be survivable at the point of writing as well.
    private = inbox.folder(tmp_path)
    real_write = inbox._write

    def refuse_the_private_folder(path, payload):
        if path.parent == private:
            raise PermissionError("not here")
        real_write(path, payload)

    monkeypatch.setattr(inbox, "_write", refuse_the_private_folder)
    assert inbox.ask("call", root=tmp_path).place == inbox.shared()


def test_the_fallback_is_a_place_both_sides_agree_on_without_asking():
    # `$TMPDIR` is writable under the sandbox too, but it is whatever each process
    # happened to be started with, and a rendezvous that needs two environments to
    # match is the bug this replaces. `computed_shared` is the real function,
    # captured before the fixture redirects the module attribute.
    assert computed_shared() == Path("/tmp") / f"talktome-{os.getuid()}" / "requests"


def test_both_folders_are_watched_whichever_one_the_note_landed_in(tmp_path):
    private = inbox.ask("call", root=tmp_path)
    place = inbox.shared()
    place.mkdir(parents=True, exist_ok=True)
    moved = inbox.Request(id="moved", place=place, command="end", payload={})
    moved.path.write_text(json.dumps({"command": "end"}))
    assert sorted(found.id for found in inbox.pending(root=tmp_path)) == sorted(
        [private.id, "moved"]
    )


def test_a_folder_someone_else_owns_is_refused(tmp_path, monkeypatch):
    # The fallback sits in a directory anyone can write to, so a folder that is not
    # ours is not a place to leave a request. `chmod` failing is the answer.
    monkeypatch.setattr(inbox.os, "chmod", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    place = tmp_path / "not-ours" / "requests"
    assert inbox.prepare(place) is False
    assert inbox.ready(root=tmp_path) == []


def test_a_folder_that_can_be_made_is_private(tmp_path):
    place = inbox.folder(tmp_path)
    assert inbox.prepare(place) is True
    assert place.stat().st_mode & 0o777 == 0o700


def test_nothing_writable_at_all_says_what_to_do(tmp_path, monkeypatch):
    # A read-only sandbox cannot be worked around, so the message has to name the
    # thing the user can change rather than leaving a traceback.
    monkeypatch.setattr(inbox, "prepare", lambda place: False)
    with pytest.raises(ValueError) as error:
        inbox.ask("call", root=tmp_path)
    assert "read-only" in str(error.value)


# ------------------------------------------------------------- housekeeping


def test_a_note_nobody_is_waiting_for_is_swept_away(tmp_path):
    # Left behind, a request written for an app that never came up would ring the
    # user the next time it opened, for a command that finished long ago.
    inbox.ask("call", root=tmp_path)
    inbox.sweep(root=tmp_path, stale=0, now=time.time() + inbox.STALE + 1)
    assert inbox.pending(root=tmp_path) == []


def test_a_fresh_request_survives_the_sweep_an_app_does_as_it_starts(tmp_path):
    # The command writes its request *before* it starts a sleeping app, so the
    # sweep that app runs on the way up must not eat the call that woke it.
    request = inbox.ask("call", root=tmp_path)
    inbox.sweep(root=tmp_path)
    assert [found.id for found in inbox.pending(root=tmp_path)] == [request.id]


def test_a_note_that_was_written_badly_is_skipped_rather_than_crashing(tmp_path):
    place = inbox.folder(tmp_path)
    place.mkdir(parents=True, exist_ok=True)
    (place / f"broken{inbox.REQUEST}").write_text("{not json")
    assert inbox.pending(root=tmp_path) == []


def test_a_folder_other_accounts_can_write_is_not_read(tmp_path, monkeypatch):
    # Under /tmp another account can make the folder first and plant a request.
    planted = tmp_path / "planted" / "requests"
    planted.mkdir(parents=True)
    os.chmod(planted, 0o777)
    monkeypatch.setattr(inbox, "shared", lambda: planted)
    (planted / "x.request.json").write_text(json.dumps({"command": "end"}))
    assert inbox.pending(root=tmp_path / "private") == []


def test_an_answer_does_not_follow_a_planted_symlink(tmp_path):
    request = inbox.ask("call", {}, root=tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("keep")
    request.reply_path.with_name(f"{request.reply_path.name}.tmp").symlink_to(victim)
    inbox.answer(request, result={})
    assert victim.read_text() == "keep"
    assert inbox.reply_for(request)["ok"] is True


def test_a_planted_symlink_folder_is_refused_before_any_chmod(tmp_path, monkeypatch):
    # Another account points /tmp/talktome-<uid> at a folder of ours.
    victim = tmp_path / "victim"
    victim.mkdir()
    os.chmod(victim, 0o755)
    link = tmp_path / "talktome-link"
    link.symlink_to(victim)
    place = link / "requests"
    assert inbox.prepare(place) is False
    assert oct(victim.stat().st_mode & 0o777) == "0o755"
    assert not (victim / "requests").exists()
