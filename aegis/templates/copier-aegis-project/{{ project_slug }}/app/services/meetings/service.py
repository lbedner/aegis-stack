"""Meetings, read and requested for one owner (``owner_user_id``; ``None``
on a project without auth reads every meeting)."""

from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.meetings.models import (
    Caption,
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    Platform,
    TranscriptLine,
)
from app.services.shared.queries import owner_filters

DEFAULT_BOT_NAME = "Notetaker"


# A meeting the bot is on its way into or in, and not asked to leave.
STILL_WANTED = (MeetingStatus.JOINING, MeetingStatus.WAITING, MeetingStatus.IN_CALL)
# Those, and one it is on its way out of: its run beats (``seen_at``) meanwhile.
IN_PROGRESS = (*STILL_WANTED, MeetingStatus.LEAVING)
NOT_DONE = (MeetingStatus.REQUESTED, *IN_PROGRESS)
# A run whose heartbeat is older than this is gone (the process stopped).
STALE_SECONDS = 60


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

    async def ask_to_leave(self, meeting_id: int) -> Meeting:
        """Ask the bot to leave; it goes on its next look, or never joins.
        A meeting it is done with is left as it is."""
        meeting = await self.get(meeting_id)
        await transition(
            self.db,
            meeting_id,
            MeetingStatus.LEAVING,
            from_=(MeetingStatus.REQUESTED, *STILL_WANTED),
        )
        await self.db.refresh(meeting)
        return meeting

    async def transcript(self, meeting: Meeting) -> list[tuple[str, TranscriptLine]]:
        """Each line of ``meeting`` (one ``get`` returned) with its speaker's
        name, in the order it was said."""
        query = (
            select(MeetingParticipant.display_name, TranscriptLine)
            .join(
                MeetingParticipant,
                col(TranscriptLine.participant_id) == MeetingParticipant.id,
                isouter=True,
            )
            .where(TranscriptLine.meeting_id == meeting.id)
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


async def transition(
    db: AsyncSession,
    meeting_id: int,
    to: MeetingStatus,
    *,
    from_: tuple[MeetingStatus, ...],
    reason: str | None = None,
) -> bool:
    """Move a meeting to ``to`` only from one of ``from_``, in one statement,
    and say whether it moved. Every status change goes through here, so a
    leave request or a failure written by one process is never overwritten
    by a run in another. A move is a heartbeat too (``seen_at``): a run's
    slow browser steps each sit between two moves or beats."""
    now = utcnow()
    values: dict[str, Any] = {"status": to, "seen_at": now}
    if to == MeetingStatus.IN_CALL:
        values["joined_at"] = now
    if to == MeetingStatus.LEFT:
        values["left_at"] = now
    if to == MeetingStatus.FAILED:
        values["failure_reason"] = reason
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(col(Meeting.id) == meeting_id, col(Meeting.status).in_(from_))
        .values(**values)
    )
    await db.commit()
    return result.rowcount == 1


async def heartbeat(db: AsyncSession, meeting_id: int) -> str | None:
    """A run's pulse: stamp ``seen_at`` and read the status back, in one
    statement. The status is how a leave request reaches the run."""
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(col(Meeting.id) == meeting_id)
        .values(seen_at=utcnow())
        .returning(col(Meeting.status))
    )
    status = result.scalar_one_or_none()
    await db.commit()
    return status


async def fail_interrupted(db: AsyncSession) -> int:
    """A meeting whose run stopped beating (its process stopped) is over,
    and says why. A run another process is still in keeps beating, so it is
    left alone. Returns how many there were."""
    stale = utcnow() - timedelta(seconds=STALE_SECONDS)
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(
            col(Meeting.status).in_(IN_PROGRESS),
            or_(col(Meeting.seen_at).is_(None), col(Meeting.seen_at) < stale),
        )
        .values(
            status=MeetingStatus.FAILED,
            failure_reason="The app stopped during the meeting",
        )
    )
    await db.commit()
    return result.rowcount


async def write_captions(
    db: AsyncSession,
    meeting_id: int,
    captions: list[Caption],
    rows: dict[str, int],
    at_seconds: float,
) -> None:
    """Each caption as its transcript line: a caption already in ``rows``
    (caption line -> row id) updates its row, a new one adds a row (and
    its id to ``rows``), its speaker becoming a participant the first time
    they speak."""
    new = [c for c in captions if c.line not in rows]
    speakers = await _participants(db, meeting_id, {c.speaker for c in new})
    added = {
        c.line: TranscriptLine(
            meeting_id=meeting_id,
            participant_id=speakers[c.speaker],
            start_seconds=at_seconds,
            end_seconds=at_seconds,
            text=c.text,
        )
        for c in new
    }
    db.add_all(added.values())
    changed = [
        {"id": rows[c.line], "text": c.text, "end_seconds": at_seconds}
        for c in captions
        if c.line in rows
    ]
    if changed:
        await db.exec(update(TranscriptLine), params=changed)
    await db.flush()
    rows |= {line: row.id for line, row in added.items()}
    await db.commit()


async def _participants(
    db: AsyncSession, meeting_id: int, names: set[str]
) -> dict[str, int]:
    """The meeting's participant id for each display name, adding those it
    does not have yet."""
    if not names:
        return {}
    found = await db.exec(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            col(MeetingParticipant.display_name).in_(names),
        )
    )
    known = {p.display_name: p for p in found.all()}
    fresh = [
        MeetingParticipant(meeting_id=meeting_id, display_name=name)
        for name in names - known.keys()
    ]
    db.add_all(fresh)
    await db.flush()
    return {p.display_name: p.id for p in [*known.values(), *fresh]}
