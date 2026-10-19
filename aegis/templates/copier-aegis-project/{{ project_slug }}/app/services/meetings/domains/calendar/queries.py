"""The reads behind the agents' calendars."""

from datetime import datetime, timedelta

from sqlalchemy import delete, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.models import CalendarEvent, Meeting

# How early an agent is sent: the job runs each minute, so by the start.
EARLY = timedelta(minutes=1)


async def events_of(
    db: AsyncSession,
    account_ids: list[int],
    start: datetime,
    end: datetime,
    keys: list[str],
) -> list[CalendarEvent]:
    """Those agents' kept meetings from ``start`` to ``end``, and any of
    ``keys`` wherever they were (one moved into the window)."""
    query = select(CalendarEvent).where(
        col(CalendarEvent.account_id).in_(account_ids),
        or_(
            col(CalendarEvent.starts_at).between(start, end),
            col(CalendarEvent.key).in_(keys),
        ),
    )
    return list((await db.exec(query)).all())


async def drop_unsent_before(
    db: AsyncSession, account_ids: list[int], before: datetime
) -> None:
    """Those agents' meetings that started before ``before`` and were never
    sent into: past what is kept of a calendar."""
    await db.exec(  # type: ignore[call-overload]
        delete(CalendarEvent).where(
            col(CalendarEvent.account_id).in_(account_ids),
            CalendarEvent.starts_at < before,
            col(CalendarEvent.sent_at).is_(None),
        )
    )


async def due(db: AsyncSession, now: datetime) -> list[CalendarEvent]:
    """Every agent's meetings starting within ``EARLY`` of ``now`` or under
    way, with a link, not cancelled, and never sent into; earliest first."""
    query = (
        select(CalendarEvent)
        .where(
            CalendarEvent.starts_at <= now + EARLY,
            CalendarEvent.ends_at > now,
            col(CalendarEvent.url).is_not(None),
            col(CalendarEvent.cancelled).is_(False),
            col(CalendarEvent.sent_at).is_(None),
        )
        .order_by(col(CalendarEvent.starts_at), col(CalendarEvent.id))
    )
    return list((await db.exec(query)).all())


async def between(
    db: AsyncSession, account_ids: list[int], start: datetime, end: datetime
) -> list[tuple[CalendarEvent, str | None]]:
    """Those agents' meetings starting from ``start`` until ``end``, earliest
    first, each with the status of the call it became, if it did."""
    query = (
        select(CalendarEvent, Meeting.status)
        .join(Meeting, col(Meeting.id) == CalendarEvent.meeting_id, isouter=True)
        .where(
            col(CalendarEvent.account_id).in_(account_ids),
            CalendarEvent.starts_at >= start,
            CalendarEvent.starts_at < end,
        )
        .order_by(col(CalendarEvent.starts_at), col(CalendarEvent.id))
    )
    return list((await db.exec(query)).all())
