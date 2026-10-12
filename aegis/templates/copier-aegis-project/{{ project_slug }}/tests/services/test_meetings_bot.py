"""The meeting bot's run (``bot.run_meeting``): it asks to join, waits to be
admitted, says who it is, stays until there is a reason to leave, and
writes each step on the meeting row, never over a leave request or a
failure written elsewhere. A scripted call stands in for the browser; the
Meet page itself is tested against a fake page (``test_meet_page``)."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings import bot
from app.services.meetings.meet import CallState
from app.services.meetings.models import (
    Caption,
    Meeting,
    MeetingParticipant,
    MeetingStatus,
)
from app.services.meetings.service import MeetingsService, transition
from tests._meetings import MEET, bot_on

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
    ):
        self.states = states
        self.counts = people or [3]
        self.shown = captions or [[]]
        self.captions_on = False
        self.during = during or {}
        self.said: list[str] = []
        self.asked_as: str | None = None
        self.left = False

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
        return self.shown.pop(0) if len(self.shown) > 1 else self.shown[0]


@pytest.fixture
def run(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Any]:
    """Run the bot against ``call`` on a meeting (a new Meet meeting unless
    given), without waiting between looks; returns the meeting after."""

    async def go(call: FakeCall, meeting: Meeting | None = None) -> Meeting:
        if meeting is None:
            meeting = await MeetingsService(async_db_session, None).request(
                MEET, "Notes"
            )
        bot_on(monkeypatch, async_db_session, call)
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
    row: Meeting = await meeting()
    await MeetingsService(async_db_session, None).ask_to_leave(row.id)  # type: ignore[arg-type]
    call = FakeCall([CallState.IN_CALL])

    after: Meeting = await run(call, row)

    assert call.asked_as is None
    assert after.status == MeetingStatus.LEFT


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
