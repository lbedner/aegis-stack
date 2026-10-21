"""The reads behind moments: the moments already on some lines, who said
those lines, a meeting's moments with where each was said, their runs, and
the call's lines up to a point."""

from collections.abc import Iterable

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.notes.queries import with_speaker
from app.services.meetings.models import (
    UNKNOWN,
    MeetingActionRun,
    MeetingMoment,
    MeetingParticipant,
    MeetingPerson,
    TranscriptLine,
)


async def on_lines(
    db: AsyncSession, line_ids: Iterable[int]
) -> dict[tuple[int, str], MeetingMoment]:
    """The moments already on these lines, by line and kind."""
    query = select(MeetingMoment).where(col(MeetingMoment.line_id).in_(list(line_ids)))
    return {(m.line_id, m.kind): m for m in (await db.exec(query)).all()}


async def speakers(
    db: AsyncSession, line_ids: Iterable[int]
) -> list[tuple[int, str, bool]]:
    """Each line's id, who said it, and whether that is the owner."""
    query = with_speaker(
        select(TranscriptLine.id, MeetingParticipant.display_name, MeetingPerson.is_me)
    ).where(col(TranscriptLine.id).in_(list(line_ids)))
    return [
        (line_id or 0, speaker or UNKNOWN, bool(is_me))
        for line_id, speaker, is_me in (await db.exec(query)).all()
    ]


async def of_meeting(
    db: AsyncSession, meeting_id: int
) -> list[tuple[MeetingMoment, float, str]]:
    """A meeting's moments in the order they were said, each with when and
    by whom."""
    query = (
        with_speaker(
            select(
                MeetingMoment,
                TranscriptLine.start_seconds,
                MeetingParticipant.display_name,
            ).join(TranscriptLine, col(TranscriptLine.id) == MeetingMoment.line_id)
        )
        .where(MeetingMoment.meeting_id == meeting_id)
        .order_by(col(TranscriptLine.start_seconds), col(MeetingMoment.id))
    )
    return [
        (moment, at, speaker or UNKNOWN)
        for moment, at, speaker in (await db.exec(query)).all()
    ]


async def runs_of(db: AsyncSession, moment_ids: list[int]) -> list[MeetingActionRun]:
    """These moments' runs, oldest first."""
    query = (
        select(MeetingActionRun)
        .where(col(MeetingActionRun.moment_id).in_(moment_ids))
        .order_by(col(MeetingActionRun.asked_at), col(MeetingActionRun.id))
    )
    return list((await db.exec(query)).all())


async def said(
    db: AsyncSession,
    meeting_id: int,
    *,
    up_to: float | None = None,
    last: int | None = None,
) -> list[tuple[str, int, str]]:
    """The call's lines in order, as speaker, line id and text: every one,
    or the ``last`` said by ``up_to`` seconds in."""
    query = with_speaker(select(MeetingParticipant.display_name, TranscriptLine)).where(
        TranscriptLine.meeting_id == meeting_id,
        *([col(TranscriptLine.start_seconds) <= up_to] if up_to is not None else []),
    )
    if last is None:
        query = query.order_by(
            col(TranscriptLine.start_seconds), col(TranscriptLine.id)
        )
    else:  # the newest ``last``, put back in order below
        query = query.order_by(
            col(TranscriptLine.start_seconds).desc(), col(TranscriptLine.id).desc()
        ).limit(last)
    rows = [
        (s or UNKNOWN, row.id or 0, row.text) for s, row in (await db.exec(query)).all()
    ]
    return rows if last is None else rows[::-1]
