"""The meeting bot's run (``domains.bot.run.run_meeting``): it asks to join, waits to be
admitted, says who it is, stays until there is a reason to leave, and
writes each step on the meeting row, never over a leave request or a
failure written elsewhere. A scripted call stands in for the browser; the
Meet page itself is tested against a fake page (``test_meet_page``)."""

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.meetings.domains.accounts import service as accounts
from app.services.meetings.domains.bot import card, voice
from app.services.meetings.domains.bot import run as bot
from app.services.meetings.domains.bot.meet import CallState
from app.services.meetings.models import (
    CLAIMED,
    Caption,
    Meeting,
    MeetingActionRun,
    MeetingParticipant,
    MeetingStatus,
)
from app.services.meetings.service import MeetingsService, transition
from tests._meetings import (
    MEET,
    SAID,
    SHOWN,
    FakeCall,
    asked_a_question,
    bot_on,
)

# The run beats on every look here (BEAT_SECONDS is 0), by design.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)


@pytest.fixture
def run(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Any]:
    """Run the bot against ``call`` on a meeting (a new Meet meeting unless
    given), without waiting between looks; returns the meeting after."""

    async def go(
        call: FakeCall,
        meeting: Meeting | None = None,
        notes: Callable[[int], Any] | None = None,
    ) -> Meeting:
        if meeting is None:
            meeting = await MeetingsService(async_db_session, None).request(
                MEET, "Notes"
            )
        bot_on(monkeypatch, async_db_session, call, notes=notes)
        await bot.run_meeting(meeting.id)  # type: ignore[arg-type]
        await async_db_session.refresh(meeting)
        return meeting

    return go


@pytest.fixture
def meeting(async_db_session: AsyncSession) -> Callable[..., Any]:
    async def make() -> Meeting:
        return await MeetingsService(async_db_session, None).request(MEET, "Notes")

    return make


async def test_it_joins_announces_itself_and_leaves_when_the_call_ends(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    moved: list[MeetingStatus] = []

    async def recorded(*args: Any, **kwargs: Any) -> bool:
        applied = await transition(*args, **kwargs)
        if applied:
            moved.append(args[2])
        return applied

    monkeypatch.setattr(bot, "transition", recorded)
    call = FakeCall([CallState.WAITING, CallState.IN_CALL, CallState.ENDED])

    meeting: Meeting = await run(call)

    assert call.asked_as == "Notes"
    assert moved == [
        MeetingStatus.JOINING,
        MeetingStatus.WAITING,
        MeetingStatus.IN_CALL,
        MeetingStatus.LEFT,
    ]
    assert call.said and call.said[0].startswith("Notes is taking notes")
    assert meeting.joined_at and meeting.left_at and meeting.seen_at
    assert meeting.failure_reason is None
    assert not call.left  # the call was already over


async def test_it_announces_itself_as_set_and_always_says_it_transcribes(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Who it says it is comes from ``MEETINGS_ANNOUNCEMENT`` (``{name}`` the
    name it joins as); that the call is transcribed is said whatever it is
    set to."""
    monkeypatch.setattr(
        settings, "MEETINGS_ANNOUNCEMENT", "{name}, envoy of His Grace, is here"
    )
    call = FakeCall([CallState.IN_CALL, CallState.ENDED])

    await run(call)

    assert call.said[0] == (
        "Notes, envoy of His Grace, is here. What is said here is transcribed."
    )


async def test_a_refused_join_fails_with_the_reason(run: Callable[..., Any]) -> None:
    meeting: Meeting = await run(FakeCall([CallState.WAITING, CallState.REFUSED]))

    assert meeting.status == MeetingStatus.FAILED
    assert "refused" in (meeting.failure_reason or "")


async def test_nobody_admitting_it_fails_after_the_wait(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bot, "ADMIT_TIMEOUT_SECONDS", 0)

    meeting: Meeting = await run(FakeCall([CallState.WAITING]))

    assert meeting.status == MeetingStatus.FAILED
    assert "admitted" in (meeting.failure_reason or "")


async def test_left_alone_it_leaves(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bot, "ALONE_SECONDS", 0)
    call = FakeCall([CallState.IN_CALL], people=[3, 1])

    meeting: Meeting = await run(call)

    assert call.left and meeting.status == MeetingStatus.LEFT


async def test_in_early_it_waits_for_the_others_to_come(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The calendar sends the bot a minute early and people come late:
    alone before anyone came is not left alone. It leaves once they have
    come and gone."""
    monkeypatch.setattr(bot, "ALONE_SECONDS", 0)
    call = FakeCall([CallState.IN_CALL], people=[1, 1, 1, 3, 1])

    meeting: Meeting = await run(call)

    assert call.counts == [1], "left before anyone came"
    assert call.left and meeting.status == MeetingStatus.LEFT


async def test_people_talking_are_there_whatever_meet_counts(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meet's People count can read 1 in a call with others in it: while
    their captions move, the bot is not alone."""
    monkeypatch.setattr(bot, "ALONE_SECONDS", 0)
    monkeypatch.setattr(bot, "WAIT_FOR_OTHERS_SECONDS", 0)
    talk = [
        [Caption("1", "William", "Good")],
        [Caption("1", "William", "Good morning")],
        [Caption("1", "William", "Good morning, all.")],
        [],
    ]
    call = FakeCall([CallState.IN_CALL], people=[1], captions=talk)

    meeting: Meeting = await run(call)

    assert call.shown == [[]], "left while they were talking"
    assert call.left and meeting.status == MeetingStatus.LEFT


async def test_a_moment_the_page_does_not_look_like_the_call_is_not_its_end(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Something put over the call (someone joining, a prompt) can hide
    Leave for a look: the bot stays unless it stays that way."""
    monkeypatch.setattr(bot, "GONE_SECONDS", 3600)
    monkeypatch.setattr(bot, "ALONE_SECONDS", 0)
    call = FakeCall(
        [CallState.IN_CALL, CallState.WAITING, CallState.IN_CALL], people=[3, 3, 1]
    )

    meeting: Meeting = await run(call)

    assert call.states == [CallState.IN_CALL], "left on a moment's look"
    assert call.left and meeting.status == MeetingStatus.LEFT


async def test_a_call_nobody_comes_to_it_leaves_in_the_end(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bot, "WAIT_FOR_OTHERS_SECONDS", 0)

    call = FakeCall([CallState.IN_CALL], people=[1])
    meeting: Meeting = await run(call)

    assert call.left and meeting.status == MeetingStatus.LEFT


async def test_asked_to_leave_in_the_call_it_leaves(
    run: Callable[..., Any], meeting: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    row: Meeting = await meeting()
    svc = MeetingsService(async_db_session, None)
    call = FakeCall(
        [CallState.IN_CALL], during={"say": lambda: svc.ask_to_leave(row.id)}
    )

    after: Meeting = await run(call, row)

    assert call.left and after.status == MeetingStatus.LEFT


async def test_asked_to_leave_before_it_starts_it_never_joins(
    run: Callable[..., Any], meeting: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    """Left at once: no run has it yet, and one that comes for it later
    finds it taken."""
    row: Meeting = await meeting()
    await MeetingsService(async_db_session, None).ask_to_leave(row.id)  # type: ignore[arg-type]
    assert (await _status(async_db_session, row)) == MeetingStatus.LEFT
    call = FakeCall([CallState.IN_CALL])

    after: Meeting = await run(call, row)

    assert call.asked_as is None
    assert after.status == MeetingStatus.LEFT


async def test_a_meeting_another_run_has_is_left_to_it(
    run: Callable[..., Any], meeting: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    """A run handed the same meeting twice (a worker that died, its job
    delivered again) finds it taken: no second bot, no notes, and the row
    as the first run (or the stale sweep) leaves it."""
    row: Meeting = await meeting()
    await transition(
        async_db_session,
        row.id,  # type: ignore[arg-type]
        MeetingStatus.IN_CALL,
        from_=(MeetingStatus.REQUESTED,),
    )
    written: list[int] = []

    async def write(meeting_id: int) -> None:
        written.append(meeting_id)

    call = FakeCall([CallState.IN_CALL])

    after: Meeting = await run(call, row, notes=write)

    assert call.asked_as is None and not written
    assert after.status == MeetingStatus.IN_CALL


async def test_a_long_failure_is_kept_cut_to_fit(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Playwright's errors carry their whole call log: kept whole, the
    failure was refused by Postgres and the meeting never said it failed."""
    from app.services.meetings.models import MOST_ERROR_CHARS

    async def stuck(*args: Any, **kwargs: Any) -> None:
        raise TimeoutError("Locator.click: Timeout 5000ms exceeded." + " log" * 300)

    monkeypatch.setattr(bot, "_join", stuck)
    meeting = await run(FakeCall([CallState.IN_CALL]))

    assert meeting.status == MeetingStatus.FAILED
    reason = meeting.failure_reason or ""
    assert reason.startswith("Locator.click") and len(reason) <= MOST_ERROR_CHARS


async def test_a_bot_that_cannot_be_started_fails_the_meeting_with_why(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing will ever run it, so it says so instead of waiting."""

    async def no_broker(meeting_id: int) -> None:
        raise ConnectionError("no broker")

    monkeypatch.setattr(bot, "start_meeting", no_broker)

    sent = await bot.send_bot(MeetingsService(async_db_session, None), MEET, "")
    sent_id: int = sent.id  # type: ignore[assignment]

    async_db_session.expire_all()
    failed = await MeetingsService(async_db_session, None).get(sent_id)
    assert failed.status == MeetingStatus.FAILED
    assert "no broker" in (failed.failure_reason or "")


async def test_a_leave_asked_while_joining_is_not_overwritten(
    run: Callable[..., Any], meeting: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    row: Meeting = await meeting()
    svc = MeetingsService(async_db_session, None)
    call = FakeCall(
        [CallState.IN_CALL], during={"ask_to_join": lambda: svc.ask_to_leave(row.id)}
    )

    after: Meeting = await run(call, row)

    assert not call.said
    assert after.status == MeetingStatus.LEFT


async def test_a_failure_written_elsewhere_stops_the_run_and_stands(
    run: Callable[..., Any], meeting: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    row: Meeting = await meeting()

    async def failed_elsewhere() -> None:
        await transition(
            async_db_session,
            row.id,  # type: ignore[arg-type]
            MeetingStatus.FAILED,
            from_=(MeetingStatus.IN_CALL,),
            reason="Failed by another process",
        )

    call = FakeCall([CallState.IN_CALL], during={"say": failed_elsewhere})

    after: Meeting = await run(call, row)

    assert call.left
    assert after.status == MeetingStatus.FAILED
    assert after.failure_reason == "Failed by another process"


async def test_a_broken_call_fails_with_the_error(run: Callable[..., Any]) -> None:
    class Broken(FakeCall):
        async def ask_to_join(self, bot_name: str) -> None:
            raise RuntimeError("the page never loaded")

    meeting: Meeting = await run(Broken([CallState.WAITING]))

    assert meeting.status == MeetingStatus.FAILED
    assert "the page never loaded" in (meeting.failure_reason or "")


async def test_only_meet_is_joined_for_now(
    run: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    zoom = await MeetingsService(async_db_session, None).request(
        "https://zoom.us/j/81234567890"
    )
    call = FakeCall([CallState.IN_CALL])

    meeting: Meeting = await run(call, zoom)

    assert meeting.status == MeetingStatus.FAILED
    assert "Zoom" in (meeting.failure_reason or "")
    assert call.asked_as is None


async def test_a_long_turn_keeps_its_start_and_lines_keep_when_they_were_said(
    run: Callable[..., Any],
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meet trims the start of a long turn as it grows; the line keeps it.
    Every line is written once, at the end, and still has the time it was
    first captioned, in the order they came."""
    call = FakeCall(
        [CallState.IN_CALL] * 4 + [CallState.ENDED],
        captions=[
            [Caption("1", "William", SAID)],
            [Caption("1", "William", SHOWN), Caption("2", "Lisa", "Steve.")],
        ],
    )
    bot_on(monkeypatch, async_db_session, call)
    monkeypatch.setattr(bot, "BEAT_SECONDS", 3600)

    meeting = await MeetingsService(async_db_session, None).request(MEET, "Notes")
    await bot.run_meeting(meeting.id)  # type: ignore[arg-type]

    lines = await MeetingsService(async_db_session, None).transcript(meeting)
    assert [(speaker, line.text) for speaker, line in lines] == [
        ("William", SAID + " Let me just"),
        ("Lisa", "Steve."),
    ]
    assert lines[0][1].start_seconds < lines[1][1].start_seconds


async def test_what_is_said_is_kept_line_by_line(
    run: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    """A caption block Meet is still writing updates its line; each speaker
    is a participant once."""
    talking = [Caption("1", "Leonard", "Okay.")]
    more = [Caption("1", "Leonard", "Okay. Testing."), Caption("2", "Ada", "Hi.")]
    again = [*more, Caption("3", "Leonard", "Bye.")]
    call = FakeCall(
        [CallState.IN_CALL] * 4 + [CallState.ENDED], captions=[talking, more, again]
    )

    meeting: Meeting = await run(call)

    lines = await MeetingsService(async_db_session, None).transcript(meeting)
    assert call.captions_on
    assert [(speaker, line.text) for speaker, line in lines] == [
        ("Leonard", "Okay. Testing."),
        ("Ada", "Hi."),
        ("Leonard", "Bye."),
    ]
    people = await async_db_session.exec(
        select(MeetingParticipant.display_name).where(
            MeetingParticipant.meeting_id == meeting.id
        )
    )
    assert sorted(people.all()) == ["Ada", "Leonard"]


async def test_once_it_has_left_the_notes_are_written(
    run: Callable[..., Any],
) -> None:
    written: list[int] = []

    async def write(meeting_id: int) -> None:
        written.append(meeting_id)

    meeting: Meeting = await run(
        FakeCall([CallState.IN_CALL, CallState.ENDED]), notes=write
    )

    assert written == [meeting.id]


async def test_after_the_notes_each_guide_and_the_series_are_written(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """How to work with each person and what the series keeps coming back
    to both read the meeting's notes, so they come after them."""
    order: list[str] = []

    def writes(what: str) -> Callable[[int], Any]:
        async def write(meeting_id: int) -> None:
            order.append(what)

        return write

    bot_on(
        monkeypatch,
        async_db_session,
        FakeCall([CallState.IN_CALL, CallState.ENDED]),
        notes=writes("notes"),
        guides=writes("guides"),
        themes=writes("themes"),
    )
    meeting = await MeetingsService(async_db_session, None).request(MEET, "Notes")

    await bot.run_meeting(meeting.id)  # type: ignore[arg-type]

    assert order == ["notes", "guides", "themes"]


async def test_what_it_hears_goes_to_whoever_was_talking(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Kept, as each speaker's audio, when a folder is named for it."""
    monkeypatch.setattr(settings, "MEETINGS_KEEP_AUDIO_DIR", str(tmp_path))
    talking = [Caption("1", "Ada", "Hello.")]
    more = [Caption("1", "Ada", "Hello there.")]
    call = FakeCall(
        [CallState.IN_CALL] * 3 + [CallState.ENDED],
        captions=[talking, more],
        sound=True,
    )

    meeting: Meeting = await run(call)

    assert [p.name for p in (tmp_path / str(meeting.id)).iterdir()] == ["Ada.wav"]


async def test_how_long_each_speaker_was_heard_is_kept(
    run: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    call = FakeCall(
        [CallState.IN_CALL] * 3 + [CallState.ENDED],
        captions=[
            [Caption("1", "Ada", "Hello.")],
            [Caption("1", "Ada", "Hello there.")],
        ],
        sound=True,
    )

    meeting: Meeting = await run(call)

    heard = (
        await MeetingsService(async_db_session, None).read(meeting.id)
    ).heard_seconds  # type: ignore[arg-type]
    assert list(heard) == ["Ada"]
    assert heard["Ada"] > 0


async def _status(session: AsyncSession, row: Meeting) -> MeetingStatus:
    return (
        await session.exec(select(Meeting.status).where(Meeting.id == row.id))
    ).one()


async def test_it_joins_as_its_card_and_announces_itself_in_the_chat_only(
    run: Callable[..., Any],
) -> None:
    """Said aloud, its announcement cut into the call as it joined: it is
    written in the chat (the notice that what is said is transcribed)."""
    call = FakeCall([CallState.IN_CALL, CallState.ENDED])

    await run(call)

    assert call.start.name == "Notes" and call.start.camera
    assert call.start.image is None
    assert call.spoken == []
    assert call.said[0].startswith("Notes")


async def test_its_card_says_it_cannot_see_captions_and_that_it_leaves(
    run: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bot, "ALONE_SECONDS", 0)
    call = FakeCall([CallState.IN_CALL], people=[3, 1])
    call.captions_offered = False

    await run(call)

    statuses = [c["status"] for c in call.cards if "status" in c]
    assert statuses[0] == card.NO_CAPTIONS
    assert statuses[-1] == card.LEAVING


async def test_its_card_says_when_a_runner_is_answering(
    run: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    meeting_id, moment_id = await asked_a_question(async_db_session)

    async def answering() -> None:
        async_db_session.add(
            MeetingActionRun(
                moment_id=moment_id, action="ask", prompt="-", status=CLAIMED
            )
        )
        await async_db_session.commit()

    call = FakeCall(
        [CallState.IN_CALL, CallState.IN_CALL, CallState.ENDED],
        during={"say": answering},
    )

    await run(call, meeting=await async_db_session.get(Meeting, meeting_id))

    assert {"status": card.ANSWERING} in call.cards


async def test_an_agents_picture_and_camera_setting_come_with_it(
    run: Callable[..., Any], async_db_session: AsyncSession
) -> None:
    await accounts.set_image(
        async_db_session, accounts.DEFAULT_AGENT, b"png", "image/png"
    )
    await accounts.set_switch(async_db_session, accounts.DEFAULT_AGENT, "camera", False)
    call = FakeCall([CallState.IN_CALL, CallState.ENDED])

    await run(call)

    assert call.start.image == "data:image/png;base64,cG5n"
    assert not call.start.camera


async def test_it_speaks_in_the_stacks_active_voice(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The voice profile Overseer speaks in, read where the bot runs: a
    worker never loads it at startup as the webserver does."""
    tts = pytest.importorskip("app.services.ai.domains.voice.tts")
    ai = pytest.importorskip("app.services.ai.service")
    async_db_session.add(ai.VoiceProfile(name="Hers", is_active=True, tts_voice="nova"))
    await async_db_session.commit()
    asked: list[tuple[str, str]] = []

    async def synthesize(self: Any, request: Any) -> Any:
        asked.append((self.voice, request.text))
        return SimpleNamespace(audio=b"mp3")

    monkeypatch.setattr(tts.TTSService, "synthesize", synthesize)

    speaking = await voice.voice_of(async_db_session)

    assert await voice.spoken("I'm here", speaking) == b"mp3"
    assert asked == [("nova", "I'm here")]
