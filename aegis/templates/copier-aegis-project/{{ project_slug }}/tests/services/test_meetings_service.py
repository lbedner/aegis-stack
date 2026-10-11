"""The meetings service: a meeting the bot is asked to join, who spoke in
it, and what they said. Nothing joins a call yet; these are the records
the bot will write."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import (
    MeetingParticipant,
    MeetingStatus,
    Platform,
    TranscriptLine,
)
from app.services.meetings.service import (
    MeetingNotFoundError,
    MeetingsService,
    UnsupportedMeetingLinkError,
    detect_platform,
    meetings_counts,
)
from tests._cli import invoke


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

    meeting = await svc.request("https://meet.google.com/abc-defg-hij", "Notes")

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
    meeting = await svc.request("https://meet.google.com/abc-defg-hij")
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

    lines = await svc.transcript(meeting.id)  # type: ignore[arg-type]

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


def test_the_cli_refuses_a_link_it_cannot_join() -> None:
    result = invoke(["meetings", "add", "https://example.com/meeting"])

    assert result.exit_code == 1
    assert "Google Meet, Microsoft Teams or Zoom" in result.output
