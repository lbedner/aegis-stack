"""The money reads over the usage ledgers: spend per day and per action, the
users it was spent on, the span of the ledger, and what voice calls cost.
Set-shaped inputs (a half-open ``[start, end)`` window), map-shaped outputs,
no business logic; the Overseer's Costs section shapes them."""

from datetime import UTC, date, datetime

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.models.llm import LLMUsage
from app.services.shared.queries import within

from .schemas import ActionSpend


async def daily_spend(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[date, float]:
    """Model spend per calendar day in the window (days with none absent)."""
    day = func.date(LLMUsage.timestamp)
    rows = await session.exec(
        select(day, func.sum(LLMUsage.total_cost))
        .where(*within(LLMUsage.timestamp, start, end))
        .group_by(day)
    )
    return {
        (d if isinstance(d, date) else date.fromisoformat(str(d))): float(cost or 0)
        for d, cost in rows.all()
    }


async def spend_by_action(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[str, ActionSpend]:
    """``{action: what it cost}`` in the window."""
    rows = await session.exec(
        select(LLMUsage.action, func.count(), func.sum(LLMUsage.total_cost))
        .where(*within(LLMUsage.timestamp, start, end))
        .group_by(col(LLMUsage.action))
    )
    return {
        action: ActionSpend(calls=int(n), cost=float(cost or 0))
        for action, n, cost in rows.all()
    }


async def spend_by_user_action(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[str | None, dict[str, ActionSpend]]:
    """``{user: {action: what it cost}}`` in the window (``None``: calls made
    for no user, a background job's)."""
    rows = await session.exec(
        select(
            LLMUsage.user_id,
            LLMUsage.action,
            func.count(),
            func.sum(LLMUsage.total_cost),
        )
        .where(*within(LLMUsage.timestamp, start, end))
        .group_by(col(LLMUsage.user_id), col(LLMUsage.action))
    )
    spend: dict[str | None, dict[str, ActionSpend]] = {}
    for user, action, n, cost in rows.all():
        spend.setdefault(user, {})[action] = ActionSpend(
            calls=int(n), cost=float(cost or 0)
        )
    return spend


async def spenders(session: AsyncSession, start: datetime, end: datetime) -> int:
    """How many distinct users the window's calls were made for."""
    result = await session.exec(
        select(func.count(func.distinct(LLMUsage.user_id))).where(
            *within(LLMUsage.timestamp, start, end)
        )
    )
    return int(result.one() or 0)


async def first_call(session: AsyncSession) -> datetime | None:
    """When the first model call on record was made."""
    result = await session.exec(select(func.min(LLMUsage.timestamp)))
    return result.one()


async def voice_spend(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[str, float]:
    """What transcription and speech cost in the window. Their ledgers keep
    aware timestamps, so the window is made aware to match. Only where
    voice is installed."""
    from app.services.ai.models.voice_usage import STTUsage, TTSUsage

    aware = (start.replace(tzinfo=UTC), end.replace(tzinfo=UTC))
    spend: dict[str, float] = {}
    for label, table in (("Transcription", STTUsage), ("Speech", TTSUsage)):
        result = await session.exec(
            select(func.coalesce(func.sum(table.total_cost), 0.0)).where(
                *within(table.timestamp, *aware)
            )
        )
        spend[label] = float(result.one() or 0)
    return spend
