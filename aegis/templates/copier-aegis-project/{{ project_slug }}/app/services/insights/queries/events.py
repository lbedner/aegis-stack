"""Reads for the insight event timeline."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.insights.models import EventOrigin, InsightEvent


async def events_where(
    db: AsyncSession,
    *,
    event_types: Iterable[str] | None = None,
    origin: EventOrigin | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    order: Literal["date_asc", "date_desc"] | None = "date_desc",
    limit: int | None = None,
    project_id: int | None = None,
) -> list[InsightEvent]:
    """Timeline rows. ``since``/``until`` are inclusive; ``project_id``
    scopes when given (the column only exists on per-user builds, and
    only a scoped call ever names it)."""
    stmt = select(InsightEvent)
    if event_types is not None:
        stmt = stmt.where(InsightEvent.event_type.in_(list(event_types)))  # type: ignore[union-attr]
    if origin is not None:
        stmt = stmt.where(InsightEvent.origin == origin)
    if since is not None:
        stmt = stmt.where(InsightEvent.date >= since)
    if until is not None:
        stmt = stmt.where(InsightEvent.date <= until)
    if project_id is not None:
        stmt = stmt.where(InsightEvent.project_id == project_id)  # type: ignore[attr-defined]
    if order == "date_asc":
        stmt = stmt.order_by(InsightEvent.date.asc())  # type: ignore[union-attr]
    elif order == "date_desc":
        stmt = stmt.order_by(InsightEvent.date.desc())  # type: ignore[union-attr]
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await db.exec(stmt)).all())
