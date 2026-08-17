"""Investments: securities, prices, holdings, trades."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import (
    Provider,
)
from app.services.finance.domains.investments import queries
from app.services.finance.domains.ledger import accounts
from app.services.finance.models import (
    FinanceHolding,
    FinanceSecurity,
    FinanceSecurityPrice,
    FinanceTrade,
)
from app.services.finance.utils import (
    DEFAULT_CURRENCY,
    utcnow,
)

# Holdings store quantity as units x 1e8 (``quantity_e8``); prices are scaled
# integers (``price / 10**price_scale`` = unit price).
_QUANTITY_SCALE = 10**8


def market_value_cents(quantity_e8: int, price: int | None, price_scale: int) -> int:
    """Position value in integer cents: shares x unit-price, rounded.

    ``shares = quantity_e8 / 1e8``; ``unit_price = price / 10**price_scale``;
    value in cents = shares * unit_price * 100.

    Stays in integer arithmetic (Python ints are arbitrary-precision) so large
    positions never lose precision to float rounding; the result is rounded to
    the nearest cent, half away from zero.
    """
    if not price:
        return 0
    denom = _QUANTITY_SCALE * (10**price_scale)
    numerator = quantity_e8 * price * 100
    if numerator < 0:
        return -((-numerator + denom // 2) // denom)
    return (numerator + denom // 2) // denom


async def get_or_create_security(
    db: AsyncSession,
    *,
    ticker: str,
    name: str | None = None,
    security_type: str | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> FinanceSecurity:
    """Fetch a security by ticker (case-insensitive), else create it.

    Securities are global/un-owned — the catalog is shared across accounts.
    """
    normalized = ticker.strip().upper()
    existing = await queries.security_by_ticker(db, normalized)
    if existing is not None:
        return existing
    await accounts.get_or_create_currency(db, currency)  # security.currency FK
    security = FinanceSecurity(
        ticker=normalized,
        name=name or normalized,
        security_type=security_type,
        currency=currency,
        provider="manual",
    )
    db.add(security)
    await db.flush()
    return security


async def upsert_provider_security(
    db: AsyncSession,
    *,
    provider: str,
    provider_security_id: str,
    ticker: str | None = None,
    name: str | None = None,
    security_type: str | None = None,
    cusip: str | None = None,
    isin: str | None = None,
    figi: str | None = None,
    currency: str = DEFAULT_CURRENCY,
    close_price: int | None = None,
    price_scale: int = 2,
) -> FinanceSecurity:
    """Resolve a provider-reported security to ONE catalog row and update it.

    Resolution order: ``(provider, provider_security_id)`` — the
    same-provider fast path — then FIGI, then CUSIP, then ISIN. The
    standard identifiers are the cross-provider merge keys (each is
    partial-unique on the table), so the same instrument reported by two
    aggregators lands on one row instead of two.

    A row matched through an identifier keeps its original
    ``provider``/``provider_security_id`` (first cataloger wins) and its
    descriptive fields are only filled where missing; the matching
    provider still finds the row again next sync via the identifier.
    Identifier columns themselves are fill-if-missing, never overwritten:
    a provider that stops sending (or disagrees about) a FIGI can neither
    null out the key nor collide with another row's.
    """
    await accounts.get_or_create_currency(db, currency)
    security = await queries.security_by_provider_ref(
        db, provider=provider, provider_security_id=provider_security_id
    )
    owns_row = security is not None
    if security is None:
        for column, value in (
            (FinanceSecurity.figi, figi),
            (FinanceSecurity.cusip, cusip),
            (FinanceSecurity.isin, isin),
        ):
            if not value:
                continue
            security = await queries.security_by_identifier(db, column, value)
            if security is not None:
                break
    if security is None:
        security = FinanceSecurity(
            provider=provider, provider_security_id=provider_security_id
        )
        owns_row = True
    if owns_row:
        # Update only what the payload actually carries: partial payloads
        # (e.g. an activities row with no pricing) must not erase catalog
        # data a fuller sync already stored.
        if ticker is not None:
            security.ticker = ticker
        if name is not None:
            security.name = name
        if security_type is not None:
            security.security_type = security_type
        security.currency = currency
        if close_price is not None:
            security.close_price = close_price
            security.price_scale = price_scale
    else:
        security.ticker = security.ticker or ticker
        security.name = security.name or name
        security.security_type = security.security_type or security_type
        if close_price is not None:
            security.close_price = close_price
            security.price_scale = price_scale
    security.cusip = security.cusip or cusip
    security.isin = security.isin or isin
    security.figi = security.figi or figi
    db.add(security)
    await db.flush()
    return security


async def upsert_security_price(
    db: AsyncSession,
    *,
    security_id: int,
    price_date: date,
    close_price: int,
    price_scale: int = 2,
    currency: str = DEFAULT_CURRENCY,
    source: str = "manual",
) -> FinanceSecurityPrice:
    """Insert/update the (security, date, source) price point."""
    existing = await queries.security_price_by_key(
        db, security_id=security_id, price_date=price_date, source=source
    )
    if existing is not None:
        existing.close_price = close_price
        existing.price_scale = price_scale
        existing.currency = currency
        db.add(existing)
        await db.flush()
        return existing
    await accounts.get_or_create_currency(db, currency)  # price.currency FK
    price = FinanceSecurityPrice(
        security_id=security_id,
        price_date=price_date,
        close_price=close_price,
        price_scale=price_scale,
        currency=currency,
        source=source,
    )
    db.add(price)
    await db.flush()
    return price


async def upsert_holding(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    account_id: int,
    security_id: int,
    as_of_date: date,
    quantity_e8: int,
    price: int | None = None,
    price_scale: int = 2,
    cost_basis: int | None = None,
    average_cost: int | None = None,
    currency: str = DEFAULT_CURRENCY,
    source: str = "manual",
    sync_account_balance: bool = True,
) -> FinanceHolding:
    """Insert/update the (account, security, as_of_date) position snapshot.

    ``owner_user_id`` is NOT NULL on holdings, so standalone (no-auth) rows
    use the ``0`` sentinel — the same convention as import batches.

    ``sync_account_balance`` sets the account's ``current_balance`` to its
    holdings value (right for manual entry). Pass ``False`` when a provider
    already supplies an authoritative account balance (e.g. Plaid).
    """
    holding_owner = 0 if owner_user_id is None else owner_user_id
    existing = await queries.holding_by_key(
        db, account_id=account_id, security_id=security_id, as_of_date=as_of_date
    )
    if existing is not None:
        existing.quantity_e8 = quantity_e8
        existing.price = price
        existing.price_scale = price_scale
        existing.cost_basis = cost_basis
        existing.average_cost = average_cost
        existing.currency = currency
        existing.source = source
        existing.deleted_at = None
        db.add(existing)
        result = existing
    else:
        await accounts.get_or_create_currency(db, currency)  # holding.currency FK
        result = FinanceHolding(
            owner_user_id=holding_owner,
            account_id=account_id,
            security_id=security_id,
            as_of_date=as_of_date,
            quantity_e8=quantity_e8,
            price=price,
            price_scale=price_scale,
            cost_basis=cost_basis,
            average_cost=average_cost,
            currency=currency,
            source=source,
        )
        db.add(result)
    await db.flush()
    # Reflect the position in net worth: an investment account's balance is
    # its holdings' market value (unless the provider supplies its own).
    if sync_account_balance:
        await sync_account_balance_from_holdings(
            db, account_id, owner_user_id=owner_user_id
        )
    return result


async def upsert_trade(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    account_id: int,
    trade_type: str,
    trade_date: date,
    amount: int,
    security_id: int | None = None,
    subtype: str | None = None,
    quantity_e8: int | None = None,
    price: int | None = None,
    price_scale: int = 2,
    fees: int | None = None,
    currency: str = DEFAULT_CURRENCY,
    source: str = Provider.MANUAL,
    external_id: str | None = None,
    external_id_source: str | None = None,
    name: str | None = None,
    connection_id: int | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> FinanceTrade:
    """Insert/update one investment trade (buy/sell/dividend/...).

    Provider rows dedup on the external-id lane ``(account, source,
    external_id)``; manual/imported rows without an ``external_id`` always
    insert (the import-hash lane is the importers' job, not this path).
    ``owner_user_id`` is NOT NULL, so standalone (no-auth) rows use the
    ``0`` sentinel — same convention as holdings and import batches.
    """
    trade_owner = 0 if owner_user_id is None else owner_user_id
    existing: FinanceTrade | None = None
    if external_id is not None:
        existing = await queries.trade_by_external_id(
            db, account_id=account_id, source=source, external_id=external_id
        )
    await accounts.get_or_create_currency(db, currency)  # trade.currency FK
    if existing is not None:
        existing.security_id = security_id
        existing.type = trade_type
        existing.subtype = subtype
        existing.quantity_e8 = quantity_e8
        existing.price = price
        existing.price_scale = price_scale
        existing.amount = amount
        existing.fees = fees
        existing.currency = currency
        existing.trade_date = trade_date
        existing.name = name
        existing.connection_id = connection_id
        existing.raw_payload = raw_payload
        existing.deleted_at = None
        db.add(existing)
        await db.flush()
        return existing
    trade = FinanceTrade(
        owner_user_id=trade_owner,
        account_id=account_id,
        security_id=security_id,
        connection_id=connection_id,
        source=source,
        external_id=external_id,
        external_id_source=external_id_source,
        type=trade_type,
        subtype=subtype,
        quantity_e8=quantity_e8,
        price=price,
        price_scale=price_scale,
        amount=amount,
        fees=fees,
        currency=currency,
        trade_date=trade_date,
        name=name,
        raw_payload=raw_payload,
    )
    db.add(trade)
    await db.flush()
    return trade


async def list_trades(
    db: AsyncSession,
    *,
    owner_user_id: int | None,
    account_id: int | None = None,
    account_ids: list[int] | None = None,
    limit: int = 100,
) -> list[FinanceTrade]:
    """Recent trades for an owner (optionally one account), newest first.

    ``account_ids`` is the register's account-picker scope - without
    it the All Accounts view showed every brokerage's trades no matter
    what the picker said.
    """
    trade_owner = 0 if owner_user_id is None else owner_user_id
    return await queries.trades_feed(
        db,
        trade_owner=trade_owner,
        account_id=account_id,
        account_ids=account_ids,
        limit=limit,
    )


async def sync_account_balance_from_holdings(
    db: AsyncSession, account_id: int, *, owner_user_id: int | None = None
) -> None:
    """Set an account's ``current_balance`` to its current holdings value.

    Keeps net worth (which sums ``current_balance``) in step with positions.
    """
    account = await accounts.get_account(db, account_id, owner_user_id=owner_user_id)
    if account is None:
        return
    account.current_balance = await get_portfolio_value(
        db, owner_user_id=owner_user_id, account_id=account_id
    )
    account.balance_as_of = utcnow()
    account.updated_at = utcnow()
    db.add(account)
    await db.flush()


async def list_current_holdings(
    db: AsyncSession, *, owner_user_id: int | None = None, account_id: int | None = None
) -> list[tuple[FinanceHolding, FinanceSecurity | None, int]]:
    """Current positions: the latest-dated holding per (account, security)
    with a non-zero quantity, each paired with its security and market
    value in cents (holding price, falling back to the security close).
    """
    # Exclude holdings whose account is soft-deleted (e.g. after
    # disconnecting a provider connection) so they don't leak into portfolio
    # totals — the account, not just the holding row, must be live.
    rows = await queries.live_holdings_joined(
        db, owner_user_id=owner_user_id, account_id=account_id
    )
    # Ascending date order -> the last write per (account, security) is the
    # current snapshot.
    latest: dict[tuple[int, int], FinanceHolding] = {}
    for holding in rows:
        latest[(holding.account_id, holding.security_id)] = holding
    current = [h for h in latest.values() if h.quantity_e8 != 0]
    if not current:
        return []
    security_ids = {h.security_id for h in current}
    securities = await queries.securities_by_ids(db, security_ids)
    result: list[tuple[FinanceHolding, FinanceSecurity | None, int]] = []
    for holding in current:
        security = securities.get(holding.security_id)
        price = holding.price
        if price is None and security is not None:
            price = security.close_price
        value = market_value_cents(holding.quantity_e8, price, holding.price_scale)
        result.append((holding, security, value))
    result.sort(key=lambda item: item[2], reverse=True)
    return result


async def get_portfolio_value(
    db: AsyncSession, *, owner_user_id: int | None = None, account_id: int | None = None
) -> int:
    """Total market value (cents) of the current holdings."""
    holdings = await list_current_holdings(
        db, owner_user_id=owner_user_id, account_id=account_id
    )
    return sum(value for _holding, _security, value in holdings)
