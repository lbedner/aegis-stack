"""Batched read queries shared across the planning domain.

Set-shaped inputs, map-shaped outputs: a caller holding many budget lines
asks for all of their spend at once and gets a dict back, so the per-line
query loop cannot be reintroduced. Statement builders only - no business
logic, no writes.

Cross-domain reads only. A query just one domain issues lives in that
domain's own ``queries`` module (``budgets/queries.py``,
``recurring/queries.py``) - this file is what more than one of them asks
for.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceAccount,
    FinanceInsight,
    FinanceTransaction,
    FinanceTransactionSplit,
)
from app.services.finance.utils import transaction_payee_key


def spend_filters(
    owner_user_id: int | None,
    start: date,
    end: date | None = None,
    account_ids: list[int] | None = None,
) -> list[object]:
    """The shared "countable spend" predicate: live accounts,
    non-duplicate, report-included outflows from ``start`` (exclusive of
    ``end`` when given, optionally scoped to ``account_ids``)."""
    live_accounts = select(FinanceAccount.id).where(FinanceAccount.deleted_at.is_(None))
    filters: list[object] = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
        FinanceTransaction.excluded_from_reports.is_(False),
        FinanceTransaction.account_id.in_(live_accounts),
        FinanceTransaction.amount < 0,
        FinanceTransaction.date_ >= start,
    ]
    if end is not None:
        filters.append(FinanceTransaction.date_ < end)
    if account_ids is not None:
        filters.append(FinanceTransaction.account_id.in_(account_ids))
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    return filters


_spend_filters = spend_filters


async def spend_by_category(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    start: date,
    end: date,
    category_ids: Iterable[int],
) -> dict[int, int]:
    """Positive cents spent per category over ``[start, end)`` - two
    queries regardless of how many categories are asked for.

    Split-aware: a split parent's own category stops counting and its
    lines count instead (same window/account predicate, applied to the
    parent they hang off), so a split never double-counts."""
    wanted = set(category_ids)
    if not wanted:
        return {}
    filters = _spend_filters(owner_user_id, start, end)
    parent_rows = (
        await db.exec(
            select(
                FinanceTransaction.category_id,
                func.sum(FinanceTransaction.amount),
            )
            .where(
                *filters,
                FinanceTransaction.is_split.is_(False),
                FinanceTransaction.category_id.in_(wanted),
            )
            .group_by(FinanceTransaction.category_id)
        )
    ).all()
    split_rows = (
        await db.exec(
            select(
                FinanceTransactionSplit.category_id,
                func.sum(FinanceTransactionSplit.amount),
            )
            .join(
                FinanceTransaction,
                FinanceTransaction.id
                == FinanceTransactionSplit.parent_transaction_id,
            )
            .where(
                *filters,
                FinanceTransaction.is_split.is_(True),
                FinanceTransactionSplit.category_id.in_(wanted),
            )
            .group_by(FinanceTransactionSplit.category_id)
        )
    ).all()
    spent: dict[int, int] = {}
    for category_id, total in [*parent_rows, *split_rows]:
        spent[category_id] = spent.get(category_id, 0) + int(-(total or 0))
    return spent


async def spend_by_payee_key(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    start: date,
    end: date,
    payee_keys: Iterable[str],
) -> dict[str, int]:
    """Positive cents spent per payee grouping key over ``[start, end)``.

    The key is Python-computed (first-4-normalized-token rule), so this
    fetches the period's spend rows once and buckets them - one query no
    matter how many keys are asked for.
    """
    wanted = set(payee_keys)
    if not wanted:
        return {}
    filters = _spend_filters(owner_user_id, start, end)
    rows = (
        await db.exec(
            select(
                FinanceTransaction.merchant_name,
                FinanceTransaction.original_description,
                FinanceTransaction.name,
                FinanceTransaction.amount,
            ).where(*filters)
        )
    ).all()
    spent: dict[str, int] = {}
    for merchant_name, original_description, name, amount in rows:
        key = transaction_payee_key(merchant_name, original_description, name)
        if key in wanted:
            spent[key] = spent.get(key, 0) + -amount
    return spent


# -- goals --------------------------------------------------------------------


async def goal_transfer_dates(
    db: AsyncSession, account_ids: list[int], *, start: date, end: date
) -> list[tuple[int, date]]:
    """(account_id, date) of inbound transfer legs on linked goal
    accounts in the window - which months are already funded."""
    if not account_ids:
        return []
    rows = (
        await db.exec(
            select(FinanceTransaction.account_id, FinanceTransaction.date_).where(
                FinanceTransaction.account_id.in_(account_ids),
                FinanceTransaction.is_transfer.is_(True),
                FinanceTransaction.amount > 0,
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.date_ >= start,
                FinanceTransaction.date_ <= end,
            )
        )
    ).all()
    return list(rows)


# -- envelopes ----------------------------------------------------------------


async def accounts_of_type(
    db: AsyncSession, *, account_type: str, owner_user_id: int | None = None
) -> list[FinanceAccount]:
    query = select(FinanceAccount).where(
        FinanceAccount.deleted_at.is_(None),
        FinanceAccount.account_type == account_type,
    )
    if owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    return list((await db.exec(query.order_by(FinanceAccount.id))).all())


# -- insights -----------------------------------------------------------------


async def insights_list(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    status: str | None = "new",
    insight_type: str | None = None,
    exclude_types: Sequence[str] = (),
) -> list[FinanceInsight]:
    query = select(FinanceInsight)
    if owner_user_id is not None:
        query = query.where(FinanceInsight.owner_user_id == owner_user_id)
    if status is not None:
        query = query.where(FinanceInsight.status == status)
    if insight_type is not None:
        query = query.where(FinanceInsight.insight_type == insight_type)
    if exclude_types:
        query = query.where(FinanceInsight.insight_type.notin_(list(exclude_types)))
    query = query.order_by(FinanceInsight.id.desc())
    return list((await db.exec(query)).all())


async def new_insight_count(
    db: AsyncSession, *, owner_user_id: int | None = None, exclude_type: str
) -> int:
    query = (
        select(func.count())
        .select_from(FinanceInsight)
        .where(
            FinanceInsight.status == "new",
            FinanceInsight.insight_type != exclude_type,
        )
    )
    if owner_user_id is not None:
        query = query.where(FinanceInsight.owner_user_id == owner_user_id)
    return (await db.exec(query)).one()


async def insight_by_id(
    db: AsyncSession, insight_id: int, *, owner_user_id: int | None = None
) -> FinanceInsight | None:
    query = select(FinanceInsight).where(FinanceInsight.id == insight_id)
    if owner_user_id is not None:
        query = query.where(FinanceInsight.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()
