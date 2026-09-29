import asyncio

import pytest

from talktome import cooperative
from talktome.cooperative import CooperativeAdapter, CooperativeError


def room_event(text="hello", turn_id="turn-1"):
    return {"call_id": "call-1", "turn_id": turn_id, "text": text}


async def started():
    adapter = CooperativeAdapter("generic", "s-1", "/tmp")
    await adapter.start()
    return adapter


async def noop(*args, **kwargs):
    pass


@pytest.mark.asyncio
async def test_a_turn_finishes_on_the_final_reply():
    adapter = await started()
    adapter.begin_turn(room_event())
    emitted = []

    async def emit(event, **data):
        emitted.append((event, data))

    task = asyncio.create_task(adapter.run("hello", emit, None))
    result = await adapter.listen(after=0, timeout=1)
    pending = result["pending"]
    assert pending["turn_id"] == "turn-1"
    await adapter.reply("s-1", "call-1", "turn-1", "item-1", "Hi there.", False)
    # A progress reply is spoken, but the turn is still open.
    assert not task.done()
    await adapter.reply("s-1", "call-1", "turn-1", "item-2", "All done.", True)
    await asyncio.wait_for(task, 1)
    spoken = [data for event, data in emitted if event == "message.done"]
    assert [(item["item_id"], item["text"]) for item in spoken] == [
        ("item-1", "Hi there."),
        ("item-2", "All done."),
    ]


@pytest.mark.asyncio
async def test_a_sequence_from_an_earlier_call_resets_at_once():
    adapter = await started()
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    result = await adapter.listen(after=40, timeout=25)
    assert result["reset"] is True
    assert loop.time() - started_at < 1


@pytest.mark.asyncio
async def test_a_turn_that_fails_its_checks_does_not_block_the_next():
    adapter = await started()
    adapter.begin_turn(room_event("hello"))
    with pytest.raises(CooperativeError):
        await adapter.run("different text", noop, None)
    # The failed event is gone, so a new one can bind.
    adapter.begin_turn(room_event("again", turn_id="turn-2"))


@pytest.mark.asyncio
async def test_a_host_that_stops_listening_ends_the_turn(monkeypatch):
    monkeypatch.setattr(cooperative, "TURN_IDLE", 0.05)
    adapter = await started()
    adapter.begin_turn(room_event())
    with pytest.raises(RuntimeError, match="stopped listening"):
        await asyncio.wait_for(adapter.run("hello", noop, None), 2)
    assert adapter.current is None


async def test_the_capability_reports_agree():
    from talktome.managed import ManagedSession
    from talktome.room import Room

    managed = ManagedSession(Room(), None, None)
    managed.adapter = await started()
    report = managed.capabilities()
    assert report["supports_cancel_speech"] is report["cancel_speech"] is True
    assert report["supports_cancel_work"] is report["cancel_work"] is False
