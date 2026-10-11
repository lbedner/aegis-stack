"""Meetings, read and requested for one owner (``owner_user_id``; ``None``
on a project without auth reads every meeting)."""

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import (
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    Platform,
    TranscriptLine,
)
from app.services.shared.queries import owner_filters

DEFAULT_BOT_NAME = "Notetaker"


class UnsupportedMeetingLinkError(ValueError):
    """A link the bot cannot join."""


class MeetingNotFoundError(LookupError):
    """No such meeting for this owner."""


def detect_platform(url: str) -> Platform:
    """The platform a meeting link belongs to; any other link is refused."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path.strip("/")
    if parts.scheme == "https" and path:
        if host == "meet.google.com":
            return Platform.MEET
        if host in ("teams.microsoft.com", "teams.live.com"):
            return Platform.TEAMS
        if (host == "zoom.us" or host.endswith(".zoom.us")) and path.startswith(
            ("j/", "wc/")
        ):
            return Platform.ZOOM
    raise UnsupportedMeetingLinkError(
        f"Not a meeting link the bot can join: {url}. "
        "It joins Google Meet, Microsoft Teams or Zoom links."
    )


class MeetingsService:
    def __init__(self, db: AsyncSession, owner_user_id: int | None) -> None:
        self.db = db
        self.owner_user_id = owner_user_id

    async def request(self, url: str, bot_name: str = DEFAULT_BOT_NAME) -> Meeting:
        """Record a meeting for the bot to join; a link it cannot join raises
        ``UnsupportedMeetingLinkError`` before anything is stored."""
        url = url.strip()
        meeting = Meeting(
            owner_user_id=self.owner_user_id,
            url=url,
            platform=detect_platform(url),
            bot_name=bot_name,
        )
        self.db.add(meeting)
        await self.db.commit()
        return meeting

    async def list_meetings(self, limit: int = 50) -> list[Meeting]:
        """Newest first."""
        query = (
            select(Meeting)
            .where(*owner_filters(Meeting.owner_user_id, self.owner_user_id))
            .order_by(col(Meeting.created_at).desc(), col(Meeting.id).desc())
            .limit(limit)
        )
        return list((await self.db.exec(query)).all())

    async def get(self, meeting_id: int) -> Meeting:
        query = select(Meeting).where(
            Meeting.id == meeting_id,
            *owner_filters(Meeting.owner_user_id, self.owner_user_id),
        )
        meeting = (await self.db.exec(query)).first()
        if meeting is None:
            raise MeetingNotFoundError(f"No meeting {meeting_id}")
        return meeting

    async def transcript(self, meeting_id: int) -> list[tuple[str, TranscriptLine]]:
        """Each line with its speaker's name, in the order it was said."""
        await self.get(meeting_id)
        query = (
            select(MeetingParticipant.display_name, TranscriptLine)
            .join(
                MeetingParticipant,
                col(TranscriptLine.participant_id) == MeetingParticipant.id,
                isouter=True,
            )
            .where(TranscriptLine.meeting_id == meeting_id)
            .order_by(col(TranscriptLine.start_seconds))
        )
        return [(name or "Unknown", line) for name, line in await self.db.exec(query)]


async def meetings_counts(db: AsyncSession) -> dict[str, Any]:
    """Across every owner, for the health check."""
    meetings, in_call = (
        await db.exec(
            select(
                func.count(),
                func.count().filter(col(Meeting.status) == MeetingStatus.IN_CALL),
            ).select_from(Meeting)
        )
    ).one()
    return {"meetings": meetings, "in_call": in_call}
