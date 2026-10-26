"""Reads across every owner's research, for figures rather than a page."""

from datetime import datetime

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.research.models import ResearchItem
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
