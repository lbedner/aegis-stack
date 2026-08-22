"""Batched read queries for the investments domain.

Set-shaped inputs, map-shaped outputs, so callers cannot reintroduce a
per-row query loop. Statement builders only - no business logic, no
writes.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceAccount,
    FinanceHolding,
    FinanceSecurity,
    FinanceSecurityPrice,
    FinanceTrade,
)


async def security_by_ticker(db: AsyncSession, ticker: str) -> FinanceSecurity | None:
    """Exact-ticker match (callers normalize case first)."""
    return (
        await db.exec(select(FinanceSecurity).where(FinanceSecurity.ticker == ticker))
    ).first()


async def security_by_provider_ref(
    db: AsyncSession, *, provider: str, provider_security_id: str
) -> FinanceSecurity | None:
    return (
        await db.exec(
            select(FinanceSecurity).where(
                FinanceSecurity.provider == provider,
                FinanceSecurity.provider_security_id == provider_security_id,
            )
        )
    ).first()


async def security_by_identifier(
    db: AsyncSession, column, value: str
) -> FinanceSecurity | None:
    """Match on one identifier column (FIGI / CUSIP / ISIN)."""
    return (await db.exec(select(FinanceSecurity).where(column == value))).first()


async def security_ticker_by_name(db: AsyncSession, name: str) -> str | None:
    """The OLDEST security row's ticker for a fund name - deterministic
    (an unordered first() over duplicates picks planner's choice)."""
    return (
        await db.exec(
            select(FinanceSecurity.ticker)
            .where(FinanceSecurity.name == name)
            .order_by(FinanceSecurity.id)
        )
    ).first()


async def securities_by_ids(
    db: AsyncSession, ids: set[int] | list[int]
) -> dict[int, FinanceSecurity]:
    wanted = list(set(ids))
    if not wanted:
        return {}
    rows = (
        await db.exec(select(FinanceSecurity).where(FinanceSecurity.id.in_(wanted)))
    ).all()
    return {row.id: row for row in rows}


async def security_price_by_key(
    db: AsyncSession, *, security_id: int, price_date: date, source: str
) -> FinanceSecurityPrice | None:
    return (
        await db.exec(
            select(FinanceSecurityPrice).where(
                FinanceSecurityPrice.security_id == security_id,
                FinanceSecurityPrice.price_date == price_date,
                FinanceSecurityPrice.source == source,
            )
        )
    ).first()


async def latest_price_for_security(
    db: AsyncSession, security_id: int
) -> FinanceSecurityPrice | None:
    """The most recent stored price row for a security, any source."""
    return (
        await db.exec(
            select(FinanceSecurityPrice)
            .where(FinanceSecurityPrice.security_id == security_id)
            .order_by(FinanceSecurityPrice.price_date.desc())  # type: ignore[union-attr]
            .limit(1)
        )
    ).first()


async def holding_by_key(
    db: AsyncSession, *, account_id: int, security_id: int, as_of_date: date
) -> FinanceHolding | None:
    return (
        await db.exec(
            select(FinanceHolding).where(
                FinanceHolding.account_id == account_id,
                FinanceHolding.security_id == security_id,
                FinanceHolding.as_of_date == as_of_date,
            )
        )
    ).first()


async def trade_by_external_id(
    db: AsyncSession, *, account_id: int, source: str, external_id: str
) -> FinanceTrade | None:
    return (
        await db.exec(
            select(FinanceTrade).where(
                FinanceTrade.account_id == account_id,
                FinanceTrade.source == source,
                FinanceTrade.external_id == external_id,
                FinanceTrade.deleted_at.is_(None),
            )
        )
    ).first()


async def trades_feed(
    db: AsyncSession,
    *,
    trade_owner: int,
    account_id: int | None = None,
    account_ids: list[int] | None = None,
    limit: int = 100,
) -> list[FinanceTrade]:
    """Recent live trades on live accounts, newest first."""
    query = select(FinanceTrade).where(
        FinanceTrade.owner_user_id == trade_owner,
        FinanceTrade.deleted_at.is_(None),
        FinanceTrade.account_id.in_(
            select(FinanceAccount.id).where(FinanceAccount.deleted_at.is_(None))
        ),
    )
    if account_id is not None:
        query = query.where(FinanceTrade.account_id == account_id)
    if account_ids is not None:
        query = query.where(FinanceTrade.account_id.in_(account_ids))
    query = query.order_by(
        FinanceTrade.trade_date.desc(), FinanceTrade.id.desc()
    ).limit(limit)
    return list((await db.exec(query)).all())


async def live_holdings_joined(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    account_id: int | None = None,
) -> list[FinanceHolding]:
    """Live holdings on live accounts, date-ascending (so the last write
    per (account, security) is the current snapshot)."""
    filters = [
        FinanceHolding.deleted_at.is_(None),
        FinanceAccount.deleted_at.is_(None),
    ]
    if owner_user_id is not None:
        filters.append(FinanceHolding.owner_user_id == owner_user_id)
    if account_id is not None:
        filters.append(FinanceHolding.account_id == account_id)
    return list(
        (
            await db.exec(
                select(FinanceHolding)
                .join(
                    FinanceAccount,
                    FinanceAccount.id == FinanceHolding.account_id,
                )
                .where(*filters)
                .order_by(FinanceHolding.as_of_date)
            )
        ).all()
    )
