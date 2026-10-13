"""The meetings service: a meeting the bot is asked to join, who spoke in
it, and what they said. Nothing joins a call yet; these are the records
the bot will write."""

import asyncio
from datetime import timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.cli.meetings import describe
from app.components.backend.startup import meetings_recovery
from app.core.time import utcnow
from app.services.meetings.models import (
    ActionItem,
    Meeting,
    MeetingNotes,
    MeetingParticipant,
    MeetingStatus,
    Notes,
    Platform,
    TranscriptLine,
    TranscriptRow,
)
from app.services.meetings.service import (
    STALE_SECONDS,
    MeetingInProgressError,
    MeetingNotFoundError,
    MeetingsService,
    NotASpeakerError,
    NothingToWriteError,
    UnsupportedMeetingLinkError,
    detect_platform,
    fail_interrupted,
    heard_line,
    meetings_counts,
    remember_me,
    save_heard,
    save_notes,
    speakers,
    transition,
    voice,
    voices,
)
from tests._cli import invoke
from tests._meetings import MEET, ended, hold_the_writer, said
from tests._meetings import record as shared_record
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


async def test_the_speaker_i_am_carries_to_my_next_meeting(
    async_db_session: AsyncSession,
) -> None:
    """Picked once, the speaker I am is picked again in my next meeting I
    speak in, by name; not in one I was not in."""
    svc = MeetingsService(async_db_session, owner_user_id=None)
    first, second, third = [await svc.request(MEET) for _ in range(3)]
    await said(async_db_session, first.id, ("Leonard", "Hi."), ("Ada", "Hello."))  # type: ignore[arg-type]
    await said(async_db_session, second.id, ("Ada", "Again."), ("Leonard", "Yes."))  # type: ignore[arg-type]
    await said(async_db_session, third.id, ("Ada", "Only me."))  # type: ignore[arg-type]

    await svc.set_me(first.id, "Leonard")  # type: ignore[arg-type]
    await remember_me(async_db_session, second.id)  # type: ignore[arg-type]
    await remember_me(async_db_session, third.id)  # type: ignore[arg-type]

    assert (await svc.get(second.id)).me == "Leonard"  # type: ignore[arg-type]
    assert (await svc.get(third.id)).me is None  # type: ignore[arg-type]


async def test_only_a_speaker_in_the_meeting_can_be_me(
    async_db_session: AsyncSession,
) -> None:
    svc = MeetingsService(async_db_session, owner_user_id=None)
    meeting = await svc.request(MEET)
    await said(async_db_session, meeting.id, ("Ada", "Hello."))  # type: ignore[arg-type]

    with pytest.raises(NotASpeakerError):
        await svc.set_me(meeting.id, "Mallory")  # type: ignore[arg-type]
    assert (await svc.set_me(meeting.id, "Ada")).me == "Ada"  # type: ignore[arg-type]
    assert (await svc.set_me(meeting.id, None)).me is None  # type: ignore[arg-type]


async def test_notes_are_kept_and_written_over(async_db_session: AsyncSession) -> None:
    svc = MeetingsService(async_db_session, owner_user_id=None)
    meeting = await svc.request(MEET)
    meeting_id: int = meeting.id  # type: ignore[assignment]

    await save_notes(async_db_session, MeetingNotes(meeting_id=meeting_id, error="x"))
    better = Notes(
        summary="Ship it.",
        action_items=[ActionItem(text="Write the docs", owner="Ada", lines=[1])],
    )
    await save_notes(
        async_db_session,
        MeetingNotes(meeting_id=meeting_id, content=better.model_dump()),
    )

    kept = (await svc.notes_for([meeting_id]))[meeting_id]
    assert kept.error is None
    assert kept.notes() == better
    assert [a.text for a in better.mine("Ada")] == ["Write the docs"]
    assert better.mine(None) == []


async def test_deleting_a_meeting_takes_everything_kept_of_it(
    async_db_session: AsyncSession,
) -> None:
    svc = MeetingsService(async_db_session, owner_user_id=None)
    meeting = await svc.request(MEET)
    meeting_id: int = meeting.id  # type: ignore[assignment]
    await said(async_db_session, meeting_id, ("Ada", "Hello."))
    await save_notes(
        async_db_session,
        MeetingNotes(meeting_id=meeting_id, content=Notes(summary="Hi.").model_dump()),
    )

    await svc.delete(meeting_id)

    with pytest.raises(MeetingNotFoundError):
        await svc.get(meeting_id)
    assert await speakers(async_db_session, meeting_id) == []
    assert await svc.notes_for([meeting_id]) == {}


async def test_a_meeting_the_bot_is_in_is_not_deleted(
    async_db_session: AsyncSession,
) -> None:
    svc = MeetingsService(async_db_session, owner_user_id=None)
    meeting = await svc.request(MEET)
    meeting_id: int = meeting.id  # type: ignore[assignment]
    await transition(
        async_db_session,
        meeting_id,
        MeetingStatus.IN_CALL,
        from_=(MeetingStatus.REQUESTED,),
    )

    with pytest.raises(MeetingInProgressError):
        await svc.delete(meeting_id)
    assert (await svc.get(meeting_id)).status == MeetingStatus.IN_CALL


def test_what_was_heard_reads_most_heard_first() -> None:
    assert heard_line({"Leonard": 150.0, "Ada": 250.4}) == "Ada 4m 10s · Leonard 2m 30s"
    assert heard_line({}) is None
    assert heard_line(None) is None


async def test_what_was_heard_is_kept_with_the_meeting(
    async_db_session: AsyncSession,
) -> None:
    svc = MeetingsService(async_db_session, None)
    meeting_id: int = (await svc.request(MEET)).id  # type: ignore[assignment]

    await save_heard(async_db_session, meeting_id, {"Ada": 42.0})

    assert (await svc.get(meeting_id)).heard == {"Ada": 42.0}


def test_the_cli_shows_a_meeting_as_the_pages_read_it() -> None:
    """``meetings show`` prints the service's read: the status as the pages
    say it, how long the bot was in, who was heard, and the transcript."""
    joined = utcnow()
    meeting = Meeting(
        id=7,
        url=MEET,
        platform=Platform.MEET,
        status=MeetingStatus.LEFT,
        bot_name="Notes",
        joined_at=joined,
        left_at=joined + timedelta(seconds=90),
        heard={"Ada": 42.0},
    )
    record = shared_record(
        meeting,
        transcript=[TranscriptRow(id=1, speaker="Ada", at=61.0, text="Hello.")],
        length="01:30",
    )

    shown = "\n".join(describe(record))

    for part in ("Status: Left", "01:30", "Ada 42s", "01:01", "Ada: Hello."):
        assert part in shown


async def test_the_read_says_who_spoke_what_is_mine_and_what_can_be_done(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What both Overseers and the page need, from one read."""
    hold_the_writer(monkeypatch)
    meeting_id, _ = await ended(
        async_db_session,
        None,
        ("Leonard", "I'll book the room."),
        ("Ada", "And I write the docs."),
        notes=lambda ids: Notes(
            summary="Room and docs.",
            action_items=[ActionItem(text="Book the room", owner="Leonard")],
        ),
    )
    svc = MeetingsService(async_db_session, None)
    await svc.set_me(meeting_id, "Leonard")

    record = await svc.read(meeting_id)

    assert record.people == ["Ada", "Leonard"]
    assert [item.text for item in record.mine] == ["Book the room"]
    assert record.can_rewrite
    assert not (record.writing or record.under_way)


async def test_notes_are_written_again_only_when_they_can_be(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not while the bot is in, nor while a writer is at it: then it starts
    one, in the background, and the read says the notes are being written."""
    started, runs = hold_the_writer(monkeypatch)
    svc = MeetingsService(async_db_session, None)
    under_way = await svc.request(MEET)
    meeting_id, _ = await ended(
        async_db_session, None, ("Ada", "Hi."), notes=lambda _: Notes(summary="Hi.")
    )

    with pytest.raises(NothingToWriteError):
        await svc.write_notes_again(under_way.id)  # type: ignore[arg-type]
    record = await svc.write_notes_again(meeting_id)

    assert record.writing and not record.can_rewrite
    with pytest.raises(NothingToWriteError):
        await svc.write_notes_again(meeting_id)
    await runs[0]
    assert started == [meeting_id]


def test_every_speaker_in_a_meeting_has_a_color_of_their_own() -> None:
    """Up to the theme's nine colors none is shared, the eight speakers of a
    real call included; a speaker keeps their name's color unless someone
    in the meeting already has it."""
    names = [
        "Lawrence Casely-Hayford",
        "William Ferro",
        "Lisa Atalese",
        "Leonard Bedner",
        "Moises J",
        "Susan Griffin-Herrera",
        "Vishal Singh",
        "Ada",
    ]

    colors = voices(names)

    assert len(set(colors.values())) == len(names)
    assert set(colors.values()) <= set(range(1, 10))
    assert voices(["Ada"]) == {"Ada": voice("Ada")}
