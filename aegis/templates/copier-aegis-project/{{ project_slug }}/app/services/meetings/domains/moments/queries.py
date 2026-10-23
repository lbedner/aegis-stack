"""The reads behind moments: the moments already in some meetings, who
said some lines (or every line of some meetings), a meeting's moments with
where each was said, their runs, the call's lines up to a point, and which
meetings there are to read over."""

from collections.abc import Iterable

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.moments.detectors import Heard
from app.services.meetings.domains.notes.queries import with_speaker
from app.services.meetings.models import (
    NOT_DONE,
    UNKNOWN,
    Meeting,
    MeetingActionRun,
    MeetingMoment,
    MeetingParticipant,
    MeetingPerson,
    TranscriptLine,
)


async def heard_in(db: AsyncSession, meeting_ids: list[int]) -> list[tuple[Heard, int]]:
    """Every line of these meetings as a detector reads it (with everyone
    who spoke in its meeting, ``people_in``), and its meeting."""
    query = with_speaker(
        select(
            TranscriptLine.id,
            TranscriptLine.meeting_id,
            TranscriptLine.text,
            MeetingParticipant.display_name,
            MeetingPerson.is_me,
        )
    ).where(col(TranscriptLine.meeting_id).in_(meeting_ids))
    rows = (await db.exec(query)).all()
    people = await people_in(db, meeting_ids)
    return [
        (Heard(i or 0, who or UNKNOWN, text, bool(me), people.get(m, frozenset())), m)
        for i, m, text, who, me in rows
    ]


async def in_meetings(
    db: AsyncSession, meeting_ids: list[int], line_ids: Iterable[int] | None = None
) -> dict[tuple[int, str], MeetingMoment]:
    """These meetings' moments (only those on ``line_ids``, given), by line
    and kind."""
    query = select(MeetingMoment).where(col(MeetingMoment.meeting_id).in_(meeting_ids))
    if line_ids is not None:
        query = query.where(col(MeetingMoment.line_id).in_(list(line_ids)))
    return {(m.line_id, m.kind): m for m in (await db.exec(query)).all()}


async def people_in(
    db: AsyncSession, meeting_ids: list[int]
) -> dict[int, frozenset[str]]:
    """Everyone who has spoken in each of these meetings, by the name the
    call gave them."""
    query = select(
        MeetingParticipant.meeting_id, MeetingParticipant.display_name
    ).where(col(MeetingParticipant.meeting_id).in_(meeting_ids))
    people: dict[int, set[str]] = {}
    for meeting_id, name in (await db.exec(query)).all():
        people.setdefault(meeting_id, set()).add(name or UNKNOWN)
    return {m: frozenset(names) for m, names in people.items()}


async def by_ids(db: AsyncSession, moment_ids: Iterable[int]) -> list[MeetingMoment]:
    query = select(MeetingMoment).where(col(MeetingMoment.id).in_(list(moment_ids)))
    return list((await db.exec(query)).all())


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
    line_ids: Iterable[int] | None = None,
) -> list[tuple[str, int, str]]:
    """The call's lines in order, as speaker, line id and text: every one,
    or those said by ``up_to`` seconds in, the ``last`` of them, or only
    the lines ``line_ids`` names."""
    query = with_speaker(select(MeetingParticipant.display_name, TranscriptLine)).where(
        TranscriptLine.meeting_id == meeting_id,
        *([col(TranscriptLine.start_seconds) <= up_to] if up_to is not None else []),
        *([col(TranscriptLine.id).in_(list(line_ids))] if line_ids is not None else []),
    )
    order = [col(TranscriptLine.start_seconds), col(TranscriptLine.id)]
    if last is not None:
        query = query.order_by(*(c.desc() for c in order)).limit(last)
    else:
        query = query.order_by(*order)
    rows = [
        (s or UNKNOWN, row.id or 0, row.text) for s, row in (await db.exec(query)).all()
    ]
    return rows[::-1] if last is not None else rows


async def every_meeting_id(db: AsyncSession) -> list[int]:
    return [i or 0 for i in (await db.exec(select(Meeting.id))).all()]


async def finished(db: AsyncSession, meeting_ids: list[int]) -> list[int]:
    """Those of these meetings the bot is done with."""
    query = select(Meeting.id).where(
        col(Meeting.id).in_(meeting_ids), col(Meeting.status).not_in(NOT_DONE)
    )
    return [i or 0 for i in (await db.exec(query)).all()]
