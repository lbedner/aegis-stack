"""Reads for payees: the merchant rows and what points at them.

A merchant is the grouping key transactions and recurring streams share,
so most of these answer "what does this payee still own" - the question
a merge or a rename has to settle before it writes.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceIcon,
    FinanceMerchant,
    FinanceRecurringStream,
    FinanceTransaction,
)


async def merchant_by_id(db: AsyncSession, merchant_id: int) -> FinanceMerchant | None:
    return await db.get(FinanceMerchant, merchant_id)


async def merchants_for_owner(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceMerchant]:
    """The owner's payees plus global (NULL-owner) seeds, name-sorted."""
    query = select(FinanceMerchant).where(FinanceMerchant.deleted_at.is_(None))
    if owner_user_id is not None:
        query = query.where(
            or_(
                FinanceMerchant.owner_user_id == owner_user_id,
                FinanceMerchant.owner_user_id.is_(None),
            )
        )
    else:
        query = query.where(FinanceMerchant.owner_user_id.is_(None))
    rows = (await db.exec(query.order_by(FinanceMerchant.name))).all()
    return list(rows)


async def merchant_by_normalized(
    db: AsyncSession, *, normalized: str, owner_user_id: int | None = None
) -> FinanceMerchant | None:
    return (
        await db.exec(
            select(FinanceMerchant).where(
                FinanceMerchant.normalized_name == normalized,
                FinanceMerchant.deleted_at.is_(None),
                FinanceMerchant.owner_user_id == owner_user_id
                if owner_user_id is not None
                else FinanceMerchant.owner_user_id.is_(None),
            )
        )
    ).first()


async def icons_by_domains(
    db: AsyncSession, domains: Iterable[str]
) -> dict[str, FinanceIcon]:
    """Stored favicon rows by domain in one query - positive and negative
    entries alike (a NULL ``icon_b64`` row is information: don't refetch)."""
    wanted = sorted(set(domains))
    if not wanted:
        return {}
    rows = (
        await db.exec(select(FinanceIcon).where(FinanceIcon.domain.in_(wanted)))
    ).all()
    return {row.domain: row for row in rows}


async def merchants_by_ids(
    db: AsyncSession, ids: set[int] | list[int]
) -> dict[int, FinanceMerchant]:
    """Merchants by id in one query (names and websites come off the
    same rows - callers project what they need)."""
    wanted = [i for i in set(ids) if i is not None]
    if not wanted:
        return {}
    rows = (
        await db.exec(select(FinanceMerchant).where(FinanceMerchant.id.in_(wanted)))
    ).all()
    return {row.id: row for row in rows}


async def live_merchants_by_ids(
    db: AsyncSession, ids: list[int]
) -> list[FinanceMerchant]:
    if not ids:
        return []
    return list(
        (
            await db.exec(
                select(FinanceMerchant).where(
                    FinanceMerchant.id.in_(ids),
                    FinanceMerchant.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def live_transactions_by_merchants(
    db: AsyncSession, merchant_ids: list[int]
) -> list[FinanceTransaction]:
    if not merchant_ids:
        return []
    return list(
        (
            await db.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.merchant_id.in_(merchant_ids),
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def live_streams_by_merchants(
    db: AsyncSession, merchant_ids: list[int]
) -> list[FinanceRecurringStream]:
    if not merchant_ids:
        return []
    return list(
        (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.merchant_id.in_(merchant_ids),
                    FinanceRecurringStream.deleted_at.is_(None),
                )
            )
        ).all()
    )


async def merchant_usage_rows(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    account_ids: list[int] | None = None,
) -> list[tuple]:
    """(merchant_id, count, total, last_date) per merchant, one grouped
    query over live rows."""
    query = (
        select(
            FinanceTransaction.merchant_id,
            func.count(FinanceTransaction.id),
            func.sum(FinanceTransaction.amount),
            func.max(FinanceTransaction.date_),
        )
        .where(
            FinanceTransaction.deleted_at.is_(None),
            FinanceTransaction.merchant_id.is_not(None),
        )
        .group_by(FinanceTransaction.merchant_id)
    )
    if owner_user_id is not None:
        query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
    if account_ids is not None:
        query = query.where(FinanceTransaction.account_id.in_(account_ids))
    return list((await db.exec(query)).all())


async def live_transactions_for_merchant(
    db: AsyncSession, merchant_id: int, *, owner_user_id: int | None = None
) -> list[FinanceTransaction]:
    query = select(FinanceTransaction).where(
        FinanceTransaction.merchant_id == merchant_id,
        FinanceTransaction.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
    return list((await db.exec(query)).all())


async def payeeless_transactions(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceTransaction]:
    """Every live transaction with no assigned payee - the shared corpus
    behind payee grouping, group assignment, and the "similar" offer
    (one full scan each caller used to run independently)."""
    query = select(FinanceTransaction).where(
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.merchant_id.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceTransaction.owner_user_id == owner_user_id)
    return list((await db.exec(query)).all())
