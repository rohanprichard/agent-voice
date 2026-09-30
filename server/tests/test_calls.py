import asyncio

from talktome_server.calls import match_choice, speech_time


async def test_a_question_call_returns_the_answer_and_the_choice(world):
    app = world.app
    result = asyncio.create_task(
        world.post("/v1/call", {"reason": "Deploy", "question": "Which region?", "choices": ["us", "eu"]})
    )
    start = await app.next("call.start")
    assert start["body"] == {"question": "Which region?", "choices": ["us", "eu"]}
    app.send("call.answered", call_id=start["call_id"])
    app.send("turn.user", call_id=start["call_id"], turn_id="t1", text="The second one.")
    reply = await app.next("turn.agent")
    assert (reply["turn_id"], reply["text"], reply["final"]) == ("t1", "Got it.", True)
    await app.next("call.end")
    answer = await result
    assert answer == {"answered": True, "answer": "The second one.", "choice": {"index": 1, "label": "eu"}}


async def test_a_declined_call_says_so(world):
    app = world.app
    result = asyncio.create_task(world.post("/v1/call", {"reason": "Hi", "greeting": "Hello."}))
    start = await app.next("call.start")
    app.send("call.missed", call_id=start["call_id"], reason="declined")
    assert await result == {"answered": False, "status": "declined"}


async def test_a_conversation_turns_until_the_user_hangs_up(world):
    app = world.app
    result = asyncio.create_task(world.post("/v1/call", {"reason": "Check in", "greeting": "Hi, the build is done."}))
    start = await app.next("call.start")
    call_id = start["call_id"]
    app.send("call.answered", call_id=call_id)
    app.send("turn.user", call_id=call_id, turn_id="t1", text="Any failures?")
    opened = await result
    assert opened["user_said"] == "Any failures?"

    turn = asyncio.create_task(world.post("/v1/turn", {"say": "None."}))
    reply = await app.next("turn.agent")
    assert (reply["turn_id"], reply["text"]) == ("t1", "None.")
    app.send("call.ended", call_id=call_id, reason="hung up", by="device")
    assert await turn == {"spoken": True, "user_said": None, "ended": True}


async def test_a_second_call_while_one_is_live_is_refused(world):
    app = world.app
    first = asyncio.create_task(world.post("/v1/call", {"reason": "One", "greeting": "Hi."}))
    start = await app.next("call.start")
    app.send("call.answered", call_id=start["call_id"])
    app.send("turn.user", call_id=start["call_id"], turn_id="t1", text="Hello.")
    await first
    try:
        await world.post("/v1/call", {"reason": "Two", "greeting": "Hi."})
    except RuntimeError as exc:
        assert "already live" in str(exc)
    else:
        raise AssertionError("the second call was placed")


async def test_a_notice_goes_to_the_app(world):
    assert await world.post("/v1/notify", {"reason": "Build", "message": "It passed."}) == {"delivered": 1}
    notice = await world.app.next("notify")
    assert notice["body"] == {"message": "It passed."}


def test_choices_by_name_or_number():
    assert match_choice("Let's go with EU", ["us", "eu"]) == {"index": 1, "label": "eu"}
    assert match_choice("the first", ["us", "eu"]) == {"index": 0, "label": "us"}
    assert match_choice("either", ["us", "eu"]) is None
    assert speech_time("x" * 1000) == 20.0
