"""Accounts, currencies, institutions, valuations and reconciliation.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.finance.domains.ledger import accounts, properties, valuations
from app.services.finance.models import (
    FinanceAccount,
    FinanceCurrency,
    FinanceInstitution,
    FinanceLiabilityDetail,
    FinanceTransaction,
    FinanceValuation,
)
from app.services.finance.schemas import ReconcileResponse
from app.services.finance.service.base import FinanceServiceBase
from app.services.finance.utils import DEFAULT_CURRENCY


class AccountsMixin(FinanceServiceBase):
    """Accounts, currencies, institutions, valuations and reconciliation."""

    async def get_or_create_currency(
        self,
        code: str = DEFAULT_CURRENCY,
        *,
        name: str | None = None,
        symbol: str | None = None,
        decimals: int = 2,
    ) -> FinanceCurrency:
        return await accounts.get_or_create_currency(
            self.db,
            code,
            name=name,
            symbol=symbol,
            decimals=decimals,
        )

    async def get_or_create_institution(
        self,
        *,
        provider: str,
        name: str,
        provider_institution_id: str | None = None,
    ) -> FinanceInstitution:
        return await accounts.get_or_create_institution(
            self.db,
            provider=provider,
            name=name,
            provider_institution_id=provider_institution_id,
        )

    async def create_manual_account(
        self,
        *,
        name: str,
        account_type: str,
        classification: str,
        owner_user_id: int | None = None,
        organization_id: int | None = None,
        current_balance: int = 0,
        currency: str = DEFAULT_CURRENCY,
        institution_id: int | None = None,
    ) -> FinanceAccount:
        return await accounts.create_manual_account(
            self.db,
            name=name,
            account_type=account_type,
            classification=classification,
            owner_user_id=owner_user_id,
            organization_id=organization_id,
            current_balance=current_balance,
            currency=currency,
            institution_id=institution_id,
        )

    async def get_account(
        self, account_id: int, *, owner_user_id: int | None = None
    ) -> FinanceAccount | None:
        return await accounts.get_account(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
        )

    async def list_accounts(
        self,
        *,
        owner_user_id: int | None = None,
        include_hidden: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FinanceAccount], int]:
        return await accounts.list_accounts(
            self.db,
            owner_user_id=owner_user_id,
            include_hidden=include_hidden,
            page=page,
            page_size=page_size,
        )

    async def update_account_balance(
        self,
        account_id: int,
        *,
        current_balance: int,
        owner_user_id: int | None = None,
    ) -> FinanceAccount | None:
        return await accounts.update_account_balance(
            self.db,
            account_id,
            current_balance=current_balance,
            owner_user_id=owner_user_id,
        )

    async def liability_details(
        self, account_ids: list[int]
    ) -> dict[int, FinanceLiabilityDetail]:
        return await accounts.liability_details(self.db, account_ids)

    async def account_transaction_totals(
        self,
        *,
        owner_user_id: int | None = None,
        account_ids: list[int] | None = None,
    ) -> dict[int, int]:
        return await accounts.account_transaction_totals(
            self.db,
            owner_user_id=owner_user_id,
            account_ids=account_ids,
        )

    async def add_valuation(
        self,
        *,
        account_id: int,
        as_of_date: date,
        value: int,
        owner_user_id: int | None = None,
        source: str = "manual",
        source_ref: str | None = None,
    ) -> FinanceValuation:
        return await valuations.add_valuation(
            self.db,
            account_id=account_id,
            as_of_date=as_of_date,
            value=value,
            owner_user_id=owner_user_id,
            source=source,
            source_ref=source_ref,
        )

    async def update_account(
        self,
        account_id: int,
        *,
        owner_user_id: int | None = None,
        name: str | None = None,
        is_hidden: bool | None = None,
        is_closed: bool | None = None,
    ) -> FinanceAccount | None:
        return await accounts.update_account(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
            name=name,
            is_hidden=is_hidden,
            is_closed=is_closed,
        )

    async def set_secured_debt(
        self,
        account_id: int,
        *,
        owner_user_id: int | None = None,
        secured_by_account_id: int | None,
        lien_position: int | None = None,
    ) -> FinanceLiabilityDetail | None:
        """Link (or unlink) the property securing a liability."""
        return await properties.set_secured_debt(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
            secured_by_account_id=secured_by_account_id,
            lien_position=lien_position,
        )

    async def set_property_details(
        self,
        account_id: int,
        *,
        owner_user_id: int | None = None,
        **fields: Any,
    ) -> FinanceAccount | None:
        """Write a property account's facts (purchase, ownership, valuation
        provenance). Raises ValueError on a bad figure or a non-property
        account; the model is the boundary."""
        return await properties.set_property_details(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
            **fields,
        )

    async def soft_delete_account(
        self, account_id: int, *, owner_user_id: int | None = None
    ) -> bool:
        return await accounts.soft_delete_account(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
        )

    async def upsert_valuation(
        self,
        *,
        account_id: int,
        as_of_date: date,
        value: int,
        owner_user_id: int | None = None,
        source: str = "manual",
        source_ref: str | None = None,
        note: str | None = None,
    ) -> FinanceValuation:
        return await valuations.upsert_valuation(
            self.db,
            account_id=account_id,
            as_of_date=as_of_date,
            value=value,
            owner_user_id=owner_user_id,
            source=source,
            source_ref=source_ref,
            note=note,
        )

    async def register_balance_as_of(self, account_id: int, as_of: date) -> int:
        return await accounts.register_balance_as_of(self.db, account_id, as_of)

    async def reconcile_adjustment_for(
        self, account_id: int, statement_date: date
    ) -> FinanceTransaction | None:
        return await accounts.reconcile_adjustment_for(
            self.db,
            account_id,
            statement_date,
        )

    async def reconcile_preview(
        self,
        account_id: int,
        *,
        owner_user_id: int | None = None,
        statement_date: date,
        statement_balance: int,
    ) -> ReconcileResponse | None:
        return await accounts.reconcile_preview(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
            statement_date=statement_date,
            statement_balance=statement_balance,
        )

    async def reconcile_account(
        self,
        account_id: int,
        *,
        owner_user_id: int | None = None,
        statement_date: date,
        statement_balance: int,
    ) -> ReconcileResponse | None:
        return await accounts.reconcile_account(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
            statement_date=statement_date,
            statement_balance=statement_balance,
        )

    async def ingest_valuations(
        self,
        account_id: int,
        *,
        rows: list[tuple[date, int]],
        source: str = "manual",
        is_estimate: bool = False,
        note: str | None = None,
        owner_user_id: int | None = None,
    ) -> valuations.IngestResult:
        """Upsert a whole dated series from one source in one pass."""
        return await valuations.ingest_valuations(
            self.db,
            account_id,
            rows=rows,
            source=source,
            is_estimate=is_estimate,
            note=note,
            owner_user_id=owner_user_id,
        )

    async def list_valuations(
        self, account_id: int, *, owner_user_id: int | None = None
    ) -> list[FinanceValuation]:
        return await valuations.list_valuations(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
        )
