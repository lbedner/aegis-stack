"""Securities, trades and holdings.

Plaid's investment endpoint has no cursor, so each sync re-windows
``_INVESTMENT_LOOKBACK_DAYS`` and dedups by
``investment_transaction_id`` - trailing coverage, not an incremental
checkpoint.
"""

from __future__ import annotations

from datetime import date
import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.finance.constants import Provider
from app.services.finance.models import (
    FinanceConnection,
)
from app.services.finance.service import FinanceService

logger = logging.getLogger(__name__)


async def _upsert_securities(
    service: FinanceService,
    plaid_securities: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert catalog securities keyed by Plaid ``security_id`` (some have no
    ticker, so the provider id is the stable key); FIGI/CUSIP/ISIN merge the
    same instrument across providers. Returns {plaid_id: our_id}."""
    mapping: dict[str, int] = {}
    for sec in plaid_securities:
        plaid_id = sec["security_id"]
        close = sec.get("close_price")
        security = await service.upsert_provider_security(
            provider=Provider.PLAID,
            provider_security_id=plaid_id,
            ticker=sec.get("ticker_symbol"),
            name=sec.get("name"),
            security_type=sec.get("type"),
            cusip=sec.get("cusip"),
            isin=sec.get("isin"),
            figi=sec.get("figi"),
            currency=(sec.get("iso_currency_code") or "usd").lower(),
            close_price=round(close * 100) if close is not None else None,
        )
        mapping[plaid_id] = security.id
    return mapping


# How far back to pull investment transactions each sync. Plaid's endpoint has
# no cursor; we re-window and dedup by ``investment_transaction_id``, so this is
# just the trailing coverage, not an incremental checkpoint.
_INVESTMENT_LOOKBACK_DAYS = 730


def _map_plaid_trade_type(plaid_type: str, subtype: str | None, amount: float) -> str:
    """Map a Plaid (type, subtype, amount) to a normalized ``FinanceTrade.type``.

    Plaid's coarse ``type`` (buy/sell/cancel/cash/fee/transfer) is often too
    blunt, so the granular ``subtype`` wins when it's meaningful. Plaid signs
    ``amount`` positive when cash is debited (money out: a buy) and negative
    when credited (money in: a sell), which disambiguates the direction of the
    ``transfer``/``cash`` types. Unknown shapes fall back to ``other`` rather
    than raising — an unrecognized trade must never break a sync.
    """
    sub = (subtype or "").lower()
    if "reinvest" in sub:
        return "reinvest"
    if "dividend" in sub:
        return "dividend"
    if "interest" in sub:
        return "interest"
    if "tax" in sub:
        return "tax"
    if "split" in sub:
        return "split"
    if sub in ("deposit", "contribution"):
        return "deposit"
    if sub == "withdrawal":
        return "withdrawal"
    if sub in ("buy", "buy to cover"):
        return "buy"
    if sub in ("sell", "sell short"):
        return "sell"
    if "fee" in sub:
        return "fee"
    coarse = (plaid_type or "").lower()
    if coarse in ("buy", "sell", "cancel", "fee"):
        return coarse
    if coarse == "transfer":
        return "transfer_out" if amount > 0 else "transfer_in"
    if coarse == "cash":
        return "withdrawal" if amount > 0 else "deposit"
    return "other"


async def _apply_trades(
    db: AsyncSession,
    service: FinanceService,
    plaid_txns: list[dict[str, Any]],
    account_by_plaid_id: dict[str, int],
    security_by_plaid_id: dict[str, int],
    *,
    connection: FinanceConnection,
) -> int:
    """Upsert each Plaid investment transaction as a FinanceTrade, deduped by
    ``investment_transaction_id`` (the external-id lane). Cash-only rows (fees,
    dividends, deposits) carry no security and are still recorded."""
    count = 0
    for txn in plaid_txns:
        plaid_account_id = txn.get("account_id")
        account_id = (
            account_by_plaid_id.get(plaid_account_id) if plaid_account_id else None
        )
        if account_id is None:
            continue
        plaid_security_id = txn.get("security_id")
        security_id = (
            security_by_plaid_id.get(plaid_security_id) if plaid_security_id else None
        )
        plaid_amount = txn.get("amount") or 0.0
        quantity = txn.get("quantity")
        price = txn.get("price")
        fees = txn.get("fees")
        # Plaid signs ``amount`` positive when cash is debited (a buy). Store it
        # in the app convention used by cash transactions — negative = money out
        # of the account — so amounts colorize consistently in the UI. The raw
        # provider value is preserved in ``raw_payload``.
        await service.upsert_trade(
            owner_user_id=connection.owner_user_id,
            account_id=account_id,
            security_id=security_id,
            connection_id=connection.id,
            source=Provider.PLAID,
            external_id=txn.get("investment_transaction_id"),
            external_id_source=Provider.PLAID,
            trade_type=_map_plaid_trade_type(
                txn.get("type", ""), txn.get("subtype"), plaid_amount
            ),
            subtype=txn.get("subtype"),
            trade_date=date.fromisoformat(txn["date"]),
            amount=round(-plaid_amount * 100),
            quantity_e8=round(quantity * 10**8) if quantity is not None else None,
            price=round(price * 100) if price is not None else None,
            fees=round(fees * 100) if fees is not None else None,
            currency=(txn.get("iso_currency_code") or "usd").lower(),
            name=txn.get("name"),
            raw_payload=txn,
        )
        count += 1
    return count


async def _apply_holdings(
    db: AsyncSession,
    service: FinanceService,
    plaid_holdings: list[dict[str, Any]],
    account_by_plaid_id: dict[str, int],
    security_by_plaid_id: dict[str, int],
    *,
    owner_user_id: int | None,
) -> int:
    """Upsert each Plaid position as a FinanceHolding. Balances come from
    ``accounts/get``, so holdings don't drive the account balance here."""
    count = 0
    for holding in plaid_holdings:
        plaid_account_id = holding.get("account_id")
        plaid_security_id = holding.get("security_id")
        if not plaid_account_id or not plaid_security_id:
            continue
        account_id = account_by_plaid_id.get(plaid_account_id)
        security_id = security_by_plaid_id.get(plaid_security_id)
        if account_id is None or security_id is None:
            continue
        price = holding.get("institution_price")
        cost = holding.get("cost_basis")
        as_of = holding.get("institution_price_as_of")
        await service.upsert_holding(
            owner_user_id=owner_user_id,
            account_id=account_id,
            security_id=security_id,
            as_of_date=date.fromisoformat(as_of) if as_of else utcnow().date(),
            quantity_e8=round((holding.get("quantity") or 0) * 10**8),
            price=round(price * 100) if price is not None else None,
            cost_basis=round(cost * 100) if cost is not None else None,
            currency=(holding.get("iso_currency_code") or "usd").lower(),
            source=Provider.PLAID,
            sync_account_balance=False,
        )
        count += 1
    return count
