"""Reads for accounts, and the things hung off one.

Currencies and institutions (an account's references), balances and
valuations (what it is worth), and the reconciliation rows that explain
a manual correction.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    RECONCILE_MARKER,
)
from app.services.finance.models import (
    FinanceAccount,
    FinanceCurrency,
    FinanceInstitution,
    FinanceLiabilityDetail,
    FinanceTransaction,
    FinanceValuation,
)


async def currency_by_code(db: AsyncSession, code: str) -> FinanceCurrency | None:
    return (
        await db.exec(select(FinanceCurrency).where(FinanceCurrency.code == code))
    ).first()


async def institution_by_provider_ref(
    db: AsyncSession, *, provider: str, provider_institution_id: str
) -> FinanceInstitution | None:
    return (
        await db.exec(
            select(FinanceInstitution).where(
                FinanceInstitution.provider == provider,
                FinanceInstitution.provider_institution_id == provider_institution_id,
            )
        )
    ).first()


async def account_by_id(
    db: AsyncSession, account_id: int, *, owner_user_id: int | None = None
) -> FinanceAccount | None:
    query = select(FinanceAccount).where(
        FinanceAccount.id == account_id,
        FinanceAccount.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def accounts_page(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    include_hidden: bool,
    page: int,
    page_size: int,
    subject_id: int | None = None,
) -> tuple[list[FinanceAccount], int]:
    """One page of live accounts plus the total count (two statements).

    ``subject_id`` narrows to whose money the rows describe: an id for one
    subject's accounts, ``0`` for the household's own (the rows nobody
    assigned), and None for everything, which is what every caller that
    predates subjects means.
    """
    query = select(FinanceAccount).where(FinanceAccount.deleted_at.is_(None))
    count_query = (
        select(func.count())
        .select_from(FinanceAccount)
        .where(FinanceAccount.deleted_at.is_(None))
    )
    if owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
        count_query = count_query.where(FinanceAccount.owner_user_id == owner_user_id)
    if not include_hidden:
        query = query.where(~FinanceAccount.is_hidden)
        count_query = count_query.where(~FinanceAccount.is_hidden)
    if subject_id is not None:
        clause = (
            FinanceAccount.subject_id.is_(None)
            if subject_id == 0
            else FinanceAccount.subject_id == subject_id
        )
        query = query.where(clause)
        count_query = count_query.where(clause)
    total = (await db.exec(count_query)).one()
    query = (
        query.order_by(FinanceAccount.classification, FinanceAccount.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.exec(query)).all()), total


async def liability_details_by_account(
    db: AsyncSession, account_ids: list[int]
) -> dict[int, FinanceLiabilityDetail]:
    if not account_ids:
        return {}
    rows = (
        await db.exec(
            select(FinanceLiabilityDetail).where(
                FinanceLiabilityDetail.account_id.in_(account_ids)
            )
        )
    ).all()
    return {row.account_id: row for row in rows}


async def transaction_totals_by_account(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    account_ids: list[int] | None = None,
) -> dict[int, int]:
    """Signed register sum per account (non-duplicate, non-deleted), one
    grouped query."""
    if account_ids is not None and not account_ids:
        return {}
    filters = [
        FinanceTransaction.deleted_at.is_(None),
        FinanceTransaction.dedup_status != "duplicate",
    ]
    if owner_user_id is not None:
        filters.append(FinanceTransaction.owner_user_id == owner_user_id)
    if account_ids is not None:
        filters.append(FinanceTransaction.account_id.in_(account_ids))
    query = (
        select(
            FinanceTransaction.account_id,
            func.coalesce(func.sum(FinanceTransaction.amount), 0),
        )
        .where(*filters)
        .group_by(FinanceTransaction.account_id)
    )
    return {
        account_id: int(total or 0)
        for account_id, total in (await db.exec(query)).all()
    }


async def valuation_by_key(
    db: AsyncSession, *, account_id: int, as_of_date: date, source: str
) -> FinanceValuation | None:
    return (
        await db.exec(
            select(FinanceValuation).where(
                FinanceValuation.account_id == account_id,
                FinanceValuation.as_of_date == as_of_date,
                FinanceValuation.source == source,
            )
        )
    ).first()


async def latest_valuation_value(
    db: AsyncSession, account_id: int, *, source: str | None = None
) -> int | None:
    """The newest valuation for an account, optionally within one source.

    Several sources can hold an opinion about the same date (the row key
    includes ``source``), so "latest" alone is only unambiguous while
    there is one of them. ``source`` is how a caller says which opinion
    it wants; ``None`` keeps the old behaviour.
    """
    query = select(FinanceValuation.value).where(
        FinanceValuation.account_id == account_id
    )
    if source is not None:
        query = query.where(FinanceValuation.source == source)
    value = (
        await db.exec(query.order_by(FinanceValuation.as_of_date.desc()).limit(1))
    ).first()
    return int(value) if value is not None else None


async def latest_valuation_row(
    db: AsyncSession, account_id: int, *, source: str | None = None
) -> FinanceValuation | None:
    """The newest valuation row (optionally within one source).

    Callers that report provenance need the row, not the number: the
    source and date that produced a balance are what make it quotable.
    """
    query = select(FinanceValuation).where(FinanceValuation.account_id == account_id)
    if source is not None:
        query = query.where(FinanceValuation.source == source)
    return (
        await db.exec(query.order_by(FinanceValuation.as_of_date.desc()).limit(1))
    ).first()


async def valuations_for_account(
    db: AsyncSession, account_id: int
) -> list[FinanceValuation]:
    query = (
        select(FinanceValuation)
        .where(FinanceValuation.account_id == account_id)
        .order_by(FinanceValuation.as_of_date)
    )
    return list((await db.exec(query)).all())


async def register_balance_through(
    db: AsyncSession, account_id: int, as_of: date
) -> int:
    """Signed sum of the account's posted register through ``as_of``."""
    total = (
        await db.exec(
            select(func.coalesce(func.sum(FinanceTransaction.amount), 0)).where(
                FinanceTransaction.account_id == account_id,
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.status == "posted",
                FinanceTransaction.date_ <= as_of,
            )
        )
    ).one()
    return int(total or 0)


async def reconcile_adjustment_on(
    db: AsyncSession, account_id: int, statement_date: date
) -> FinanceTransaction | None:
    return (
        await db.exec(
            select(FinanceTransaction).where(
                FinanceTransaction.account_id == account_id,
                FinanceTransaction.external_id_source == RECONCILE_MARKER,
                FinanceTransaction.date_ == statement_date,
                FinanceTransaction.deleted_at.is_(None),
            )
        )
    ).first()


async def has_nonreconcile_register(db: AsyncSession, account_id: int) -> bool:
    """True when the account has any live register row that is not a
    reconciliation adjustment (NULL-safe on ``external_id_source``)."""
    row = (
        await db.exec(
            select(FinanceTransaction.id)
            .where(
                FinanceTransaction.account_id == account_id,
                FinanceTransaction.deleted_at.is_(None),
                func.coalesce(FinanceTransaction.external_id_source, "")
                != RECONCILE_MARKER,
            )
            .limit(1)
        )
    ).first()
    return row is not None
