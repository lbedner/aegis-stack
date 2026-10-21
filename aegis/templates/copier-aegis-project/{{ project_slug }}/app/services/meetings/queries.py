"""The meetings' own reads and statements (each domain keeps its own under
``domains/``): an owner's meetings, one meeting, its transcript, the
health counts, and the moves that keep a run and its row in step. None
commits: the service does."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.notes import queries as notes_queries
from app.services.meetings.models import (
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    TranscriptLine,
)
from app.services.shared.queries import owner_filters


async def meetings_of(
    db: AsyncSession, owner_user_id: int | None, limit: int
) -> list[Meeting]:
    """An owner's meetings, newest first."""
    query = (
        select(Meeting)
        .where(*owner_filters(Meeting.owner_user_id, owner_user_id))
        .order_by(col(Meeting.created_at).desc(), col(Meeting.id).desc())
        .limit(limit)
    )
    return list((await db.exec(query)).all())


async def meeting(
    db: AsyncSession, meeting_id: int, owner_user_id: int | None
) -> Meeting | None:
    query = select(Meeting).where(
        Meeting.id == meeting_id,
        *owner_filters(Meeting.owner_user_id, owner_user_id),
    )
    return (await db.exec(query)).first()


async def transcript(
    db: AsyncSession, meeting_id: int | None
) -> list[tuple[str | None, TranscriptLine]]:
    """Each line of a meeting with its speaker's name (None when unknown),
    in the order it was said."""
    query = (
        notes_queries.with_speaker(
            select(MeetingParticipant.display_name, TranscriptLine)
        )
        .where(TranscriptLine.meeting_id == meeting_id)
        # Lines captioned in the same look keep the order Meet showed them.
        .order_by(col(TranscriptLine.start_seconds), col(TranscriptLine.id))
    )
    return list(await db.exec(query))


async def counts(db: AsyncSession) -> tuple[int, int]:
    """``(meetings, in a call now)`` across every owner."""
    found = await db.exec(
        select(
            func.count(),
            func.count().filter(col(Meeting.status) == MeetingStatus.IN_CALL),
        ).select_from(Meeting)
    )
    return found.one()


async def move(
    db: AsyncSession,
    meeting_id: int,
    from_: Iterable[MeetingStatus],
    values: dict[str, Any],
) -> bool:
    """Set ``values`` on a meeting only while its status is one of
    ``from_``, in one statement; whether it moved."""
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(col(Meeting.id) == meeting_id, col(Meeting.status).in_(from_))
        .values(**values)
    )
    return result.rowcount == 1


async def beat(db: AsyncSession, meeting_id: int, at: datetime) -> str | None:
    """Stamp ``seen_at`` and read the status back, in one statement."""
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(col(Meeting.id) == meeting_id)
        .values(seen_at=at)
        .returning(col(Meeting.status))
    )
    return result.scalar_one_or_none()


async def fail_stale(
    db: AsyncSession, statuses: Iterable[MeetingStatus], seen_before: datetime
) -> int:
    """Fail every meeting in one of ``statuses`` whose run last beat before
    ``seen_before`` (or never); how many."""
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(
            col(Meeting.status).in_(statuses),
            or_(col(Meeting.seen_at).is_(None), col(Meeting.seen_at) < seen_before),
        )
        .values(
            status=MeetingStatus.FAILED,
            failure_reason="The app stopped during the meeting",
        )
    )
    return result.rowcount


async def update_lines(db: AsyncSession, changed: list[dict[str, Any]]) -> None:
    """Each transcript line in ``changed`` (``id``, ``text``,
    ``end_seconds``) updated, in one statement."""
    await db.exec(update(TranscriptLine), params=changed)
