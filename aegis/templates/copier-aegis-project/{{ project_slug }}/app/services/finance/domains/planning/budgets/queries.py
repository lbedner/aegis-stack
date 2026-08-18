"""Reads against the budget tables, and the outflow fetches that feed them.

Statement builders only - no business logic, no writes. These are here
rather than in the planning package's shared ``queries`` because nothing
outside this package asks for them: a period's lines, a dismissal marker,
the tallied outflow rows a summary is built from.

``month_bounds`` sits with them on purpose: every one of these reads is
scoped by a YYYYMM period, and turning that period into a date range is
the first half of building the predicate.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import add_months
from app.services.finance.domains.planning.queries import spend_filters
from app.services.finance.models import (
    FinanceBudget,
    FinanceBudgetCategory,
    FinanceTransaction,
)


def month_bounds(period_month: int) -> tuple[date, date]:
    """``[start, end)`` date range for a YYYYMM period."""
    year, month = divmod(period_month, 100)
    start = date(year, month, 1)
    return start, add_months(start, 1)


async def monthly_budget(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> FinanceBudget | None:
    """The owner's standing "Monthly" budget row, if it exists."""
    query = select(FinanceBudget).where(
        FinanceBudget.name == "Monthly",
        FinanceBudget.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceBudget.owner_user_id == owner_user_id)
    return (await db.exec(query.order_by(FinanceBudget.id))).first()


async def budget_lines_for_period(
    db: AsyncSession, budget_id: int, period_month: int
) -> list[FinanceBudgetCategory]:
    return list(
        (
            await db.exec(
                select(FinanceBudgetCategory).where(
                    FinanceBudgetCategory.budget_id == budget_id,
                    FinanceBudgetCategory.period_month == period_month,
                )
            )
        ).all()
    )


async def budget_lines_with_category(
    db: AsyncSession, budget_id: int
) -> list[FinanceBudgetCategory]:
    """Category-carrying lines across ALL periods, dismissal markers
    included (period-less rows)."""
    return list(
        (
            await db.exec(
                select(FinanceBudgetCategory).where(
                    FinanceBudgetCategory.budget_id == budget_id,
                    FinanceBudgetCategory.category_id.is_not(None),
                )
            )
        ).all()
    )


async def dismissal_marker_lines(
    db: AsyncSession, budget_id: int
) -> list[FinanceBudgetCategory]:
    """Period-less category rows - the "declined suggestion" markers."""
    return list(
        (
            await db.exec(
                select(FinanceBudgetCategory).where(
                    FinanceBudgetCategory.budget_id == budget_id,
                    FinanceBudgetCategory.category_id.is_not(None),
                    FinanceBudgetCategory.period_month.is_(None),
                )
            )
        ).all()
    )


async def budget_line_for_target(
    db: AsyncSession,
    budget_id: int,
    *,
    period_month: int,
    category_id: int | None,
    payee_key: str | None,
) -> FinanceBudgetCategory | None:
    """The period's line for one target: a category, a payee key, or the
    overall (both-NULL) line."""
    filters = [
        FinanceBudgetCategory.budget_id == budget_id,
        FinanceBudgetCategory.period_month == period_month,
    ]
    if category_id is not None:
        filters.append(FinanceBudgetCategory.category_id == category_id)
    elif payee_key is not None:
        filters.append(FinanceBudgetCategory.payee_key == payee_key)
    else:
        filters.append(FinanceBudgetCategory.category_id.is_(None))
        filters.append(FinanceBudgetCategory.payee_key.is_(None))
    return (await db.exec(select(FinanceBudgetCategory).where(*filters))).first()


async def budget_line_by_id(
    db: AsyncSession, line_id: int, *, owner_user_id: int | None = None
) -> FinanceBudgetCategory | None:
    filters = [FinanceBudgetCategory.id == line_id]
    if owner_user_id is not None:
        filters.append(FinanceBudgetCategory.owner_user_id == owner_user_id)
    return (await db.exec(select(FinanceBudgetCategory).where(*filters))).first()


async def categorized_outflow_history(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceTransaction]:
    """Live, non-transfer, categorized outflows across all time - the
    lookback corpus budget suggestions average over."""
    query = select(FinanceTransaction).where(
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.is_transfer.is_(False),
        FinanceTransaction.amount < 0,
        FinanceTransaction.category_id.is_not(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
    return list((await db.exec(query)).all())


async def outflow_tuples(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    start: date,
    end: date | None = None,
    account_ids: list[int] | None = None,
) -> list[tuple]:
    """(category_id, merchant_name, original_description, name, amount,
    recurring_stream_id) for every countable outflow in the window - ONE
    fetch a caller tallies by category / payee key / stream in a single
    Python pass. This is the query that keeps budget_summary O(1) in the
    number of lines and streams."""
    rows = (
        await db.exec(
            select(
                FinanceTransaction.category_id,
                FinanceTransaction.merchant_name,
                FinanceTransaction.original_description,
                FinanceTransaction.name,
                FinanceTransaction.amount,
                FinanceTransaction.recurring_stream_id,
            ).where(*spend_filters(owner_user_id, start, end, account_ids))
        )
    ).all()
    return list(rows)


async def sum_amount_where(db: AsyncSession, filters: list) -> int:
    """Signed sum of ``FinanceTransaction.amount`` under caller-built
    predicate fragments (see ``spend_filters``)."""
    total = (
        await db.exec(
            select(func.coalesce(func.sum(FinanceTransaction.amount), 0)).where(
                *filters
            )
        )
    ).one()
    return int(total or 0)


async def grouped_category_totals_where(db: AsyncSession, filters: list) -> list[tuple]:
    """(category_id, count, summed amount) grouped by category under
    caller-built predicate fragments."""
    rows = (
        await db.exec(
            select(
                FinanceTransaction.category_id,
                func.count(),
                func.sum(FinanceTransaction.amount),
            )
            .where(*filters)
            .group_by(FinanceTransaction.category_id)
        )
    ).all()
    return list(rows)


async def allocated_budget_lines(
    db: AsyncSession, budget_id: int
) -> list[FinanceBudgetCategory]:
    """Lines with a positive allocation, all periods."""
    return list(
        (
            await db.exec(
                select(FinanceBudgetCategory).where(
                    FinanceBudgetCategory.budget_id == budget_id,
                    FinanceBudgetCategory.allocated_amount > 0,
                )
            )
        ).all()
    )
