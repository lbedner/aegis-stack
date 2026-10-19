"""The reads and writes behind a meeting's notes: their rows, the lines
each item cites with who said them, and what a deleted meeting leaves
citing nothing elsewhere."""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, case, delete, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import (
    Meeting,
    MeetingNoteItem,
    MeetingNoteLine,
    MeetingNotes,
    MeetingParticipant,
    MeetingPerson,
    TranscriptLine,
)
from app.services.shared.queries import owner_clause

COMMITMENTS = "commitments"
CONTRADICTIONS = "contradictions"


async def delete_in(db: AsyncSession, column: Any, values: Iterable[Any]) -> None:
    """Delete the rows of ``column``'s table whose ``column`` is one of
    ``values`` (none: nothing)."""
    wanted = list(values)
    if wanted:
        await db.exec(delete(column.class_).where(column.in_(wanted)))  # type: ignore[call-overload]


async def notes_rows(db: AsyncSession, meeting_ids: list[int]) -> list[MeetingNotes]:
    query = select(MeetingNotes).where(col(MeetingNotes.meeting_id).in_(meeting_ids))
    return list((await db.exec(query)).all())


async def locked_notes(db: AsyncSession, meeting_id: int) -> MeetingNotes | None:
    """The meeting's notes row, locked for this transaction where the
    engine locks rows (Postgres): two writers of one meeting's notes take
    turns."""
    query = (
        select(MeetingNotes)
        .where(MeetingNotes.meeting_id == meeting_id)
        .with_for_update()
    )
    return (await db.exec(query)).first()


async def owner_meetings(
    db: AsyncSession, owner_user_id: int | None, limit: int
) -> list[int]:
    """The owner's latest meetings (None: the standalone install's), newest
    first."""
    query = (
        select(Meeting.id)
        .where(owner_clause(Meeting.owner_user_id, owner_user_id))
        .order_by(col(Meeting.created_at).desc(), col(Meeting.id).desc())
        .limit(limit)
    )
    return list((await db.exec(query)).all())  # type: ignore[arg-type]


async def items_of(
    db: AsyncSession, meeting_ids: list[int], kinds: Iterable[str] | None = None
) -> list[MeetingNoteItem]:
    """Every item of those meetings' notes (of ``kinds`` only, if given),
    each part in order. Read as the database has them now: a commitment
    deleted under a follow-up sets its ``commitment_id`` to NULL there, not
    in this session."""
    query = (
        select(MeetingNoteItem)
        .execution_options(populate_existing=True)
        .where(col(MeetingNoteItem.meeting_id).in_(meeting_ids))
    )
    if kinds is not None:
        query = query.where(col(MeetingNoteItem.kind).in_(list(kinds)))
    query = query.order_by(
        col(MeetingNoteItem.meeting_id),
        col(MeetingNoteItem.kind),
        col(MeetingNoteItem.ord),
    )
    return list((await db.exec(query)).all())


def with_speaker(query: Any) -> Any:
    """``query`` (over transcript lines) with each line's participant and
    the person they are joined on: None for both where nobody was named."""
    return query.join(
        MeetingParticipant,
        col(TranscriptLine.participant_id) == MeetingParticipant.id,
        isouter=True,
    ).join(
        MeetingPerson,
        col(MeetingPerson.id) == MeetingParticipant.person_id,
        isouter=True,
    )


async def cited(
    db: AsyncSession, item_ids: list[int]
) -> list[tuple[MeetingNoteLine, str | None]]:
    """Every line those items cite, in order, with who said it."""
    if not item_ids:
        return []
    query = (
        with_speaker(
            select(MeetingNoteLine, MeetingPerson.name).join(
                TranscriptLine, col(TranscriptLine.id) == MeetingNoteLine.line_id
            )
        )
        .where(col(MeetingNoteLine.item_id).in_(item_ids))
        .order_by(col(MeetingNoteLine.item_id), col(MeetingNoteLine.ord))
    )
    return [(row, name) for row, name in (await db.exec(query)).all()]


def first_line() -> Any:
    """Each item's first cited line (of its own side), as a subquery of
    ``item_id`` and ``line_id``."""
    return (
        select(MeetingNoteLine.item_id, MeetingNoteLine.line_id)
        .where(col(MeetingNoteLine.against).is_(False), MeetingNoteLine.ord == 0)
        .subquery("first")
    )


async def first_lines(db: AsyncSession, item_ids: list[int]) -> dict[int, int]:
    """The first line each of those items cites, by item id."""
    if not item_ids:
        return {}
    first = first_line()
    query = select(first.c.item_id, first.c.line_id).where(
        first.c.item_id.in_(item_ids)
    )
    return {item: line for item, line in (await db.exec(query)).all()}


async def person_names(db: AsyncSession, ids: Iterable[int]) -> dict[int, str]:
    wanted = list(set(ids))
    if not wanted:
        return {}
    query = select(MeetingPerson.id, MeetingPerson.name).where(
        col(MeetingPerson.id).in_(wanted)
    )
    return {i: name for i, name in (await db.exec(query)).all() if i is not None}


async def commitment_lines(db: AsyncSession, meeting_id: int) -> dict[int, set[int]]:
    """The meeting's commitments, each with the lines it cites."""
    query = (
        select(MeetingNoteItem.id, MeetingNoteLine.line_id)
        .join(
            MeetingNoteLine,
            col(MeetingNoteLine.item_id) == MeetingNoteItem.id,
            isouter=True,
        )
        .where(
            MeetingNoteItem.meeting_id == meeting_id,
            MeetingNoteItem.kind == COMMITMENTS,
        )
    )
    found: dict[int, set[int]] = {}
    for item_id, line_id in (await db.exec(query)).all():
        lines = found.setdefault(item_id, set())  # type: ignore[arg-type]
        if line_id is not None:
            lines.add(line_id)
    return found


async def existing(
    db: AsyncSession, line_ids: Iterable[int], item_ids: Iterable[int]
) -> tuple[set[int], set[int]]:
    """Which of ``line_ids`` are transcript lines, and which of
    ``item_ids`` are note items, still."""
    lines, items = list(set(line_ids)), list(set(item_ids))
    found_lines = (
        set(
            (
                await db.exec(
                    select(TranscriptLine.id).where(col(TranscriptLine.id).in_(lines))
                )
            ).all()
        )
        if lines
        else set()
    )
    found_items = (
        set(
            (
                await db.exec(
                    select(MeetingNoteItem.id).where(col(MeetingNoteItem.id).in_(items))
                )
            ).all()
        )
        if items
        else set()
    )
    return found_lines, found_items  # type: ignore[return-value]


async def citing(db: AsyncSession, link: Any, meeting_id: int) -> list[int]:
    """What cites a line of ``meeting_id`` through the citation table of
    ``link`` (its column naming what cites: ``MeetingNoteLine.item_id``,
    ``MeetingGuidePointLine.point_id``)."""
    query = (
        select(link)
        .join(TranscriptLine, col(TranscriptLine.id) == link.class_.line_id)
        .where(TranscriptLine.meeting_id == meeting_id)
        .distinct()
    )
    return list((await db.exec(query)).all())


async def citing_nothing(db: AsyncSession, link: Any, ids: list[int]) -> list[int]:
    """Which of ``ids`` cite no line any more through the citation table
    of ``link`` (its column naming what cites, as for ``citing``)."""
    if not ids:
        return []
    still = set((await db.exec(select(link).where(link.in_(ids)))).all())
    return [i for i in ids if i not in still]


async def left_uncited(db: AsyncSession, item_ids: list[int]) -> list[int]:
    """Which of ``item_ids`` no longer stand: citing no line of their own,
    or a contradiction with no other side left."""
    if not item_ids:
        return []
    own = func.count(case((col(MeetingNoteLine.against).is_(False), 1)))
    other = func.count(case((col(MeetingNoteLine.against).is_(True), 1)))
    query = (
        select(MeetingNoteItem.id, MeetingNoteItem.kind, own, other)
        .join(
            MeetingNoteLine,
            col(MeetingNoteLine.item_id) == MeetingNoteItem.id,
            isouter=True,
        )
        .where(col(MeetingNoteItem.id).in_(item_ids))
        .group_by(col(MeetingNoteItem.id), col(MeetingNoteItem.kind))
    )
    return [
        item_id  # type: ignore[misc]
        for item_id, kind, mine, against in (await db.exec(query)).all()
        if not mine or (kind == CONTRADICTIONS and not against)
    ]


async def mine_counts(
    db: AsyncSession, meeting_ids: list[int], names: set[str]
) -> dict[int, int]:
    """How many action items one of ``names`` has to do in each of those
    meetings' notes, by meeting id: only meetings with notes."""
    if not meeting_ids:
        return {}
    owner = func.coalesce(MeetingPerson.name, MeetingNoteItem.person_text)
    mine = and_(MeetingNoteItem.kind == "action_items", owner.in_(list(names)))
    query = (
        select(MeetingNoteItem.meeting_id, func.count(case((mine, 1))))
        .join(
            MeetingPerson,
            col(MeetingPerson.id) == MeetingNoteItem.person_id,
            isouter=True,
        )
        .where(col(MeetingNoteItem.meeting_id).in_(meeting_ids))
        .group_by(col(MeetingNoteItem.meeting_id))
    )
    return {meeting: count for meeting, count in (await db.exec(query)).all()}
