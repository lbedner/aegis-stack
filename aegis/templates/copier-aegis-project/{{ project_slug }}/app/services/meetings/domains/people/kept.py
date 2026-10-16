"""Each person's guide as kept: a row per person (``PersonGuide``), each
point a row (``MeetingGuidePoint``) citing the lines it rests on
(``MeetingGuidePointLine``). ``Guide`` is how one is written and read."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.meetings.domains.notes.queries import delete_in, existing
from app.services.meetings.domains.notes.service import cited
from app.services.meetings.domains.people import queries
from app.services.meetings.models import (
    GUIDE_SECTIONS,
    Guide,
    MeetingGuidePoint,
    MeetingGuidePointLine,
    NoteItem,
    PersonGuide,
)


async def _row(db: AsyncSession, person_id: int) -> PersonGuide:
    """The person's guide row, locked for this write, made if they have
    none yet."""
    row = await queries.guide_row(db, person_id, lock=True)
    if row is None:
        row = PersonGuide(person_id=person_id)
        db.add(row)
        await db.flush()
    return row


async def keep_guide(
    db: AsyncSession,
    person_id: int,
    guide: Guide,
    model_name: str | None,
    meetings: int,
) -> None:
    """Keep ``guide`` as the person's, over the points they had; the
    owner's note on them stays as it is (only the fields set here are
    written)."""
    row = await _row(db, person_id)
    await delete_in(db, MeetingGuidePoint.guide_id, [row.id])
    lines, _ = await existing(db, (n for p in guide.points() for n in p.lines), ())
    points = [
        (MeetingGuidePoint(guide_id=row.id, section=key, ord=i, text=p.text), p)
        for key in GUIDE_SECTIONS
        for i, p in enumerate(getattr(guide, key))
    ]
    db.add_all(kept for kept, _ in points)
    await db.flush()
    db.add_all(
        MeetingGuidePointLine(point_id=kept.id, line_id=line, ord=i)
        for kept, point in points
        for i, line in enumerate(cited(point.lines, lines))
    )
    row.sqlmodel_update(
        {
            "error": None,
            "model_name": model_name,
            "meetings": meetings,
            "written_at": utcnow(),
        }
    )
    db.add(row)
    await db.commit()


async def keep_guide_failure(db: AsyncSession, person_id: int, error: str) -> None:
    """Why the person's guide could not be written; its points stay."""
    row = await _row(db, person_id)
    row.error = error[:500]
    db.add(row)
    await db.commit()


async def guides_of(db: AsyncSession, guide_ids: list[int]) -> dict[int, Guide]:
    """Those guides read back from their points, by guide id."""
    read: dict[int, Guide] = {i: Guide() for i in guide_ids}
    points: dict[int, NoteItem] = {}
    for point, line in await queries.guide_points(db, guide_ids):
        item = points.get(point.id)  # type: ignore[arg-type]
        if item is None:
            item = points[point.id] = NoteItem(id=point.id, text=point.text)  # type: ignore[index]
            getattr(read[point.guide_id], point.section).append(item)
        if line is not None:
            item.lines.append(line)
    return read
