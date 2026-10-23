"""The reads (and the few writes) behind a series: its link, the meetings
on it, its row, its themes with the lines each cites, and the series a
deleted meeting leaves with no meeting."""

from urllib.parse import urlsplit

from sqlalchemy import delete
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import (
    CalendarEvent,
    Meeting,
    MeetingSeries,
    MeetingTheme,
    MeetingThemeLine,
)
from app.services.shared.queries import owner_clause, owner_filters


def series_link(url: str) -> str:
    """The link a series is known by: the meeting's address without what
    follows it (``?authuser=0``, a Zoom passcode), however it was pasted."""
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{(parts.hostname or '').lower()}{parts.path.rstrip('/')}"


async def meetings_on(
    db: AsyncSession, owner_user_id: int | None, link: str, limit: int | None = None
) -> list[Meeting]:
    """The owner's latest meetings on ``link`` (None: the standalone
    install's), newest first."""
    query = (
        select(Meeting)
        .where(
            owner_clause(Meeting.owner_user_id, owner_user_id),
            col(Meeting.url).istartswith(link),
        )
        .order_by(col(Meeting.created_at).desc(), col(Meeting.id).desc())
    )
    found = (await db.exec(query)).all()
    return [m for m in found if series_link(m.url) == link][:limit]


async def title_of(db: AsyncSession, meeting_ids: list[int]) -> str:
    """The latest calendar event title of those meetings, if any has one."""
    query = (
        select(CalendarEvent.title)
        .where(
            col(CalendarEvent.meeting_id).in_(meeting_ids), CalendarEvent.title != ""
        )
        .order_by(col(CalendarEvent.starts_at).desc())
        .limit(1)
    )
    return (await db.exec(query)).first() or ""


async def series_row(
    db: AsyncSession, owner_user_id: int | None, link: str, lock: bool = False
) -> MeetingSeries | None:
    """The owner's series on ``link``; ``lock``: for this transaction,
    where the engine locks rows (Postgres), so two writers take turns."""
    query = select(MeetingSeries).where(
        owner_clause(MeetingSeries.owner_user_id, owner_user_id),
        MeetingSeries.link == link,
    )
    if lock:
        query = query.with_for_update()
    return (await db.exec(query)).first()


async def series_of(
    db: AsyncSession, owner_user_id: int | None, limit: int
) -> list[MeetingSeries]:
    """An owner's series (every owner's for None), latest written first."""
    query = (
        select(MeetingSeries)
        .where(*owner_filters(MeetingSeries.owner_user_id, owner_user_id))
        .order_by(col(MeetingSeries.written_at).desc(), col(MeetingSeries.id).desc())
        .limit(limit)
    )
    return list((await db.exec(query)).all())


async def one_series(
    db: AsyncSession, owner_user_id: int | None, series_id: int
) -> MeetingSeries | None:
    query = select(MeetingSeries).where(
        MeetingSeries.id == series_id,
        *owner_filters(MeetingSeries.owner_user_id, owner_user_id),
    )
    return (await db.exec(query)).first()


async def theme_lines(
    db: AsyncSession, series_id: int
) -> list[tuple[MeetingTheme, int | None]]:
    """Every point of the series, each part in order, each point once per
    line it cites (in order; None for one that cites none)."""
    query = (
        select(MeetingTheme, MeetingThemeLine.line_id)
        .join(
            MeetingThemeLine,
            col(MeetingThemeLine.theme_id) == MeetingTheme.id,
            isouter=True,
        )
        .where(MeetingTheme.series_id == series_id)
        .order_by(
            col(MeetingTheme.kind), col(MeetingTheme.ord), col(MeetingThemeLine.ord)
        )
    )
    return [(theme, line) for theme, line in (await db.exec(query)).all()]


async def drop_if_empty(db: AsyncSession, owner_user_id: int | None, link: str) -> None:
    """Drop the owner's series on ``link`` once no meeting is on it."""
    if not await meetings_on(db, owner_user_id, link, 1):
        await db.exec(  # type: ignore[call-overload]
            delete(MeetingSeries).where(
                owner_clause(MeetingSeries.owner_user_id, owner_user_id),
                MeetingSeries.link == link,
            )
        )
