"""A run's session, as the app knows it: its other runs, whether a
runner took one before it (the agent may have begun the session then),
and what they have cost together."""

from typing import Any

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .models import RunnerRun


def _others(run_id: int) -> list[Any]:
    """Clauses keeping runs to the other runs of this run's session: none
    for a run in no session."""
    its = (
        select(RunnerRun.session_id)
        .where(col(RunnerRun.id) == run_id)
        .scalar_subquery()
    )
    return [col(RunnerRun.session_id) == its, col(RunnerRun.id) != run_id]


async def taken(db: AsyncSession, run_id: int) -> bool:
    """Whether a runner took an earlier run of this run's session: the
    agent may have begun the session then."""
    query = select(RunnerRun.id).where(
        *_others(run_id),
        col(RunnerRun.id) < run_id,
        col(RunnerRun.claimed_at).is_not(None),
    )
    return (await db.exec(query.limit(1))).first() is not None


async def cost(db: AsyncSession, run_id: int) -> float:
    """What the other runs of this run's session have cost, together:
    every one that answered before it, whichever was asked first."""
    query = select(func.coalesce(func.sum(col(RunnerRun.cost)), 0.0)).where(
        *_others(run_id)
    )
    return float((await db.exec(query)).one())
