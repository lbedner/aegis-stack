"""Insights: listing, counting, dismissal."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    ANALYST_NOTE_INSIGHT_TYPE,
)
from app.services.finance.domains.planning import queries
from app.services.finance.models import (
    FinanceInsight,
)


async def list_insights(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    status: str | None = "new",
    insight_type: str | None = None,
    exclude_types: Sequence[str] = (),
) -> list[FinanceInsight]:
    """Insights for an owner (default: only ``new``), newest first.

    ``insight_type`` narrows to one kind, ``exclude_types`` drops kinds.
    One table, two audiences: the anomaly list and the analyst's notes,
    each wanting the other filtered out at the query rather than in the UI.
    """
    return await queries.insights_list(
        db,
        owner_user_id=owner_user_id,
        status=status,
        insight_type=insight_type,
        exclude_types=exclude_types,
    )


async def count_new_insights(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> int:
    """How many unseen insights — the finance card's badge count."""
    # Analyst notes are excluded: the badge means "things to act on", and a
    # note saying everything is fine is not one of them.
    return await queries.new_insight_count(
        db, owner_user_id=owner_user_id, exclude_type=ANALYST_NOTE_INSIGHT_TYPE
    )


async def dismiss_insight(
    db: AsyncSession, insight_id: int, *, owner_user_id: int | None = None
) -> FinanceInsight | None:
    """Dismiss an insight (survives re-runs via its dedup_key)."""
    insight = await queries.insight_by_id(db, insight_id, owner_user_id=owner_user_id)
    if insight is None:
        return None
    insight.status = "dismissed"
    insight.is_read = True
    insight.dismissed_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(insight)
    await db.flush()
    return insight
