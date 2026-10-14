"""The reads behind each person's guide: an owner's guides, the meetings
a person spoke in and what was said there, and the lines a guide cites."""

from collections.abc import Iterable
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import (
    Meeting,
    MeetingParticipant,
    PersonGuide,
    Quote,
    TranscriptLine,
)
from app.services.shared.queries import owner_filters


async def guides(
    db: AsyncSession, owner_user_id: int | None, limit: int
) -> list[PersonGuide]:
    """An owner's guides (every owner's for None), latest written first."""
    query = (
        select(PersonGuide)
        .where(*owner_filters(PersonGuide.owner_user_id, owner_user_id))
        .order_by(col(PersonGuide.written_at).desc(), col(PersonGuide.id).desc())
        .limit(limit)
    )
    return list((await db.exec(query)).all())


async def guide(
    db: AsyncSession, owner_user_id: int | None, guide_id: int
) -> PersonGuide | None:
    query = select(PersonGuide).where(
        PersonGuide.id == guide_id,
        *owner_filters(PersonGuide.owner_user_id, owner_user_id),
    )
    return (await db.exec(query)).first()


async def guide_of(
    db: AsyncSession, owner_user_id: int | None, person: str
) -> PersonGuide | None:
    query = select(PersonGuide).where(
        PersonGuide.person == person,
        *owner_filters(PersonGuide.owner_user_id, owner_user_id),
    )
    return (await db.exec(query)).first()


async def meetings_with(
    db: AsyncSession, owner_user_id: int | None, person: str, limit: int
) -> list[int]:
    """The owner's meetings ``person`` spoke in, newest first."""
    query = (
        select(Meeting.id)
        .join(MeetingParticipant, col(MeetingParticipant.meeting_id) == Meeting.id)
        .where(
            MeetingParticipant.display_name == person,
            *owner_filters(Meeting.owner_user_id, owner_user_id),
        )
        .distinct()
        .order_by(col(Meeting.id).desc())
        .limit(limit)
    )
    return [m for m in (await db.exec(query)).all() if m is not None]


def _spoken() -> Any:
    """Each transcript line with its speaker's name (None: nobody named)."""
    return select(MeetingParticipant.display_name, TranscriptLine).join(
        MeetingParticipant,
        col(TranscriptLine.participant_id) == MeetingParticipant.id,
        isouter=True,
    )


async def said_in(
    db: AsyncSession, meeting_ids: Iterable[int]
) -> list[tuple[int, str, TranscriptLine]]:
    """Every line of those meetings: (meeting, speaker, line), each
    meeting's in the order it was said."""
    query = (
        _spoken()
        .where(col(TranscriptLine.meeting_id).in_(list(meeting_ids)))
        .order_by(
            col(TranscriptLine.meeting_id),
            col(TranscriptLine.start_seconds),
            col(TranscriptLine.id),
        )
    )
    return [
        (line.meeting_id, name or "Unknown", line)
        for name, line in await db.exec(query)
    ]


async def quotes(db: AsyncSession, line_ids: Iterable[int]) -> dict[int, Quote]:
    """The lines a guide cites, by id."""
    ids = list(line_ids)
    if not ids:
        return {}
    query = _spoken().where(col(TranscriptLine.id).in_(ids))
    return {
        line.id: Quote(
            id=line.id,
            meeting_id=line.meeting_id,
            speaker=name or "Unknown",
            at=line.start_seconds,
            text=line.text,
        )
        for name, line in await db.exec(query)
    }
