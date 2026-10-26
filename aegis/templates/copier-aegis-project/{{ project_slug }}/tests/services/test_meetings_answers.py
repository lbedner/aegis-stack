"""Questions put to the bot by name, answered out loud in the call
(``bot.answers``): it says her answer in the chat and aloud when its run
is done, and that it is looking it up only while she is slow to."""

from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.actions import registry
from app.services.meetings.domains.actions.registry import Action
from app.services.meetings.domains.bot import answers
from app.services.meetings.domains.bot.meet import CallState
from app.services.meetings.models import MeetingActionRun
from tests._meetings import (
    FakeCall,
    FakeLive,
    a_meeting,
    asked_a_question,
    hold_the_answers,
)

# A question put to the bot (it joins as "Notes").
HER = (("Dana", "Hey Notes, who owns billing?"),)


@pytest.fixture
def voiced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Speech made from the words, to tell what was said aloud; her answer,
    asked as the line is said, held, not run."""

    async def spoken(text: str, voice: Any) -> bytes | None:
        return None if voice is None else text.encode()

    monkeypatch.setattr(answers, "spoken", spoken)
    hold_the_answers(monkeypatch)
    if registry.action_named(registry.ANSWERS) is None:  # a stack without her
        her = Action(registry.ANSWERS, "Ask AI", registry.QUESTIONS, "app", run=_unused)
        monkeypatch.setitem(registry._actions, registry.ANSWERS, her)


async def _unused(prompt: str, owner_user_id: int | None) -> str:
    raise AssertionError("her answer is held here, never run")


async def _over(db: AsyncSession, status: str, result: str) -> None:
    """Her answer to the one question put to her, done or failed."""
    from sqlmodel import select

    (run,) = (await db.exec(select(MeetingActionRun))).all()
    run.status, run.result = status, result
    db.add(run)
    await db.commit()


async def _took(db: AsyncSession, transcript: Any, captions: list[Any]) -> list[Any]:
    """What ``captions`` made once the transcript took them: those due written
    (``Transcript.take``, then ``write``)."""
    writing = transcript.take(captions)
    return await transcript.write(db, writing) if writing else []


async def test_a_quick_answer_is_said_without_looking_it_up_first(
    async_db_session: AsyncSession, voiced: None
) -> None:
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.heard([(moment_id, "addressed")])
    await _over(async_db_session, "done", "Sam owns billing.")
    await answering.answer(async_db_session)
    await answering.answer(async_db_session)  # said once
    await answering.said()

    assert call.said == ["Sam owns billing."]
    assert call.spoken == [b"Sam owns billing."]
    answering.close()


async def test_a_slow_answer_is_looked_up_out_loud_once_while_it_waits(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(answers, "LOOKING_AFTER", 0.0)
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.heard([(moment_id, "addressed")])
    await answering.answer(async_db_session)
    await answering.answer(async_db_session)
    await answering.said()
    assert call.spoken == [answers.LOOKING.encode()] and call.said == []

    await _over(async_db_session, "done", "Sam owns billing.")
    await answering.answer(async_db_session)
    await answering.said()

    assert call.spoken == [answers.LOOKING.encode(), b"Sam owns billing."]
    answering.close()


async def test_an_answer_is_posted_at_once_and_spoken_a_sentence_at_a_time(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Her speech is made a sentence at a time, the first played while the
    rest are made, and never holds up the call: what she said is in the
    chat before any of it is heard."""
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.heard([(moment_id, "addressed")])
    await _over(async_db_session, "done", "Sam owns billing. Dana owns search.")
    await answering.answer(async_db_session)
    assert call.said == ["Sam owns billing. Dana owns search."] and call.spoken == []

    await answering.said()
    assert call.spoken == [b"Sam owns billing.", b"Dana owns search."]
    answering.close()


async def test_her_markdown_is_said_as_plain_sentences(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """She writes for a chat: a list or bold read aloud would be heard as
    symbols, and one sentence the length of the list."""
    pytest.importorskip("app.services.ai.domains.voice.spoken")
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.heard([(moment_id, "addressed")])
    await _over(
        async_db_session, "done", "- **Sam** owns billing.\n- Dana owns search."
    )
    await answering.answer(async_db_session)
    await answering.said()

    assert call.spoken == [b"Sam owns billing.", b"Dana owns search."]
    answering.close()


async def test_a_failed_answer_is_said_as_not_found_and_no_voice_types_it(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Without a voice it types what it would have said."""
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice=None)

    await answering.heard([(moment_id, "addressed"), (moment_id + 99, "question")])
    await _over(async_db_session, "failed", "x")
    await answering.answer(async_db_session)

    assert call.said == [answers.NOT_FOUND] and call.spoken == []
    answering.close()


async def test_a_line_for_the_bot_is_written_once_its_speaker_pauses(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Captions put a question mark on every pause: a line naming the bot,
    or said right after it spoke, waits until it stops changing, then is
    written at once, never on the beat half said."""
    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "BEAT_SECONDS", 0.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")
    half = Caption("1", "Dana", "Hey Notes, can you tell us how a?")
    whole = Caption("1", "Dana", "Hey Notes, can you tell us how a request gets in?")

    monkeypatch.setattr(captions, "SETTLE_SECONDS", 60.0)
    talking = await _took(async_db_session, transcript, [half]) + await _took(
        async_db_session, transcript, [whole]
    )
    assert transcript.held  # the call is looked at quickly meanwhile
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    paused = await _took(async_db_session, transcript, [whole])

    assert talking == []
    assert [kind for _, kind in paused] == ["addressed"]
    await _took(
        async_db_session,
        transcript,
        [whole, Caption("2", "You", "Through the gateway.")],
    )
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 60.0)
    back = Caption("3", "Dana", "And then where does it go?")
    assert (
        await _took(async_db_session, transcript, [back]) == []
    )  # said back to it: held too
    other = Caption("4", "Sam", "Can we move on to lunch now?")
    await _took(async_db_session, transcript, [other])
    assert "4" not in transcript.pending  # not the one it answered: not held


async def test_each_time_the_bot_is_named_in_one_long_caption_is_its_own_line(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meet keeps one caption while a speaker talks on: it is cut before each
    sentence naming the bot, so each question put to it is heard."""
    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")
    talk = "What can you tell me? Hey Notes. How is billing going right now?"

    first = await _took(async_db_session, transcript, [Caption("1", "Dana", talk)])
    then = await _took(
        async_db_session,
        transcript,
        [Caption("1", "Dana", f"{talk} Hey Notes, who owns the invoices?")],
    )

    assert [kind for _, kind in first + then] == ["addressed", "addressed"]
    assert first[0][0] != then[0][0]


async def test_a_caption_meet_draws_again_is_the_same_line(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meet sometimes starts a second block for what a speaker is still
    saying (the name spelled anew, the rest run on): it is that line drawn
    again, asked once, never two questions."""
    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "BEAT_SECONDS", 0.0)
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")
    first = Caption("1", "Dana", "Notes, can you tell me how a?")
    again = Caption("2", "Dana", "Nodes, can you tell me how a? Uh, a request gets in.")

    begun = Caption("2", "Dana", "Nodes.")  # too little yet to tell

    made = await _took(async_db_session, transcript, [first])
    made += await _took(async_db_session, transcript, [first, begun])
    made += await _took(async_db_session, transcript, [first, again])
    made += await _took(async_db_session, transcript, [first, again])

    from app.services.meetings.domains.moments.service import moments_of

    (moment,) = await moments_of(async_db_session, meeting_id)
    assert [kind for _, kind in made] == ["addressed"]
    assert moment.text.endswith("a request gets in.")


@pytest.mark.parametrize(
    ("before", "shown", "again"),
    [
        (  # the name spelled anew
            "Illiana, how many workers are there?",
            "Ileana. How many workers are there?",
            True,
        ),
        (  # the rest of it run on
            "Illiana, can you tell me how a?",
            "Iliana, can you tell me how a? Uh, request gets to the database.",
            True,
        ),
        (  # drawn again with the name spelled anew in its first words
            "So Illiana, um, if redis goes down?",
            "So Ileana, um,",
            True,
        ),
        (  # drawn again from mid-way
            "Yeah, I don't know, Illiana said. It was fine earlier, though.",
            "Ileana said it was fine earlier.",
            True,
        ),
        (
            "Iliana, can you tell me how a? Uh, request gets to the database.",
            "Yeah, how does a request get to the database?",
            False,
        ),
        (
            "Hey Illiana, how is it going?",
            "Hey Illiana, how many workers are there?",
            False,
        ),
    ],
)
def test_a_block_is_the_last_drawn_again_only_where_it_says_it_again(
    before: str, shown: str, again: bool
) -> None:
    from app.services.meetings.domains.bot.transcript import said_again

    assert said_again(before, shown) is again


async def test_with_nothing_to_answer_her_it_waits_on_nothing(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stack where nothing answers her (``answerer``: none) is never told
    "let me look that up" for an answer that will not come."""
    monkeypatch.setattr(answers, "answerer", lambda: None)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.heard([(1, "addressed")])

    assert answering.waiting == {}
    answering.close()


async def test_an_answer_she_said_live_is_posted_not_said_again(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live, she is heard as she makes the answer: it is posted in the chat
    and not made into speech again, and nothing is said while she thinks."""
    monkeypatch.setattr(answers, "LOOKING_AFTER", 0.0)
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(
        call, voice="hers", live=FakeLive(spoken=("Sam owns billing.",))
    )

    await answering.heard([(moment_id, "addressed")])
    await answering.answer(async_db_session)  # slow, but she is talking already
    await _over(async_db_session, "done", "Sam owns billing.")
    await answering.answer(async_db_session)
    await answering.said()

    assert call.said == ["Sam owns billing."] and call.spoken == []
    answering.close()


async def test_her_live_engine_is_her_voice_profiles_where_she_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bot runs in a worker, where the settings are the .env's, not the
    voice profile's: the engine is the profile's (``voice_of``), and there
    is none to open where she is not the one answering."""
    from types import SimpleNamespace

    from app.services.meetings.domains.bot import voice

    asked: list[str] = []

    class Engines:
        async def resolve(self, session: Any, key: str) -> str:
            asked.append(key)
            return "her engine"

    from app.services.meetings.domains.actions.registry import ANSWERS

    monkeypatch.setattr(voice, "answerer", lambda: ANSWERS)  # she answers
    monkeypatch.setattr(
        voice, "optional", lambda name: SimpleNamespace(live_engines=Engines())
    )
    profile = SimpleNamespace(VOICE_LIVE_ENGINE="gpt-realtime-2.1-mini")

    assert await voice.live_engine_of(None, profile) == "her engine"  # type: ignore[arg-type]
    assert asked == ["gpt-realtime-2.1-mini"]
    assert await voice.live_engine_of(None, None) is None  # type: ignore[arg-type]
    monkeypatch.setattr(voice, "answerer", lambda: "agent")  # a coding agent answers
    assert await voice.live_engine_of(None, profile) is None  # type: ignore[arg-type]


async def test_without_a_voice_there_is_no_live_voice() -> None:
    from app.services.meetings.domains.bot import voice

    async with voice.live(FakeCall([CallState.IN_CALL]), None, None, None) as live:
        assert live is None and voice.LIVE.get() is None
