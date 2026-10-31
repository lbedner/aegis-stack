"""Questions put to the bot by name, answered out loud in the call
(``bot.answers``): it says her answer in the chat and aloud when its run
is done, and that it is looking it up only once she starts to."""

from typing import Any

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.actions import registry, runs
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
        her = Action(registry.ANSWERS, "Ask Illiana", registry.QUESTIONS, "app", run=_unused)
        monkeypatch.setitem(registry._actions, registry.ANSWERS, her)


async def _unused(prompt: str, owner_user_id: int | None) -> str:
    raise AssertionError("her answer is held here, never run")


async def _over(db: AsyncSession, status: str, result: str) -> None:
    """Her answer to the one question put to her, done or failed."""
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

    await answering.heard(async_db_session, [(moment_id, "addressed")])
    await _over(async_db_session, "done", "Sam owns billing.")
    await answering.answer(async_db_session)
    await answering.answer(async_db_session)  # said once
    await answering.said()

    assert call.said == ["Sam owns billing."]
    assert call.spoken == [b"Sam owns billing."]
    answering.close()


async def test_a_slow_answer_with_nothing_to_look_up_is_just_said(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Asked whether she can hear, she takes a few seconds and looks nothing
    up for it: nothing is said until her answer."""
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.heard(async_db_session, [(moment_id, "addressed")])
    await answering.answer(async_db_session)
    await answering.said()

    assert call.spoken == [] and call.said == []
    answering.close()


async def test_once_she_looks_it_up_she_says_so_once(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """A step of her turn (a tool call) while the answer is waited on: she
    says she is looking it up, once however many steps she takes."""
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.heard(async_db_session, [(moment_id, "addressed")])
    answering.looking_up(moment_id)
    await answering.answer(async_db_session)
    answering.looking_up(moment_id)
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

    await answering.heard(async_db_session, [(moment_id, "addressed")])
    await _over(async_db_session, "done", "Sam owns billing. Dana owns search.")
    await answering.answer(async_db_session)
    assert call.said == ["Sam owns billing. Dana owns search."] and call.spoken == []

    await answering.said()
    assert call.spoken == [b"Sam owns billing.", b"Dana owns search."]
    answering.close()


async def test_a_step_of_another_run_is_not_her_looking_it_up(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """A run made here for something else (asked from the page) takes steps
    too: none of them is her looking up the question put to her."""
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.heard(async_db_session, [(moment_id, "addressed")])
    assert answering.looking_up(moment_id + 99) == moment_id + 99
    await answering.answer(async_db_session)
    await answering.said()

    assert call.spoken == []
    answering.close()


@pytest.mark.parametrize("live", [False, True])
async def test_she_is_saying_her_answer_until_it_has_played(
    async_db_session: AsyncSession, voiced: None, live: bool
) -> None:
    """Her answer is back before it is heard: she is saying it until the
    last of it has played, made into speech or said live."""
    import asyncio

    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    her_voice = FakeLive(spoken=("Sam owns billing.",)) if live else None
    answering = answers.Answers(call, voice="hers", live=her_voice)
    await answering.heard(async_db_session, [(moment_id, "addressed")])
    await _over(async_db_session, "done", "Sam owns billing.")
    call.until = asyncio.get_running_loop().time() + 0.2  # what plays
    await answering.answer(async_db_session)
    await answering.said()

    assert answering.saying() == {moment_id}
    await asyncio.sleep(0.25)
    assert answering.saying() == set()
    answering.close()


async def test_her_mic_is_open_from_the_question_until_her_answer_has_played(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Meet opens a mic late: opened as she spoke, each answer, and each
    sentence of one, lost its first words. It opens once a question is put
    to her and closes once the last of her answer has played."""
    import asyncio

    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(call, voice="hers")

    await answering.mic()
    assert not call.mic_open
    await answering.heard(async_db_session, [(moment_id, "addressed")])
    await answering.mic()
    assert call.mic_open
    await _over(async_db_session, "done", "Sam owns billing. Dana owns search.")
    await answering.answer(async_db_session)
    await answering.said()
    call.until = asyncio.get_running_loop().time() + 60
    await answering.mic()
    assert call.mic_open  # still playing
    call.until = float("-inf")
    await answering.mic()

    assert not call.mic_open
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

    await answering.heard(async_db_session, [(moment_id, "addressed")])
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

    await answering.heard(async_db_session, [(moment_id, "addressed"), (moment_id + 99, "question")])
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


async def test_a_stop_is_written_the_moment_it_is_heard(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stop waits on neither the beat nor its speaker's pause: named or
    not, it is written (and stops her) at the next look."""
    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "BEAT_SECONDS", 3600.0)
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 60.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")

    plain = await _took(async_db_session, transcript, [Caption("1", "Dana", "Stop.")])
    named = await _took(
        async_db_session, transcript, [Caption("2", "Dana", "Hey Notes, stop.")]
    )

    assert [kind for _, kind in plain] == ["stop"]
    assert [kind for _, kind in named] == ["stop"]
    # Stopped, what she is told next is put to her only by name.
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    await _took(async_db_session, transcript, [Caption("3", "You", "Then the")])
    after = Caption("4", "Dana", "How does a request reach the database?")
    assert await _took(async_db_session, transcript, [after]) == []


async def test_a_line_begun_over_her_is_written_at_once_and_cuts_in(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Talking over her waits on neither the beat nor a pause: it is written,
    and cuts in, at the next look. Her echo meanwhile waits as ever."""
    import asyncio

    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "BEAT_SECONDS", 3600.0)
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 60.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")
    words = "The deploy failed at four because the cache was cold."
    now = asyncio.get_running_loop().time
    transcript.her = lambda: (now() + 60, words)  # playing

    echo = Caption("1", "Dana", "because the cache")
    assert await _took(async_db_session, transcript, [echo]) == []
    over = Caption("2", "Dana", "Wait, which deploy?")
    made = await _took(async_db_session, transcript, [echo, over])
    assert "cut_in" in [kind for _, kind in made]

    # Once she is quiet, what it grows into waits as ever.
    transcript.her = lambda: (now() - 1, words)
    grown = Caption("2", "Dana", "Wait, which deploy? The one at four?")
    assert transcript.take([echo, grown]) == []


async def test_her_own_words_heard_back_through_a_mic_are_not_put_to_her(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Her speech, picked up by the asker's microphone as she says it, is
    captioned as theirs: words of hers said back while she talks are her
    echo, not asked of her again. The same words said once she is done are
    a reply."""
    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.domains.moments import detectors
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "BEAT_SECONDS", 0.0)
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")
    asked = Caption("1", "Dana", "Hey Notes, which part should I look at?")
    her = Caption("2", "You", "Let me look that up. The scheduler or the worker?")
    await _took(async_db_session, transcript, [asked])
    await _took(async_db_session, transcript, [asked, her])

    echo = await _took(
        async_db_session, transcript, [asked, her, Caption("3", "Dana", "Let me.")]
    )
    monkeypatch.setattr(detectors, "ECHO_SECONDS", -1.0)  # she is done talking
    reply = await _took(
        async_db_session,
        transcript,
        [asked, her, Caption("4", "Dana", "The worker?")],
    )

    assert echo == []
    assert [kind for _, kind in reply] == ["addressed"]


async def test_her_echo_is_told_by_her_words_as_both_are_captioned(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Her caption and its echo under the asker's name grow together: the
    echo, first seen at "Yes,", is held until it settles and then told by
    all she has said by then, not by her first word."""
    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "BEAT_SECONDS", 0.0)
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")
    asked = Caption("1", "Dana", "Notes, can you hear me?")
    await _took(async_db_session, transcript, [asked])

    monkeypatch.setattr(captions, "SETTLE_SECONDS", 60.0)
    await _took(
        async_db_session,
        transcript,
        [asked, Caption("2", "You", "Yes,"), Caption("3", "Dana", "Yes,")],
    )
    said = "Yes, I can hear you clearly."
    for words in ("Yes, I can", "Yes, I can hear", said):
        grown = [asked, Caption("2", "You", words), Caption("3", "Dana", words)]
        await _took(async_db_session, transcript, grown)
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    echo = await _took(async_db_session, transcript, grown)

    assert echo == []
    # Her caption growing is kept once, not once a look.
    assert transcript.before["3"][3].count("hear") == 1


async def test_her_words_heard_back_while_her_voice_plays_are_her_echo(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meet captions her late, or not at all: what she is saying and until
    when is the bot's own (``her``). Her words heard back while it plays
    are her echo; said back once it has played, a reply."""
    import asyncio

    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "BEAT_SECONDS", 0.0)
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")
    words = "Let me look that up. The scheduler or the worker?"
    now = asyncio.get_running_loop().time
    asked = Caption("1", "Dana", "Hey Notes, which part should I look at?")
    await _took(async_db_session, transcript, [asked])

    transcript.her = lambda: (now() + 60, words)  # playing
    echo = await _took(
        async_db_session, transcript, [asked, Caption("2", "Dana", "Let me.")]
    )
    transcript.her = lambda: (now() - 5, words)  # played a while ago
    reply = await _took(
        async_db_session,
        transcript,
        [asked, Caption("3", "Dana", "The worker?")],
    )

    assert echo == []
    assert [kind for _, kind in reply] == ["addressed"]


async def test_a_question_put_to_her_again_at_once_is_asked_once(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meet at times draws one question twice, a second block a moment
    after the first with her name spelled anew, in a way the caption check
    misses (``_drawn_again``): the same speaker putting the same to her
    within ``AGAIN_SECONDS`` is that line again, written over it and asked
    once. Asked again later, it is asked again."""
    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.domains.moments.service import moments_of
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "BEAT_SECONDS", 0.0)
    monkeypatch.setattr(captions, "SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(captions.Transcript, "_drawn_again", lambda *a: None)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")
    first = Caption("1", "Dana", "Notes, how does a request hit the database?")
    again = Caption("2", "Dana", "Nodes, how does a request hit the database?")

    made = await _took(async_db_session, transcript, [first])
    made += await _took(async_db_session, transcript, [first, again])
    lines = set(transcript.rows.values())
    monkeypatch.setattr(captions, "AGAIN_SECONDS", -1.0)  # a while later
    later = Caption("3", "Dana", "Notes, how does a request hit the database?")
    made += await _took(async_db_session, transcript, [first, again, later])

    assert [kind for _, kind in made] == ["addressed", "addressed"]
    assert len(lines) == 1  # one transcript line, Meet's later words
    assert len(await moments_of(async_db_session, meeting_id)) == 2


async def test_a_line_for_her_is_heard_before_it_is_said_in_full(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While a line for her is still being said (held until its speaker
    pauses), it is already hers to show: who is saying it, and what of it
    so far."""
    from app.services.meetings.domains.bot import transcript as captions
    from app.services.meetings.models import Caption

    monkeypatch.setattr(captions, "SETTLE_SECONDS", 60.0)
    meeting_id = await a_meeting(async_db_session)
    transcript = captions.Transcript(meeting_id, "Notes")

    await _took(async_db_session, transcript, [Caption("1", "Dana", "Hey Notes, who")])
    await _took(
        async_db_session, transcript, [Caption("1", "Dana", "Hey Notes, who owns it?")]
    )

    assert transcript.hearing() == [("Dana", "Hey Notes, who owns it?")]


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

    await answering.heard(async_db_session, [(1, "addressed")])

    assert answering.waiting == {}
    answering.close()


async def test_an_answer_she_said_live_is_posted_not_said_again(
    async_db_session: AsyncSession, voiced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live, she is heard as she makes the answer: it is posted in the chat
    and not made into speech again, and nothing is said while she thinks."""
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    answering = answers.Answers(
        call, voice="hers", live=FakeLive(spoken=("Sam owns billing.",))
    )

    await answering.heard(async_db_session, [(moment_id, "addressed")])
    answering.looking_up(None)  # a step of her live call's
    await answering.answer(async_db_session)  # looking, but she is talking already
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
        async def resolve(self, session: Any, key: str) -> Any:
            asked.append(key)
            return SimpleNamespace(key=key)

    from app.services.meetings.domains.actions.registry import ANSWERS

    monkeypatch.setattr(voice, "answerer", lambda: ANSWERS)  # she answers
    monkeypatch.setattr(
        voice, "optional", lambda name: SimpleNamespace(live_engines=Engines())
    )
    profile = SimpleNamespace(VOICE_LIVE_ENGINE="gpt-realtime-2.1-mini")

    engine = await voice.live_engine_of(None, profile)  # type: ignore[arg-type]
    assert engine.key == "gpt-realtime-2.1-mini"
    assert asked == ["gpt-realtime-2.1-mini"]
    assert await voice.live_engine_of(None, None) is None  # type: ignore[arg-type]
    monkeypatch.setattr(voice, "answerer", lambda: "agent")  # a coding agent answers
    assert await voice.live_engine_of(None, profile) is None  # type: ignore[arg-type]


async def test_her_live_call_is_told_she_is_in_the_meeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Her live call's manners are a meeting's (``IN_A_MEETING``), not a
    call with one person's: one of several, heard through the captions,
    seen as a card, so asked whether she can hear she says so."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from app.services.meetings.domains.actions.live import IN_A_MEETING
    from app.services.meetings.domains.bot import voice

    told: dict[str, Any] = {}

    @asynccontextmanager
    async def live_voice(ai: Any, **how: Any) -> Any:
        told.update(how)
        yield None

    async def hush() -> None:
        return None

    ai = SimpleNamespace(live_voice=live_voice, AIService=lambda settings: object())
    monkeypatch.setattr(voice, "optional", lambda name: ai)
    call = SimpleNamespace(stream=None, hush=hush)
    her = SimpleNamespace(TTS_VOICE="marin")

    async with voice.live(call, her, SimpleNamespace(key="gpt-realtime-2.1"), None):
        pass

    assert told["instructions"] == IN_A_MEETING


async def test_without_a_voice_there_is_no_live_voice() -> None:
    from app.services.meetings.domains.bot import voice

    async with voice.live(FakeCall([CallState.IN_CALL]), None, None, None) as live:
        assert live is None and voice.LIVE.get() is None


async def test_told_to_stop_she_drops_everything_and_listens_again(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """A stop while she answers: the answer owed is never said, what is
    playing is cut off, her live answer is stopped and her mic closed; the
    next question put to her is answered as ever."""
    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    live = FakeLive()
    answering = answers.Answers(call, voice="hers", live=live)
    await answering.heard(async_db_session, [(moment_id, "addressed")])
    await answering.mic()

    await answering.heard(async_db_session, [(moment_id + 1, "stop")])
    await answering.answer(async_db_session)
    await answering.said()

    assert call.said == [] and call.spoken == []
    assert call.silenced and live.stopped and not call.mic_open
    assert answering.saying() == set() and not answering.waiting
    (run,) = (await async_db_session.exec(select(MeetingActionRun))).all()
    assert (run.status, run.result) == ("failed", runs.STOPPED)
    await answering.heard(async_db_session, [(moment_id, "addressed")])
    assert answering.waiting
    answering.close()


class _Playing(FakeCall):
    """A call each sentence said into plays for the next of ``lengths``
    seconds, after what it plays already."""

    def __init__(self, *lengths: float) -> None:
        super().__init__([CallState.IN_CALL])
        self.lengths = list(lengths)

    async def speak(self, audio: bytes) -> None:
        import asyncio

        await super().speak(audio)
        now = asyncio.get_running_loop().time()
        self.until = max(self.until, now) + self.lengths.pop(0)


async def _saying(
    db: AsyncSession, call: FakeCall, answer: str, live: Any = None
) -> tuple[answers.Answers, int]:
    """Her answer to the one question put to her, being said into ``call``."""
    import asyncio

    _, moment_id = await asked_a_question(db, lines=HER)
    answering = answers.Answers(call, voice="hers", live=live)
    await answering.heard(db, [(moment_id, "addressed")])
    await _over(db, "done", answer)
    if live is not None:
        call.until = asyncio.get_running_loop().time() + 60
    await answering.answer(db)
    await answering.said()
    return answering, moment_id


async def test_cut_in_on_she_goes_quiet_and_goes_on_when_told(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Talked over, she stops where she has been heard to and listens; told
    to go on, she says the rest, from the sentence she was cut off in."""
    call = _Playing(0.0, 60.0, 60.0)  # the first sentence heard already
    answering, moment_id = await _saying(async_db_session, call, "One. Two. Three.")

    await answering.heard(async_db_session, [(moment_id + 1, "cut_in")])
    await answering.mic()
    assert call.silenced and not call.mic_open and answering.saying() == set()
    call.lengths = [1.0, 1.0]
    await answering.heard(async_db_session, [(moment_id + 2, "go_on")])
    await answering.said()

    assert call.spoken == [b"One.", b"Two.", b"Three.", b"Two.", b"Three."]
    assert call.said == ["One. Two. Three."]  # in the chat once, all of it
    answering.close()


async def test_a_question_after_a_cut_in_drops_the_rest(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Cut in on with a new question, she answers that: what she was
    saying is not gone on with."""
    call = _Playing(60.0, 60.0)
    answering, moment_id = await _saying(async_db_session, call, "One. Two.")

    await answering.heard(
        async_db_session, [(moment_id + 1, "cut_in"), (moment_id + 2, "addressed")]
    )
    await answering.heard(async_db_session, [(moment_id + 3, "go_on")])
    await answering.said()

    assert call.spoken == [b"One.", b"Two."]
    assert moment_id + 2 in answering.waiting
    answering.close()


async def test_told_to_go_on_said_back_is_not_asked_too(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Said back to her, "Sorry, carry on." is a reply as well as a go-on:
    cut in on, it is only the go-on."""
    call = _Playing(60.0)
    answering, moment_id = await _saying(async_db_session, call, "One.")

    await answering.heard(async_db_session, [(moment_id + 1, "cut_in")])
    call.lengths = [1.0]
    told = [(moment_id + 2, "addressed"), (moment_id + 3, "go_on")]
    await answering.heard(async_db_session, told)
    await answering.said()

    assert moment_id + 2 not in answering.waiting
    assert call.spoken == [b"One.", b"One."]
    answering.close()


async def test_cut_in_on_live_she_is_asked_to_carry_on(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Live, her answer is cut where it was heard to in her call (``stop``),
    and going on is hers: asked to carry on from there."""
    call = FakeCall([CallState.IN_CALL])
    live = FakeLive(spoken=("One. Two.",))
    answering, moment_id = await _saying(async_db_session, call, "One. Two.", live)

    await answering.heard(async_db_session, [(moment_id + 1, "cut_in")])
    assert live.stopped and call.silenced
    await answering.heard(async_db_session, [(moment_id + 2, "go_on")])
    assert answering.going_on is not None
    await answering.going_on

    assert live.asked == [answers.CARRY_ON]
    answering.close()


async def test_cut_in_on_live_while_her_answer_is_still_made(
    async_db_session: AsyncSession, voiced: None
) -> None:
    """Live, she is heard as she makes her answer, before its run is back:
    cut in on then, she stops, and what she says going on is posted."""
    import asyncio

    _, moment_id = await asked_a_question(async_db_session, lines=HER)
    call = FakeCall([CallState.IN_CALL])
    live = FakeLive("Sam owns billing.")
    answering = answers.Answers(call, voice="hers", live=live)
    await answering.heard(async_db_session, [(moment_id, "addressed")])
    call.until = asyncio.get_running_loop().time() + 60  # her voice playing

    await answering.heard(async_db_session, [(moment_id + 1, "cut_in")])
    await _over(async_db_session, "done", "")  # cut off: nothing came back
    await answering.answer(async_db_session)
    await answering.heard(async_db_session, [(moment_id + 2, "go_on")])
    assert answering.going_on is not None
    await answering.going_on

    assert live.stopped and call.said == ["Sam owns billing."]
    answering.close()
