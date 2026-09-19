"""Asking a goal how it is doing: progress, pace, and an ETA."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    add_months,
)
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning.goals.meta import GoalMeta, goal_metadata
from app.services.finance.models import (
    FinanceAccount,
)


def goal_progress(*, balance: int, target: int) -> float:
    """Saved-so-far as a fraction of the target, clamped to [0, 1]."""
    if target <= 0:
        return 0.0
    return max(0.0, min(1.0, balance / target))


def goal_monthly_need(meta: GoalMeta, *, balance: int, today: date) -> int:
    """Cents per month this goal asks of the budget right now.

    Zero unless the goal is active with money still to save. A target
    date turns the remainder into remaining/months-left (due this month
    or overdue = 1 month: the rest is wanted now); without a date the
    declared rate is the ask, and no declared rate asks nothing.
    """
    remaining = meta.target_amount - balance
    if meta.status != "active" or remaining <= 0:
        return 0
    if meta.target_date is None:
        return meta.monthly_contribution or 0
    months_left = max(
        1,
        (meta.target_date.year - today.year) * 12
        + (meta.target_date.month - today.month),
    )
    return -(-remaining // months_left)  # ceil division on ints


def goal_eta(
    *, balance: int, target: int, monthly_rate: int | None, today: date
) -> date | None:
    """When the goal lands at ``monthly_rate`` cents/month.

    Already-reached returns ``today``; no rate (or zero) returns ``None``,
    which every caller renders as "never" - spelled out, never recomputed.
    """
    remaining = target - balance
    if remaining <= 0:
        return today
    if not monthly_rate or monthly_rate <= 0:
        return None
    months = -(-remaining // monthly_rate)  # ceil division
    return add_months(today, months)


async def list_goals(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceAccount]:
    """Every account wearing goal metadata - virtual (hidden) and
    linked alike. Filtered in Python: the goal keys live in JSON the
    SQL layer never reads, and the account population is tens, not
    thousands."""
    accounts = await ledger_queries.live_accounts_for_owner(
        db, owner_user_id=owner_user_id
    )
    return [a for a in accounts if goal_metadata(a.metadata_) is not None]


def _observed_rate(snapshots: list[Any]) -> int | None:
    """Trailing growth in cents/month from a date-ascending snapshot
    series; None below 2 points or 14 days of history."""
    if len(snapshots) < 2:
        return None
    first, last = snapshots[0], snapshots[-1]
    days = (last.balance_date - first.balance_date).days
    if days < 14:
        return None
    rate = round((last.balance - first.balance) * 30 / days)
    return rate if rate > 0 else None


async def goal_rates(
    db: AsyncSession, accounts: list[FinanceAccount], *, today: date
) -> dict[int, int | None]:
    """``goal_rate`` for many accounts with ONE snapshot query.

    Declared rates come straight off the metadata; the rest share a
    single balance-snapshot fetch instead of one query per goal.
    """
    rates: dict[int, int | None] = {}
    undeclared: list[FinanceAccount] = []
    for account in accounts:
        meta = goal_metadata(account.metadata_)
        if meta is not None and meta.monthly_contribution:
            rates[account.id] = meta.monthly_contribution
        else:
            undeclared.append(account)
    if undeclared:
        window_start = today - timedelta(days=120)
        rows = await ledger_queries.balance_snapshots_between(
            db, [a.id for a in undeclared], start=window_start, end=today
        )
        by_account: dict[int, list[Any]] = {}
        for snapshot in rows:
            by_account.setdefault(snapshot.account_id, []).append(snapshot)
        for account in undeclared:
            snapshots = sorted(
                by_account.get(account.id, []), key=lambda s: s.balance_date
            )
            rates[account.id] = _observed_rate(snapshots)
    return rates


async def goal_rate(
    db: AsyncSession, account: FinanceAccount, *, today: date
) -> int | None:
    """Cents/month the goal is actually growing at: the declared rate
    when one is set, else the trailing observed rate from the
    account's own balance-snapshot history (>=14 days of it within the
    last 120), else ``None`` - which renders as "never"."""
    rates = await goal_rates(db, [account], today=today)
    return rates.get(account.id)
