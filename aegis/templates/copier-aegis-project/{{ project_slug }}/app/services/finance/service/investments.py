"""Securities, holdings, trades and prices.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.finance.constants import Provider
from app.services.finance.domains.investments import securities
from app.services.finance.models import (
    FinanceHolding,
    FinanceSecurity,
    FinanceSecurityPrice,
    FinanceTrade,
)
from app.services.finance.service.base import FinanceServiceBase
from app.services.finance.utils import DEFAULT_CURRENCY


class InvestmentsMixin(FinanceServiceBase):
    """Securities, holdings, trades and prices."""

    async def get_or_create_security(
        self,
        *,
        ticker: str,
        name: str | None = None,
        security_type: str | None = None,
        currency: str = DEFAULT_CURRENCY,
    ) -> FinanceSecurity:
        return await securities.get_or_create_security(
            self.db,
            ticker=ticker,
            name=name,
            security_type=security_type,
            currency=currency,
        )

    async def upsert_provider_security(
        self,
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
        return await securities.upsert_provider_security(
            self.db,
            provider=provider,
            provider_security_id=provider_security_id,
            ticker=ticker,
            name=name,
            security_type=security_type,
            cusip=cusip,
            isin=isin,
            figi=figi,
            currency=currency,
            close_price=close_price,
            price_scale=price_scale,
        )

    async def upsert_security_price(
        self,
        *,
        security_id: int,
        price_date: date,
        close_price: int,
        price_scale: int = 2,
        currency: str = DEFAULT_CURRENCY,
        source: str = "manual",
    ) -> FinanceSecurityPrice:
        return await securities.upsert_security_price(
            self.db,
            security_id=security_id,
            price_date=price_date,
            close_price=close_price,
            price_scale=price_scale,
            currency=currency,
            source=source,
        )

    async def upsert_holding(
        self,
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
        return await securities.upsert_holding(
            self.db,
            owner_user_id=owner_user_id,
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
            sync_account_balance=sync_account_balance,
        )

    async def upsert_trade(
        self,
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
        return await securities.upsert_trade(
            self.db,
            owner_user_id=owner_user_id,
            account_id=account_id,
            trade_type=trade_type,
            trade_date=trade_date,
            amount=amount,
            security_id=security_id,
            subtype=subtype,
            quantity_e8=quantity_e8,
            price=price,
            price_scale=price_scale,
            fees=fees,
            currency=currency,
            source=source,
            external_id=external_id,
            external_id_source=external_id_source,
            name=name,
            connection_id=connection_id,
            raw_payload=raw_payload,
        )

    async def list_trades(
        self,
        *,
        owner_user_id: int | None,
        account_id: int | None = None,
        account_ids: list[int] | None = None,
        limit: int = 100,
    ) -> list[FinanceTrade]:
        return await securities.list_trades(
            self.db,
            owner_user_id=owner_user_id,
            account_id=account_id,
            account_ids=account_ids,
            limit=limit,
        )

    async def sync_account_balance_from_holdings(
        self, account_id: int, *, owner_user_id: int | None = None
    ) -> None:
        return await securities.sync_account_balance_from_holdings(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
        )

    async def list_current_holdings(
        self, *, owner_user_id: int | None = None, account_id: int | None = None
    ) -> list[tuple[FinanceHolding, FinanceSecurity | None, int]]:
        return await securities.list_current_holdings(
            self.db,
            owner_user_id=owner_user_id,
            account_id=account_id,
        )

    async def get_portfolio_value(
        self, *, owner_user_id: int | None = None, account_id: int | None = None
    ) -> int:
        return await securities.get_portfolio_value(
            self.db,
            owner_user_id=owner_user_id,
            account_id=account_id,
        )
