"""The meeting bot's run (``bot.run_meeting``): it asks to join, waits to be
admitted, says who it is, stays until there is a reason to leave, and
writes each step on the meeting row, never over a leave request or a
failure written elsewhere. A scripted call stands in for the browser; the
Meet page itself is tested against a fake page (``test_meet_page``)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.services.meetings import bot
from app.services.meetings.meet import CallState
from app.services.meetings.models import (
    Caption,
    Meeting,
    MeetingParticipant,
    MeetingStatus,
)
from app.services.meetings.service import MeetingsService, transition
from tests._meetings import MEET, SAID, SECOND, SHOWN, bot_on

# The run beats on every look here (BEAT_SECONDS is 0), by design.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)


class FakeCall:
    """A call whose states are scripted: one per look, the last repeating.
    ``during`` runs a hook at a named moment, as another process would."""

    def __init__(
        self,
        states: list[CallState],
        people: list[int] | None = None,
        during: dict[str, Callable[[], Any]] | None = None,
        captions: list[list[Caption]] | None = None,
        sound: bool = False,
    ):
        self.states = states
        self.counts = people or [3]
        self.shown = captions or [[]]
        self.captions_on = False
        self.during = during or {}
        self.said: list[str] = []
        self.asked_as: str | None = None
        self.left = False
        # A second of the call reaches the bot on every look, while ``sound``.
        self.sound = sound
        self.on_audio: Callable[[str], None] | None = None

    async def _at(self, moment: str) -> None:
        if moment in self.during:
            await self.during[moment]()

    async def ask_to_join(self, bot_name: str) -> None:
        self.asked_as = bot_name
        await self._at("ask_to_join")

    async def state(self) -> CallState:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    async def people(self) -> int:
        return self.counts.pop(0) if len(self.counts) > 1 else self.counts[0]

    async def say(self, text: str) -> None:
        self.said.append(text)
        await self._at("say")

    async def leave(self) -> None:
        self.left = True

    async def turn_on_captions(self) -> bool:
        self.captions_on = True
        return True

    async def captions(self) -> list[Caption]:
        if self.sound and self.on_audio is not None:
            self.on_audio(SECOND)
        return self.shown.pop(0) if len(self.shown) > 1 else self.shown[0]


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


async def test_after_the_notes_each_persons_guide_is_written(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """How to work with each person reads the notes' meeting too, so it
    comes after them."""
    order: list[str] = []

    async def notes(meeting_id: int) -> None:
        order.append("notes")

    async def guides(meeting_id: int) -> None:
        order.append("guides")

    bot_on(
        monkeypatch,
        async_db_session,
        FakeCall([CallState.IN_CALL, CallState.ENDED]),
        notes=notes,
        guides=guides,
    )
    meeting = await MeetingsService(async_db_session, None).request(MEET, "Notes")

    await bot.run_meeting(meeting.id)  # type: ignore[arg-type]

    assert order == ["notes", "guides"]


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
    run: Callable[..., Any],
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

    assert list(meeting.heard or {}) == ["Ada"]
    assert (meeting.heard or {})["Ada"] > 0


async def _status(session: AsyncSession, row: Meeting) -> MeetingStatus:
    return (
        await session.exec(select(Meeting.status).where(Meeting.id == row.id))
    ).one()
