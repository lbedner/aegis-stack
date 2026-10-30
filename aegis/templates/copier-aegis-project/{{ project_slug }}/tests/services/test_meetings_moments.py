"""Moments: what is heard in a call that something can be done with. A
detector per kind reads each line as the bot writes it, and again as it
grows; the first kind is a question someone other than the owner asks."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.moments import detectors
from app.services.meetings.domains.moments.detectors import Heard, register_detector
from app.services.meetings.domains.moments.service import find_again, moments_of
from app.services.meetings.domains.moments.tidy import meeting_ids_of
from app.services.meetings.domains.notes.queries import delete_in
from app.services.meetings.models import Caption, MeetingActionRun, MeetingMoment
from app.services.meetings.service import MeetingsService, write_captions
from tests._meetings import (
    MEET,
    a_meeting,
    hold_the_answers,
    kept_series,
    said,
    someone_else,
    topic,
)


async def test_a_question_someone_asks_is_a_moment(
    async_db_session: AsyncSession,
) -> None:
    meeting_id = await a_meeting(async_db_session)

    lines = await said(
        async_db_session,
        meeting_id,
        ("Dana", "The report is late."),
        ("Dana", "Can we ship the CSV export this week?"),
    )

    (moment,) = await moments_of(async_db_session, meeting_id)
    assert moment.kind == "question"
    assert moment.line_id == lines[1]
    assert moment.speaker == "Dana"
    assert moment.text == "Can we ship the CSV export this week?"


async def test_the_owners_own_question_is_not(async_db_session: AsyncSession) -> None:
    meeting_id = await a_meeting(async_db_session)
    await said(async_db_session, meeting_id, ("Sam", "Hi."))
    await MeetingsService(async_db_session, None).set_me(meeting_id, "Sam")

    await said(async_db_session, meeting_id, ("Sam", "Is everyone here?"))

    assert await moments_of(async_db_session, meeting_id) == []


async def test_a_line_that_grows_into_a_question_becomes_one_and_follows_it(
    async_db_session: AsyncSession,
) -> None:
    """A caption keeps growing while its speaker talks: the moment appears
    when the line turns into a question, and its text follows the line."""
    meeting_id = await a_meeting(async_db_session)
    rows: dict[str, int] = {}

    async def caption(text: str, at: float) -> None:
        line = Caption("1", "Dana", text)
        await write_captions(async_db_session, meeting_id, [line], rows, at, {"1": 0.0})

    await caption("So the export", 1.0)
    assert await moments_of(async_db_session, meeting_id) == []
    await caption("So the export, can it ship?", 2.0)
    await caption("So the export, can it ship this week?", 3.0)

    (moment,) = await moments_of(async_db_session, meeting_id)
    assert moment.text == "So the export, can it ship this week?"


async def test_a_detector_registered_for_a_kind_finds_its_moments(
    async_db_session: AsyncSession,
) -> None:
    """Moments are not only questions: any kind a detector is registered
    for is found the same way."""
    register_detector(
        "mention",
        lambda heard: heard.text if "GridCo" in heard.text else None,
        replace=True,
    )
    try:
        meeting_id = await a_meeting(async_db_session)
        await said(async_db_session, meeting_id, ("Tom", "GridCo moves to OAuth."))

        (moment,) = await moments_of(async_db_session, meeting_id)
        assert (moment.kind, moment.text) == ("mention", "GridCo moves to OAuth.")
    finally:
        detectors.unregister_detector("mention")


async def test_questions_asked_close_together_are_one(
    async_db_session: AsyncSession,
) -> None:
    """A burst of questions on one thing (a question, its follow-up, a
    fragment) is one: led by the first, the rest with it, and a prompt
    that has them all; a question asked minutes later is its own."""
    meeting_id = await a_meeting(async_db_session)
    first, _, follow, later = await said(
        async_db_session,
        meeting_id,
        ("Dana", "Can the export ship this week?"),
        ("Tom", "It depends on billing."),
        ("Dana", "Did billing sign off on it?"),
        ("Priya", "How long has delivery taken?"),
        at=[0.0, 20.0, 40.0, 400.0],
    )

    led, alone = await moments_of(async_db_session, meeting_id)

    assert (led.line_id, [m.line_id for m in led.also]) == (first, [follow])
    assert (alone.line_id, alone.also) == (later, [])
    copy = next(a for a in led.actions if a.where == "browser")
    assert "export ship" in (copy.prompt or "") and "billing sign off" in (
        copy.prompt or ""
    )
    assert "It depends on billing." in (copy.prompt or "")


async def test_questions_on_one_topic_are_one_card_wherever_said(
    async_db_session: AsyncSession,
) -> None:
    """Once questions carry a topic (the model's clean-up), one topic is one
    card, however far apart in the call they were asked, under its topic."""
    meeting_id = await a_meeting(async_db_session)
    early, late = await said(
        async_db_session,
        meeting_id,
        ("Dana", "How do members return a scale?"),
        ("Tom", "What does the assistant say about returns?"),
        apart=900.0,
    )
    found = await moments_of(async_db_session, meeting_id)
    await topic(async_db_session, [m.id for m in found], "Scale returns")

    (card,) = await moments_of(async_db_session, meeting_id)

    assert card.topic == "Scale returns"
    assert (card.line_id, [m.line_id for m in card.also]) == (early, [late])


async def test_past_meetings_are_looked_over_again(
    async_db_session: AsyncSession,
) -> None:
    """A meeting kept before a detector (or before it changed) is read
    again: a question it now finds is made, and one it no longer finds goes,
    unless something was already asked of it."""
    meeting_id = await a_meeting(async_db_session)
    real, noise, asked = await said(
        async_db_session,
        meeting_id,
        ("Dana", "Can the export ship this week?"),
        ("Tom", "Right?"),
        ("Tom", "Okay?"),
    )
    await delete_in(async_db_session, MeetingMoment.meeting_id, [meeting_id])
    # As a looser detector once kept them: the noise, and one asked of.
    stale = MeetingMoment(
        meeting_id=meeting_id, line_id=noise, kind="question", text="Right?"
    )
    kept = MeetingMoment(
        meeting_id=meeting_id, line_id=asked, kind="question", text="Okay?"
    )
    async_db_session.add_all([stale, kept])
    await async_db_session.flush()
    async_db_session.add(
        MeetingActionRun(moment_id=kept.id or 0, action="agent", prompt="?")
    )
    await async_db_session.commit()

    await find_again(async_db_session, [meeting_id])

    found = await moments_of(async_db_session, meeting_id)
    lines = [m.line_id for led in found for m in [led, *led.also]]
    assert sorted(lines) == sorted([real, asked])


async def test_a_call_still_going_is_not_read_over(
    async_db_session: AsyncSession,
) -> None:
    """While the bot is in, its moments are its own to keep: looking the
    call over then would drop what it is still adding."""
    from app.services.meetings.domains.moments.tidy import look_over
    from app.services.meetings.models import MeetingStatus
    from app.services.meetings.service import NOT_DONE, transition

    meeting_id = await a_meeting(async_db_session)
    (noise,) = await said(async_db_session, meeting_id, ("Tom", "Right?"))
    await transition(
        async_db_session, meeting_id, MeetingStatus.IN_CALL, from_=NOT_DONE
    )
    async_db_session.add(
        MeetingMoment(
            meeting_id=meeting_id, line_id=noise, kind="question", text="Right?"
        )
    )
    await async_db_session.commit()

    await look_over(async_db_session, [meeting_id])

    (kept,) = await moments_of(async_db_session, meeting_id)
    assert kept.line_id == noise


async def test_a_series_or_every_meeting_is_read_over(
    async_db_session: AsyncSession,
) -> None:
    """What ``find_again`` is handed for a series: its meetings, every one
    on its link however it was pasted; or every meeting."""
    svc = MeetingsService(async_db_session, None)
    first = await svc.request(MEET, "Notes")
    again = await svc.request(f"{MEET}?authuser=0", "Notes")
    elsewhere = await svc.request("https://meet.google.com/zzz-zzzz-zzz", "Notes")
    theirs = await MeetingsService(
        async_db_session, await someone_else(async_db_session)
    ).request(MEET, "Notes")
    series_id = await kept_series(async_db_session, None)

    on_it = await meeting_ids_of(async_db_session, series_id)
    every = await meeting_ids_of(async_db_session)

    # A series is its owner's: another owner's meeting on the link is not in it.
    assert sorted(on_it) == sorted([first.id, again.id])
    assert sorted(every) == sorted([first.id, again.id, elsewhere.id, theirs.id])
    with pytest.raises(LookupError):
        await meeting_ids_of(async_db_session, 0)


def test_what_a_detector_reads() -> None:
    """A detector sees one line: who said it, whether that is the owner,
    and what was said so far."""
    heard = Heard(line_id=1, speaker="Dana", text="Is it ready?", is_me=False)

    assert detectors.question(heard) == "Is it ready?"
    assert detectors.question(Heard(1, "Sam", "Is it ready?", is_me=True)) is None
    assert detectors.question(Heard(1, "Dana", "It is ready.", is_me=False)) is None


@pytest.mark.parametrize(
    "said",
    [
        "Did that ship?",
        "We're not shipping the trackers, right?",
        "The rollout slipped. How long has delivery taken on average?",
        "We could ask them on sign-up, what do they wear?",
        "Thank you. How long has delivery taken?",
        "So, you know, how does the export work?",
        "What is the assistant saying when they ask for a return?",
    ],
)
def test_a_question_is_asked_as_one(said: str) -> None:
    """The last sentence asks: it opens on a question word or an auxiliary
    (a clause of it may), or it ends on a tag (``..., right?``)."""
    assert detectors.question(Heard(1, "Dana", said, is_me=False)) == said


@pytest.mark.parametrize(
    "said",
    [
        "Right?",
        "Correct?",
        "So, so?",
        "Okay, um?",
        "Also okay?",
        "Catch okay?",
        "No, no, no, no?",
        "Doesn't change much. Okay?",
        "And from the warehouse, okay?",
        "Oh, okay. Got you understood it?",
    ],
)
def test_a_rising_tone_is_not_a_question(said: str) -> None:
    """Captions end anything said with a rising tone in a question mark:
    a filler, a yes or no, or a statement that trails off is not asked."""
    assert detectors.question(Heard(1, "Dana", said, is_me=False)) is None


PEOPLE = frozenset({"Dana Okafor", "Tom Becker", "Priya Shah"})


@pytest.mark.parametrize(
    "said",
    [
        "Is Priya to check on? Or let Tom how many trackers have we sent out, "
        "and how many have actually, uh? Have been giving readings back?",
        "Okay, okay. Do you think that we need?",
        "Tom, can you send that over?",
        "Okay, so um, can, can you send Priya the login?",
        "So, when you say billing, is it the yearly plan?",
        "Wait, what do you mean by that?",
        "Uh, can I say something?",
        "Is that correct Tom?",
    ],
)
def test_a_question_asked_of_someone_in_the_call_is_theirs(said: str) -> None:
    """Asked of a person (by name, or as *you*), or asking leave: theirs to
    answer, not an agent's."""
    heard = Heard(1, "Dana Okafor", said, is_me=False, people=PEOPLE)
    assert detectors.question(heard) is None


@pytest.mark.parametrize(
    ("said", "asked"),
    [
        (
            "Hey Illiana, what did we decide about the launch?",
            "what did we decide about the launch?",
        ),
        (
            "Eliana, can you check what the worker is doing?",
            "can you check what the worker is doing?",
        ),
        ("Hey illiana. How you doing?", "How you doing?"),
        ("Hey Illiana, how's it going?", "how's it going?"),
        (  # captioned as asked, though it opens on no question word
            "So Illiana, um, if redis goes down? Uh, what happens?",
            "um, if redis goes down? Uh, what happens?",
        ),
        (
            "So Iliana tell me who owns the billing service.",
            "tell me who owns the billing service.",
        ),
        (
            "What would break if Redis went down, Illiana?",
            "What would break if Redis went down?",
        ),
        (  # talking on past the question, in the same line
            "Illiana, what are you all about? She wasn't gonna get that.",
            "what are you all about? She wasn't gonna get that.",
        ),
        ("Hey Illiana is Redis up?", "is Redis up?"),  # a greeting: to her
        (  # a pause captioned as a question mark mid-question
            "Ileana, can you tell me how? Request gets from the traffic layer.",
            "can you tell me how? Request gets from the traffic layer.",
        ),
    ],
)
def test_a_line_put_to_the_bot_by_name_wakes_it(said: str, asked: str) -> None:
    """Captions spell her as they hear her (Iliana, Eliana): a line that
    opens on her name, after a greeting at most, or closes on it, and asks
    something, is put to her; what she is asked is the rest of it."""
    heard = Heard(1, "Dana", said, is_me=False, addressee="Illiana")

    assert detectors.addressed(heard) == asked


@pytest.mark.parametrize(
    "said",
    [
        "I know he built Iliana to listen to the calls.",  # about her
        "Right or actually is Eliana on here?",  # about her
        "Good morning, Illiana.",  # nothing asked
        "Hey Illiana, what did",  # not said to its end yet
        # her name who the line is about, said to someone else
        "So, so Iliana is actually, uh, going to this website and the one good"
        " thing about Google meet is that all of this?",
        "And Illiana has the logs open, right?",
    ],
)
def test_a_line_about_the_bot_or_asking_nothing_does_not(said: str) -> None:
    heard = Heard(1, "Dana", said, is_me=False, addressee="Illiana")

    assert detectors.addressed(heard) is None


def test_only_a_speaker_who_may_wake_the_bot_does() -> None:
    """``addressee`` is the bot's name only where that speaker may wake it
    (anyone, or only the owner: its agent's setting) and is not the bot."""
    heard = Heard(1, "Dana", "Hey Illiana, who owns billing?", is_me=False)

    assert detectors.addressed(heard) is None


def test_a_line_said_back_to_the_bot_is_put_to_it_without_its_name() -> None:
    """Right after it spoke, a reply needs no "Hey Illiana" again: what
    is said back (asked or not) is put to it."""
    asked = "Can you tell us how a request reaches the database?"
    told = "The one from the traffic layer."

    def back(
        text: str, replying: bool = True, addressee: str = "Illiana"
    ) -> str | None:
        people = frozenset({"Dana", "Lawrence Casely-Hayford"})
        return detectors.addressed(
            Heard(1, "Dana", text, False, people, addressee, replying=replying)
        )

    assert back(asked) == asked and back(told) == told
    assert back(asked, replying=False) is None
    assert back(asked, addressee="") is None  # one who may not wake it
    assert back("Okay.") is None  # a sound, not a reply
    assert back("And the database.") == "And the database."  # short, still asks
    assert back("Thank you.") is None and back("Got it, thanks!") is None
    # Said to another in the call (by name), or about it (*she*): not back.
    assert back("Were you able to hear that Lawrence?") is None
    assert back("No, she's only supposed to listen to me.") is None


@pytest.mark.parametrize(
    "said",
    [
        "Hey Illiana, stop.",
        "Stop.",
        "Illiana, be quiet.",
        "Okay, that's enough.",
        "Stop, stop, stop.",
        "Shut up, Illiana.",
        "Never mind",
        "Illiana stop talking",
        "No, no. Stop.",
    ],
)
def test_one_who_may_wake_the_bot_stops_it(said: str) -> None:
    """A stop, said by itself (her name and a greeting at most beside it),
    stops her: at once, not waiting for the caption to end, and it is
    never a question put to her."""
    heard = Heard(1, "Leonard", said, True, addressee="Illiana", replying=True)

    assert detectors.stop(heard) == said
    assert detectors.addressed(heard) is None


def test_a_stop_counts_only_from_one_who_may_wake_the_bot_and_alone() -> None:
    def stop(text: str, addressee: str = "Illiana") -> str | None:
        return detectors.stop(Heard(1, "Leonard", text, True, addressee=addressee))

    assert stop("Stop.", addressee="") is None  # one who may not wake her
    assert stop("Stop the deploy and tell me why it failed.") is None
    assert stop("We should stop for lunch.") is None


@pytest.fixture
def her_answer_held(monkeypatch: pytest.MonkeyPatch) -> None:
    hold_the_answers(monkeypatch)


async def test_a_line_put_to_the_bot_is_its_moment_not_a_question(
    async_db_session: AsyncSession, her_answer_held: None
) -> None:
    meeting_id = await a_meeting(async_db_session)  # the bot joins as "Notes"

    await said(async_db_session, meeting_id, ("Dana", "Hey Notes, who owns billing?"))

    (moment,) = await moments_of(async_db_session, meeting_id)
    assert (moment.kind, moment.text) == ("addressed", "who owns billing?")


async def test_an_agent_that_answers_only_its_owner_is_woken_only_by_them(
    async_db_session: AsyncSession, her_answer_held: None
) -> None:
    from app.services.meetings.models import BotAccount

    agent = BotAccount(name="work", display_name="Notes", login_secret="X")
    async_db_session.add(agent)
    await async_db_session.commit()
    meeting = await MeetingsService(async_db_session, None).request(
        MEET, "Notes", account_id=agent.id
    )
    meeting_id = meeting.id or 0
    await said(async_db_session, meeting_id, ("Sam", "Hi."))
    await MeetingsService(async_db_session, None).set_me(meeting_id, "Sam")

    await said(async_db_session, meeting_id, ("Dana", "Hey Notes, who owns billing?"))
    await said(async_db_session, meeting_id, ("Sam", "Hey Notes, who owns search?"))

    kinds = [(m.kind, m.text) for m in await moments_of(async_db_session, meeting_id)]
    assert ("addressed", "who owns search?") in kinds
    assert ("addressed", "who owns billing?") not in kinds


async def test_each_question_put_to_the_bot_is_its_own_card(
    async_db_session: AsyncSession, her_answer_held: None
) -> None:
    """Questions asked close together are one card; questions put to her by
    name are each answered."""
    from app.services.meetings.domains.moments.service import cards_of

    meeting_id = await a_meeting(async_db_session)
    await said(
        async_db_session,
        meeting_id,
        ("Dana", "Hey Notes, who owns billing?"),
        ("Dana", "Hey Notes, who owns search?"),
    )

    cards = await cards_of(async_db_session, meeting_id)
    assert len({id(card) for card in cards.values()}) == 2


async def test_what_its_asker_says_right_after_the_bot_is_put_to_it(
    async_db_session: AsyncSession, her_answer_held: None
) -> None:
    """Only from the one it answered: someone else talking just after it
    is not talking to it."""
    meeting_id = await a_meeting(async_db_session)

    await said(
        async_db_session,
        meeting_id,
        ("Dana", "Hey Notes, how does a request get in?"),
        ("You", "Could you finish the question?"),
        ("Dana", "How does a request reach the database?"),
        ("You", "Through the gateway, then the API."),
        ("Sam", "Can we move on to lunch now?"),
        apart=2.0,
    )

    kinds = [(m.kind, m.text) for m in await moments_of(async_db_session, meeting_id)]
    assert ("addressed", "How does a request reach the database?") in kinds
    assert ("addressed", "Can we move on to lunch now?") not in kinds


async def test_after_a_stop_what_its_asker_says_next_is_not_put_to_it(
    async_db_session: AsyncSession, her_answer_held: None
) -> None:
    """Stopped, she listens again: only her name wakes her, not the window
    after her last words. A stop is no moment of the meeting to list."""
    meeting_id = await a_meeting(async_db_session)

    await said(
        async_db_session,
        meeting_id,
        ("Dana", "Hey Notes, how does a request get in?"),
        ("You", "Through the gateway, then the API."),
        ("Dana", "Stop."),
        ("You", "Then the"),
        ("Dana", "How does a request reach the database?"),
        apart=2.0,
    )

    kinds = [m.kind for m in await moments_of(async_db_session, meeting_id)]
    assert kinds == ["addressed", "question"]  # the room's question, not hers
