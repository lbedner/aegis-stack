"""Security, holding, and trade shapes.

A topic module of the ``schemas`` package; every name here is
re-exported from the package root, which stays the one import path.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.services.finance.models import (
        FinanceHolding,
        FinanceSecurity,
        FinanceTrade,
    )


class SecurityResponse(BaseModel):
    """A catalog security (equity, ETF, fund, crypto, ...)."""

    id: int
    ticker: str | None
    name: str | None
    security_type: str | None
    currency: str | None

    @classmethod
    def from_row(cls, row: FinanceSecurity) -> SecurityResponse:
        return cls(
            id=row.id,
            ticker=row.ticker,
            name=row.name,
            security_type=row.security_type,
            currency=row.currency,
        )


class HoldingResponse(BaseModel):
    """A current position with its computed market value (cents)."""

    id: int
    account_id: int
    security_id: int
    ticker: str | None = None
    name: str | None = None
    security_type: str | None = None
    as_of_date: date
    quantity: float  # shares = quantity_e8 / 1e8
    price: int | None  # unit price in scaled minor units
    price_scale: int
    cost_basis: int | None
    market_value: int  # cents
    currency: str
    icon_b64: str | None = None  # set by the router; from_parts has no async access

    @classmethod
    def from_parts(
        cls,
        holding: FinanceHolding,
        security: FinanceSecurity | None,
        market_value: int,
    ) -> HoldingResponse:
        return cls(
            id=holding.id,
            account_id=holding.account_id,
            security_id=holding.security_id,
            ticker=security.ticker if security else None,
            name=security.name if security else None,
            security_type=security.security_type if security else None,
            as_of_date=holding.as_of_date,
            quantity=holding.quantity_e8 / 100_000_000,
            price=holding.price,
            price_scale=holding.price_scale,
            cost_basis=holding.cost_basis,
            market_value=market_value,
            currency=holding.currency,
        )


class HoldingListResponse(BaseModel):
    items: list[HoldingResponse]
    total: int
    portfolio_value: int  # cents


class TradeResponse(BaseModel):
    """One investment trade / security movement (buy/sell/dividend/...).

    ``amount`` is in cents, negative when cash left the account (a buy/fee)
    and positive when it arrived (a sell/dividend) — the same convention as
    cash transactions.
    """

    id: int
    account_id: int
    security_id: int | None = None
    type: str
    subtype: str | None = None
    trade_date: date
    quantity: float | None  # shares = quantity_e8 / 1e8
    price: int | None  # unit price in scaled minor units
    price_scale: int
    amount: int  # cents (signed: negative = cash out)
    fees: int | None
    name: str | None = None
    currency: str

    @classmethod
    def from_row(cls, trade: FinanceTrade) -> TradeResponse:
        return cls(
            id=trade.id,
            account_id=trade.account_id,
            security_id=trade.security_id,
            type=trade.type,
            subtype=trade.subtype,
            trade_date=trade.trade_date,
            quantity=(
                trade.quantity_e8 / 100_000_000
                if trade.quantity_e8 is not None
                else None
            ),
            price=trade.price,
            price_scale=trade.price_scale,
            amount=trade.amount,
            fees=trade.fees,
            name=trade.name,
            currency=trade.currency,
        )


class TradeListResponse(BaseModel):
    items: list[TradeResponse]
    total: int


class SecurityCreate(BaseModel):
    """POST body for /securities."""

    ticker: str
    name: str | None = None
    security_type: str | None = None
    currency: str = "usd"


class HoldingCreate(BaseModel):
    """POST body for /accounts/{id}/holdings (account from the path).

    ``ticker`` resolves or creates the security; ``quantity`` is in shares;
    ``price`` is the unit price in minor units (cents, price_scale 2).
    """

    ticker: str
    name: str | None = None
    security_type: str | None = None
    as_of_date: date | None = None
    quantity: float
    price: int | None = None
    cost_basis: int | None = None
