"""Reads across every owner's research, for figures rather than a page."""

from datetime import datetime

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.research.models import (
    ResearchCounts,
    ResearchItem,
    ResearchWatch,
)
from app.services.shared.queries import within


async def item_counts(
    db: AsyncSession, since: datetime | None = None
) -> list[tuple[str, str, int]]:
    """Live items fetched since ``since`` (all, when None), as ``(source,
    kind, count)``: one grouped read, never an item."""
    found = await db.exec(
        select(ResearchItem.source, ResearchItem.kind, func.count())
        .where(
            col(ResearchItem.deleted_at).is_(None),
            *within(ResearchItem.fetched_at, since, None),
        )
        .group_by(ResearchItem.source, ResearchItem.kind)
    )
    return [(source, kind, int(n)) for source, kind, n in found.all()]


async def research_counts(db: AsyncSession) -> ResearchCounts:
    """The ``ResearchCounts``, across every owner."""
    watches, last = (
        await db.exec(
            select(func.count(), func.max(ResearchWatch.refreshed_at)).select_from(
                ResearchWatch
            )
        )
    ).one()
    items = (await db.exec(select(func.count()).select_from(ResearchItem))).one()
    return ResearchCounts(watches=watches, items=items, last_refresh=last)
