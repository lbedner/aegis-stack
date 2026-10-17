"""The money reads over the usage ledgers: spend per day and per action, the
users it was spent on, the span of the ledger, and what voice calls cost.
Set-shaped inputs (a half-open ``[start, end)`` window), map-shaped outputs,
no business logic; the Overseer's Costs section shapes them."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import case, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.spend.recording import VOICE_ACTIONS
from app.services.ai.models.llm import LLMUsage
from app.services.shared.queries import within

from .schemas import ActionSpend


async def daily_spend(
    session: AsyncSession, start: datetime, end: datetime
) -> dict[date, float]:
    """Spend per calendar day in the window, voice included (days with none
    absent)."""
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
    """What transcription, speech and live calls cost in the window, read
    from the one ledger by action (every voice kind is named, at 0 when
    unused)."""
    rows = await session.exec(
        select(LLMUsage.action, func.sum(LLMUsage.total_cost))
        .where(
            *within(LLMUsage.timestamp, start, end),
            col(LLMUsage.action).in_(VOICE_ACTIONS),
        )
        .group_by(col(LLMUsage.action))
    )
    spent = {action: float(cost or 0) for action, cost in rows.all()}
    return {label: spent.get(action, 0.0) for action, label in VOICE_ACTIONS.items()}


async def usage_windows(
    session: AsyncSession, starts: Sequence[datetime | None]
) -> list[tuple[int, int, float]]:
    """Requests, tokens and cost since each of ``starts`` (None: the whole
    ledger), in one read."""
    tokens = LLMUsage.input_tokens + LLMUsage.output_tokens

    def since(start: datetime | None, value: Any) -> Any:
        return value if start is None else case((LLMUsage.timestamp >= start, value))

    columns = [
        figure
        for start in starts
        for figure in (
            func.count(since(start, LLMUsage.id)),
            func.coalesce(func.sum(since(start, tokens)), 0),
            func.coalesce(func.sum(since(start, LLMUsage.total_cost)), 0.0),
        )
    ]
    row = (await session.exec(select(*columns))).one()
    return [
        (int(row[i]), int(row[i + 1]), float(row[i + 2]))
        for i in range(0, len(columns), 3)
    ]
