"""The budget itself, and the individual limits set against it.

One standing budget row per owner; the month-by-month allocations are
lines hanging off it. Everything here is about setting or clearing one
limit and answering for it immediately - reading the whole period back
is ``summary``, proposing new lines is ``suggestions``.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import accounts, categories
from app.services.finance.domains.planning import queries as planning_queries
from app.services.finance.domains.planning.budgets import queries
from app.services.finance.models import FinanceBudget, FinanceBudgetCategory
from app.services.finance.schemas import BudgetLineResponse
from app.services.finance.utils import (
    DEFAULT_CURRENCY,
    current_period_month,
    utcnow,
)


def budget_line_status(
    allocated_amount: int, spent_amount: int
) -> Literal["good", "warn", "critical"]:
    """good / warn / critical - budgets warn at 80% spent, not the 70% a
    resource-utilization card would use (see backend_modal's CPU/Memory
    thresholds - a different domain, not reused here on purpose)."""
    if allocated_amount <= 0:
        return "critical" if spent_amount > 0 else "good"
    pct = spent_amount / allocated_amount
    if pct >= 1.0:
        return "critical"
    if pct >= 0.8:
        return "warn"
    return "good"


async def get_or_create_budget(
    db: AsyncSession, *, owner_user_id: int | None, period_month: int
) -> FinanceBudget:
    """The owner's one standing "Monthly" budget - created on first use,
    reused after (one SELECT, one INSERT only the first time ever).

    ``period_month`` only seeds ``start_date`` on that first creation;
    every later month reuses this same row. Each month's actual
    allocations live on ``FinanceBudgetCategory``, keyed by
    ``period_month`` - the budget definition itself doesn't repeat.
    """
    existing = await queries.monthly_budget(db, owner_user_id=owner_user_id)
    if existing is not None:
        return existing
    await accounts.get_or_create_currency(db, DEFAULT_CURRENCY)
    start, _ = queries.month_bounds(period_month)
    budget = FinanceBudget(
        # NOT NULL column - standalone (no-auth) installs use the same
        # ``0`` owner sentinel ``create_recurring_stream`` already does.
        owner_user_id=0 if owner_user_id is None else owner_user_id,
        name="Monthly",
        period="monthly",
        start_date=start,
    )
    db.add(budget)
    await db.flush()
    return budget


async def lines_in_force(
    db: AsyncSession, *, budget_id: int, period_month: int
) -> list[FinanceBudgetCategory]:
    """The plan this period runs on, inheriting the last one if empty.

    A budget is a standing decision, not a monthly chore: allocations are
    keyed by period, so without this every month opened as "everything
    else" and the only way back was to type it all in again.

    The ONLY read of a period's lines. Every surface that asks - the
    budget page, the projection, the month strip, the uncovered-spend
    rate - has to get the same answer, and while the summary was the
    only caller that inherited, the same month read differently
    depending on which tab was opened first.

    Amounts only. Spend is computed from this period's transactions, and
    a copied ``spent_amount`` would read as money already gone. A period
    with any line of its own is a month someone has decided about, and is
    never touched.
    """
    existing = await queries.budget_lines_for_period(db, budget_id, period_month)
    if existing:
        return existing

    source = await queries.latest_period_with_lines(db, budget_id, period_month)
    if source is None:
        return []

    copied = [
        FinanceBudgetCategory(
            owner_user_id=line.owner_user_id,
            budget_id=budget_id,
            period_month=period_month,
            category_id=line.category_id,
            payee_key=line.payee_key,
            payee_label=line.payee_label,
            allocated_amount=line.allocated_amount,
            rollover_enabled=line.rollover_enabled,
            currency=line.currency,
        )
        for line in await queries.budget_lines_for_period(db, budget_id, source)
    ]
    # The dashboard opens several panels at once and every one of them
    # asks this question, so two callers can both find the period empty
    # and both seed it. The partial unique index settles who wins; the
    # loser wants the winner's rows, not a failed request. The savepoint
    # keeps the rejection from poisoning the surrounding transaction.
    try:
        async with db.begin_nested():
            db.add_all(copied)
    except IntegrityError:
        return await queries.budget_lines_for_period(db, budget_id, period_month)
    return copied


async def spend_for_target(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    period_month: int,
    category_id: int | None,
    payee_key: str | None,
) -> int:
    """Positive cents spent this period against one category or payee -
    a single scoped query, for the one-line response an upsert/delete
    needs right away. ``budget_summary`` does the all-lines-at-once
    version of this same fetch; this is deliberately the one-off
    sibling, not a call site of it, so setting a single line never
    pulls the whole period's transaction history."""
    start, end = queries.month_bounds(period_month)
    if category_id is not None:
        spent = await planning_queries.spend_by_category(
            db,
            owner_user_id=owner_user_id,
            start=start,
            end=end,
            category_ids={category_id},
        )
        return spent.get(category_id, 0)
    if payee_key is not None:
        spent = await planning_queries.spend_by_payee_key(
            db,
            owner_user_id=owner_user_id,
            start=start,
            end=end,
            payee_keys={payee_key},
        )
        return spent.get(payee_key, 0)
    return 0


async def upsert_budget_line(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    period_month: int | None,
    category_id: int | None,
    payee_key: str | None,
    payee_label: str | None,
    allocated_amount: int,
    rollover_enabled: bool = False,
) -> BudgetLineResponse:
    """Set (create or replace) one budget line for the period. One
    lookup on the matching partial-unique key, one write, plus one
    scoped spend query so the response's status is correct immediately
    (a category with existing spend shouldn't show "good" at 0)."""
    month = period_month or current_period_month()
    budget = await get_or_create_budget(
        db, owner_user_id=owner_user_id, period_month=month
    )
    line = await queries.budget_line_for_target(
        db,
        budget.id,
        period_month=month,
        category_id=category_id,
        payee_key=payee_key,
    )
    if line is None:
        line = FinanceBudgetCategory(
            owner_user_id=0 if owner_user_id is None else owner_user_id,
            budget_id=budget.id,
            category_id=category_id,
            payee_key=payee_key,
            period_month=month,
        )
    line.payee_label = payee_label
    line.allocated_amount = allocated_amount
    line.rollover_enabled = rollover_enabled
    line.updated_at = utcnow()
    db.add(line)
    await db.flush()

    category_name = None
    if line.category_id is not None:
        names = await categories.category_names(db, {line.category_id})
        category_name = names.get(line.category_id)
    spent = await spend_for_target(
        db,
        owner_user_id=owner_user_id,
        period_month=month,
        category_id=line.category_id,
        payee_key=line.payee_key,
    )
    return BudgetLineResponse(
        id=line.id,
        category_id=line.category_id,
        category_name=category_name,
        payee_key=line.payee_key,
        payee_label=line.payee_label,
        allocated_amount=line.allocated_amount,
        spent_amount=spent,
        status=budget_line_status(line.allocated_amount, spent),
    )


async def delete_budget_line(
    db: AsyncSession, line_id: int, *, owner_user_id: int | None = None
) -> bool:
    line = await queries.budget_line_by_id(db, line_id, owner_user_id=owner_user_id)
    if line is None:
        return False
    await db.delete(line)
    await db.flush()
    return True
