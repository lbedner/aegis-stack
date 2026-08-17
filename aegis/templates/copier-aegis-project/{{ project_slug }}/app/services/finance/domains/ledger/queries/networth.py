"""Reads behind the net-worth series and the Overview roll-ups.

Snapshots, valuations, register deltas, holdings and priced trades - the
inputs a balance curve is recomputed from, plus the account and
connection roll-ups the header cells read.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, case, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceAccount,
    FinanceBalanceSnapshot,
    FinanceConnection,
    FinanceHolding,
    FinanceNetWorthSnapshot,
    FinanceTrade,
    FinanceTransaction,
    FinanceValuation,
)


async def live_accounts_for_owner(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> list[FinanceAccount]:
    query = select(FinanceAccount).where(FinanceAccount.deleted_at.is_(None))
    if owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    return list((await db.exec(query.order_by(FinanceAccount.id))).all())


async def valuations_for_accounts(
    db: AsyncSession, account_ids: list[int]
) -> list[FinanceValuation]:
    if not account_ids:
        return []
    return list(
        (
            await db.exec(
                select(FinanceValuation)
                .where(FinanceValuation.account_id.in_(account_ids))
                .order_by(FinanceValuation.account_id, FinanceValuation.as_of_date)
            )
        ).all()
    )


async def daily_register_deltas(
    db: AsyncSession, account_ids: list[int]
) -> list[tuple[int, date, int]]:
    """(account_id, date, summed amount) per account-day, ascending - the
    register fallback for balance reconstruction, one grouped query."""
    if not account_ids:
        return []
    rows = (
        await db.exec(
            select(
                FinanceTransaction.account_id,
                FinanceTransaction.date_,
                func.sum(FinanceTransaction.amount),
            )
            .where(
                FinanceTransaction.account_id.in_(account_ids),
                FinanceTransaction.deleted_at.is_(None),
                FinanceTransaction.dedup_status != "duplicate",
            )
            .group_by(FinanceTransaction.account_id, FinanceTransaction.date_)
            .order_by(FinanceTransaction.account_id, FinanceTransaction.date_)
        )
    ).all()
    return [(account_id, d, int(delta or 0)) for account_id, d, delta in rows]


async def holding_quantities(
    db: AsyncSession, account_ids: list[int]
) -> list[tuple[int, int, int]]:
    """(security_id, account_id, quantity_e8) for the accounts."""
    if not account_ids:
        return []
    rows = (
        await db.exec(
            select(
                FinanceHolding.security_id,
                FinanceHolding.account_id,
                FinanceHolding.quantity_e8,
            ).where(FinanceHolding.account_id.in_(account_ids))
        )
    ).all()
    return list(rows)


async def priced_trade_rows(
    db: AsyncSession, account_ids: list[int]
) -> list[tuple[int, date, int, int, int, int]]:
    """(account_id, trade_date, security_id, quantity_e8, price, price_scale)
    for security-linked trades, date-ascending per account."""
    if not account_ids:
        return []
    rows = (
        await db.exec(
            select(
                FinanceTrade.account_id,
                FinanceTrade.trade_date,
                FinanceTrade.security_id,
                FinanceTrade.quantity_e8,
                FinanceTrade.price,
                FinanceTrade.price_scale,
            )
            .where(
                FinanceTrade.account_id.in_(account_ids),
                FinanceTrade.security_id.is_not(None),
            )
            .order_by(FinanceTrade.account_id, FinanceTrade.trade_date)
        )
    ).all()
    return list(rows)


async def balance_snapshots_between(
    db: AsyncSession, account_ids: list[int], *, start: date, end: date
) -> list[FinanceBalanceSnapshot]:
    if not account_ids:
        return []
    return list(
        (
            await db.exec(
                select(FinanceBalanceSnapshot).where(
                    FinanceBalanceSnapshot.account_id.in_(account_ids),
                    FinanceBalanceSnapshot.balance_date >= start,
                    FinanceBalanceSnapshot.balance_date <= end,
                )
            )
        ).all()
    )


def _owner_scoped_net_worth(query, owner_user_id: int | None):
    # owner_user_id is nullable; ``== None`` never matches in SQL, so branch
    # to keep standalone (no-auth) mode working.
    if owner_user_id is None:
        return query.where(FinanceNetWorthSnapshot.owner_user_id.is_(None))
    return query.where(FinanceNetWorthSnapshot.owner_user_id == owner_user_id)


async def net_worth_snapshots_between(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    start: date,
    end: date,
    currency: str,
) -> list[FinanceNetWorthSnapshot]:
    query = select(FinanceNetWorthSnapshot).where(
        FinanceNetWorthSnapshot.currency == currency,
        FinanceNetWorthSnapshot.as_of_date >= start,
        FinanceNetWorthSnapshot.as_of_date <= end,
    )
    return list((await db.exec(_owner_scoped_net_worth(query, owner_user_id))).all())


async def net_worth_series_since(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    since: date,
    currency: str,
) -> list[FinanceNetWorthSnapshot]:
    query = select(FinanceNetWorthSnapshot).where(
        FinanceNetWorthSnapshot.as_of_date >= since,
        FinanceNetWorthSnapshot.currency == currency,
    )
    query = _owner_scoped_net_worth(query, owner_user_id)
    query = query.order_by(FinanceNetWorthSnapshot.as_of_date)
    return list((await db.exec(query)).all())


async def balance_class_series(
    db: AsyncSession,
    *,
    account_ids: list[int],
    since: date,
    owner_user_id: int | None,
) -> list[tuple[date, str, int]]:
    """(balance_date, classification, summed balance) for the accounts -
    the live-summed series behind a filtered Overview chart. The join to
    ``finance_account`` keeps the owner scope authoritative."""
    rows = (
        await db.exec(
            select(
                FinanceBalanceSnapshot.balance_date,
                FinanceAccount.classification,
                func.sum(FinanceBalanceSnapshot.balance),
            )
            .join(
                FinanceAccount,
                FinanceAccount.id == FinanceBalanceSnapshot.account_id,
            )
            .where(
                FinanceBalanceSnapshot.account_id.in_(account_ids),
                FinanceBalanceSnapshot.balance_date >= since,
                FinanceAccount.deleted_at.is_(None),
                FinanceAccount.owner_user_id.is_(None)
                if owner_user_id is None
                else FinanceAccount.owner_user_id == owner_user_id,
            )
            .group_by(
                FinanceBalanceSnapshot.balance_date,
                FinanceAccount.classification,
            )
            .order_by(FinanceBalanceSnapshot.balance_date)
        )
    ).all()
    return list(rows)


async def account_rollup(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> tuple[int, int, int]:
    """(assets, liabilities, account_count) in a single aggregate query.

    Assets/liabilities sum only *visible* accounts; the count includes
    hidden ones - conditional sums over one scan rather than three
    separate queries."""
    query = (
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                FinanceAccount.classification == "asset",
                                ~FinanceAccount.is_hidden,
                            ),
                            FinanceAccount.current_balance,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                FinanceAccount.classification == "liability",
                                ~FinanceAccount.is_hidden,
                            ),
                            FinanceAccount.current_balance,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.count(),
        )
        .select_from(FinanceAccount)
        .where(FinanceAccount.deleted_at.is_(None))
    )
    if owner_user_id is not None:
        query = query.where(FinanceAccount.owner_user_id == owner_user_id)
    assets, liabilities, count = (await db.exec(query)).one()
    return int(assets or 0), int(liabilities or 0), int(count or 0)


async def connection_rollup(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> tuple[int, int]:
    """(connection_count, needs_action_count) in a single aggregate query."""
    query = (
        select(
            func.count(),
            func.coalesce(
                func.sum(case((FinanceConnection.needs_user_action, 1), else_=0)),
                0,
            ),
        )
        .select_from(FinanceConnection)
        .where(FinanceConnection.deleted_at.is_(None))
    )
    if owner_user_id is not None:
        query = query.where(FinanceConnection.owner_user_id == owner_user_id)
    connections, needs_action = (await db.exec(query)).one()
    return int(connections or 0), int(needs_action or 0)
