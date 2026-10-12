"""The meetings service: a meeting the bot is asked to join, who spoke in
it, and what they said. Nothing joins a call yet; these are the records
the bot will write."""

import asyncio
from datetime import timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.startup import meetings_recovery
from app.core.time import utcnow
from app.services.meetings.models import (
    MeetingParticipant,
    MeetingStatus,
    Platform,
    TranscriptLine,
)
from app.services.meetings.service import (
    STALE_SECONDS,
    MeetingNotFoundError,
    MeetingsService,
    UnsupportedMeetingLinkError,
    detect_platform,
    fail_interrupted,
    meetings_counts,
    transition,
)
from tests._cli import invoke
from tests._meetings import MEET
from tests._session import opens


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://meet.google.com/abc-defg-hij", Platform.MEET),
        ("https://meet.google.com/abc-defg-hij?authuser=1", Platform.MEET),
        (
            "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x/0",
            Platform.TEAMS,
        ),
        ("https://teams.live.com/meet/9876543210", Platform.TEAMS),
        ("https://us02web.zoom.us/j/81234567890?pwd=abc", Platform.ZOOM),
        ("https://zoom.us/j/81234567890", Platform.ZOOM),
    ],
)
def test_the_platform_comes_from_the_link(url: str, platform: Platform) -> None:
    assert detect_platform(url) == platform


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/meeting",
        "http://meet.google.com/abc-defg-hij",
        "https://meet.google.com/",
        "https://meet.google.com.evil.example/abc-defg-hij",
        "https://zoom.us/pricing",
        "not a link",
    ],
)
def test_any_other_link_is_refused(url: str) -> None:
    with pytest.raises(UnsupportedMeetingLinkError):
        detect_platform(url)


async def test_a_requested_meeting_waits_for_the_bot(
    async_db_session: AsyncSession,
) -> None:
    svc = MeetingsService(async_db_session, owner_user_id=7)

    meeting = await svc.request(MEET, "Notes")

    assert meeting.platform == Platform.MEET
    assert meeting.status == MeetingStatus.REQUESTED
    assert meeting.bot_name == "Notes" and meeting.owner_user_id == 7
    assert meeting.joined_at is None and meeting.left_at is None
    assert (await svc.get(meeting.id)).url == meeting.url  # type: ignore[arg-type]


async def test_each_owner_sees_only_their_meetings(
    async_db_session: AsyncSession,
) -> None:
    mine = MeetingsService(async_db_session, owner_user_id=1)
    theirs = MeetingsService(async_db_session, owner_user_id=2)
    first = await mine.request("https://meet.google.com/aaa-bbbb-ccc")
    second = await mine.request("https://meet.google.com/ddd-eeee-fff")
    other = await theirs.request("https://zoom.us/j/81234567890")

    assert [m.id for m in await mine.list_meetings()] == [second.id, first.id]
    with pytest.raises(MeetingNotFoundError):
        await mine.get(other.id)  # type: ignore[arg-type]


def test_an_owners_newest_meetings_are_read_off_one_index() -> None:
    """``list_meetings`` filters by owner and sorts newest first."""
    from app.services.meetings.models import Meeting

    indexes = {
        index.name: [column.name for column in index.columns]
        for index in Meeting.__table__.indexes  # type: ignore[attr-defined]
    }

    assert indexes == {
        "ix_meeting_owner_created": ["owner_user_id", "created_at", "id"]
    }


async def test_without_auth_every_meeting_is_shown(
    async_db_session: AsyncSession,
) -> None:
    owned = await MeetingsService(async_db_session, owner_user_id=1).request(
        "https://meet.google.com/aaa-bbbb-ccc"
    )

    everyone = MeetingsService(async_db_session, owner_user_id=None)

    assert [m.id for m in await everyone.list_meetings()] == [owned.id]


async def test_the_transcript_reads_in_order_with_its_speakers(
    async_db_session: AsyncSession,
) -> None:
    svc = MeetingsService(async_db_session, owner_user_id=None)
    meeting = await svc.request(MEET)
    ana = MeetingParticipant(meeting_id=meeting.id, display_name="Ana")  # type: ignore[arg-type]
    async_db_session.add(ana)
    await async_db_session.flush()
    async_db_session.add_all(
        [
            TranscriptLine(
                meeting_id=meeting.id,  # type: ignore[arg-type]
                participant_id=ana.id,
                start_seconds=12.0,
                end_seconds=14.5,
                text="Second",
            ),
            TranscriptLine(
                meeting_id=meeting.id,  # type: ignore[arg-type]
                participant_id=ana.id,
                start_seconds=3.0,
                end_seconds=5.0,
                text="First",
            ),
        ]
    )
    await async_db_session.flush()

    lines = await svc.transcript(meeting)

    assert [(speaker, line.text) for speaker, line in lines] == [
        ("Ana", "First"),
        ("Ana", "Second"),
    ]


async def test_the_counts_cover_every_owner(async_db_session: AsyncSession) -> None:
    await MeetingsService(async_db_session, owner_user_id=1).request(
        "https://meet.google.com/aaa-bbbb-ccc"
    )
    await MeetingsService(async_db_session, owner_user_id=2).request(
        "https://zoom.us/j/81234567890"
    )

    assert await meetings_counts(async_db_session) == {"meetings": 2, "in_call": 0}


async def test_a_status_moves_only_from_where_it_is_expected(
    async_db_session: AsyncSession,
) -> None:
    meeting = await MeetingsService(async_db_session, None).request(MEET)
    meeting_id: int = meeting.id  # type: ignore[assignment]

    wrong = await transition(
        async_db_session,
        meeting_id,
        MeetingStatus.IN_CALL,
        from_=(MeetingStatus.WAITING,),
    )
    right = await transition(
        async_db_session,
        meeting_id,
        MeetingStatus.JOINING,
        from_=(MeetingStatus.REQUESTED,),
    )

    await async_db_session.refresh(meeting)
    assert (wrong, right) == (False, True)
    assert meeting.status == MeetingStatus.JOINING and meeting.seen_at


async def test_every_move_is_a_heartbeat(async_db_session: AsyncSession) -> None:
    """A run's slow browser steps sit between two moves, so a run is never
    stale for longer than one step."""
    meeting = await MeetingsService(async_db_session, None).request(MEET)
    meeting_id: int = meeting.id  # type: ignore[assignment]
    await transition(
        async_db_session,
        meeting_id,
        MeetingStatus.JOINING,
        from_=(MeetingStatus.REQUESTED,),
    )
    stale = utcnow() - timedelta(seconds=STALE_SECONDS + 1)
    meeting.seen_at = stale
    await async_db_session.commit()

    await transition(
        async_db_session,
        meeting_id,
        MeetingStatus.WAITING,
        from_=(MeetingStatus.JOINING,),
    )

    await async_db_session.refresh(meeting)
    assert meeting.seen_at and meeting.seen_at > stale


async def test_the_app_keeps_sweeping_for_stopped_runs(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not only at startup: a ``meetings join`` killed while the app runs
    is failed on a later sweep."""
    sweeps: list[int] = []

    async def sweep(db: AsyncSession) -> int:
        sweeps.append(1)
        if len(sweeps) == 3:
            raise asyncio.CancelledError
        return 0

    monkeypatch.setattr(meetings_recovery, "STALE_SECONDS", 0)
    monkeypatch.setattr(meetings_recovery, "get_async_session", opens(async_db_session))
    monkeypatch.setattr(meetings_recovery, "fail_interrupted", sweep)

    with pytest.raises(asyncio.CancelledError):
        await meetings_recovery.sweep_forever()

    assert len(sweeps) == 3


async def test_only_a_run_that_stopped_beating_is_failed(
    async_db_session: AsyncSession,
) -> None:
    """A restart fails the meetings its runs died in, never one another
    process (``meetings join``) is still beating for."""
    svc = MeetingsService(async_db_session, None)
    live = await svc.request("https://meet.google.com/aaa-bbbb-ccc")
    dead = await svc.request("https://meet.google.com/ddd-eeee-fff")
    done = await svc.request("https://meet.google.com/ggg-hhhh-iii")
    live.status = dead.status = MeetingStatus.IN_CALL
    done.status = MeetingStatus.LEFT
    live.seen_at = utcnow()
    dead.seen_at = utcnow() - timedelta(seconds=STALE_SECONDS + 1)
    await async_db_session.commit()

    assert await fail_interrupted(async_db_session) == 1

    async_db_session.expire_all()
    await svc.list_meetings()  # one read brings all three back
    assert dead.status == MeetingStatus.FAILED and "stopped" in dead.failure_reason  # type: ignore[operator]
    assert live.status == MeetingStatus.IN_CALL
    assert done.status == MeetingStatus.LEFT


def test_the_cli_refuses_a_link_it_cannot_join() -> None:
    result = invoke(["meetings", "join", "https://example.com/meeting"])

    assert result.exit_code == 1
    assert "Google Meet, Microsoft Teams or Zoom" in result.output
