"""A series as kept: a row per owner and link (``MeetingSeries``) with
its headline, each point a row (``MeetingTheme``, its part the ``kind``: a
theme, something settled, shifted, still open, the mood) citing the lines
it rests on (``MeetingThemeLine``). ``SeriesNotes`` is how one is written
and read back."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.meetings.domains.notes.queries import delete_in, existing
from app.services.meetings.domains.notes.service import cited
from app.services.meetings.domains.series import queries
from app.services.meetings.models import (
    OVER_TIME,
    MeetingSeries,
    MeetingTheme,
    MeetingThemeLine,
    NoteItem,
    SeriesNotes,
    Theme,
    fitted,
)

THEMES = "themes"
# Each part a point is kept in, in the order they read.
PARTS = (THEMES, *OVER_TIME)


async def _row(db: AsyncSession, owner_user_id: int | None, link: str) -> MeetingSeries:
    """The owner's series on ``link``, locked for this write, made if it
    has none yet."""
    row = await queries.series_row(db, owner_user_id, link, lock=True)
    if row is None:
        row = MeetingSeries(owner_user_id=owner_user_id, link=link)
        db.add(row)
        await db.flush()
    return row


async def keep_series(
    db: AsyncSession,
    owner_user_id: int | None,
    link: str,
    notes: SeriesNotes,
    *,
    name: str,
    model_name: str | None,
    meetings: int,
) -> int:
    """Keep ``notes`` as the series', over the points it had; its id."""
    row = await _row(db, owner_user_id, link)
    series_id: int = row.id  # type: ignore[assignment]
    await delete_in(db, MeetingTheme.series_id, [series_id])
    points = [
        (
            MeetingTheme(
                series_id=series_id,
                kind=kind,
                ord=i,
                text=point.text,
                status=getattr(point, "status", "open"),
            ),
            point,
        )
        for kind in PARTS
        for i, point in enumerate(getattr(notes, kind))
    ]
    lines, _ = await existing(db, (n for _, p in points for n in p.lines), ())
    db.add_all(kept for kept, _ in points)
    await db.flush()
    db.add_all(
        MeetingThemeLine(theme_id=kept.id, line_id=line, ord=i)  # type: ignore[arg-type]
        for kept, point in points
        for i, line in enumerate(cited(point.lines, lines))
    )
    row.sqlmodel_update(
        {
            "name": name[:255],
            "summary": notes.summary,
            "meetings": meetings,
            "error": None,
            "model_name": model_name,
            "written_at": utcnow(),
        }
    )
    db.add(row)
    await db.commit()
    return series_id


async def keep_series_failure(
    db: AsyncSession, owner_user_id: int | None, link: str, error: str
) -> None:
    """Why the series could not be written; its themes stay."""
    row = await _row(db, owner_user_id, link)
    row.error = fitted(error)
    db.add(row)
    await db.commit()


async def notes_of(db: AsyncSession, series: MeetingSeries) -> SeriesNotes:
    """The series read back as it was written: each part's points in
    order, each with its lines."""
    read = SeriesNotes(summary=series.summary)
    points: dict[int, NoteItem] = {}
    for kept, line in await queries.theme_lines(db, series.id):  # type: ignore[arg-type]
        point = points.get(kept.id)  # type: ignore[arg-type]
        if point is None:
            point = (
                Theme(id=kept.id, text=kept.text, status=kept.status)  # type: ignore[arg-type]
                if kept.kind == THEMES
                else NoteItem(id=kept.id, text=kept.text)
            )
            points[kept.id] = point  # type: ignore[index]
            if kept.kind in PARTS:
                getattr(read, kept.kind).append(point)
        if line is not None:
            point.lines.append(line)
    return read
