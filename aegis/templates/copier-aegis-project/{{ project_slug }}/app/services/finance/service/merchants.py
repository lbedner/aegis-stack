"""Payees: naming them, merging them, and what points at them.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.finance.domains.ledger import merchants
from app.services.finance.domains.ledger.merchants import _UNSET
from app.services.finance.models import (
    FinanceMerchant,
    FinanceTransaction,
)
from app.services.finance.schemas import (
    MerchantCategorySummary,
    PayeeGroup,
)
from app.services.finance.service.base import FinanceServiceBase


class MerchantsMixin(FinanceServiceBase):
    """Payees: naming them, merging them, and what points at them."""

    async def list_merchants(
        self, *, owner_user_id: int | None = None
    ) -> list[FinanceMerchant]:
        return await merchants.list_merchants(self.db, owner_user_id=owner_user_id)

    async def create_merchant(
        self,
        name: str,
        *,
        owner_user_id: int | None = None,
        website_url: str | None = None,
    ) -> FinanceMerchant:
        return await merchants.create_merchant(
            self.db,
            name,
            owner_user_id=owner_user_id,
            website_url=website_url,
        )

    async def set_merchant_website(
        self, merchant_id: int, website_url: str | None
    ) -> FinanceMerchant | None:
        return await merchants.set_merchant_website(self.db, merchant_id, website_url)

    async def update_merchant(
        self,
        merchant_id: int,
        *,
        name: str | None = None,
        website_url: str | None | Any = _UNSET,
        default_category_id: int | None | Any = _UNSET,
        owner_user_id: int | None = None,
    ) -> FinanceMerchant | None:
        return await merchants.update_merchant(
            self.db,
            merchant_id,
            name=name,
            website_url=website_url,
            default_category_id=default_category_id,
            owner_user_id=owner_user_id,
        )

    async def merge_merchants(
        self,
        source_ids: list[int],
        target_id: int,
        *,
        owner_user_id: int | None = None,
    ) -> int:
        return await merchants.merge_merchants(
            self.db,
            source_ids,
            target_id,
            owner_user_id=owner_user_id,
        )

    async def merchant_usage(
        self,
        *,
        owner_user_id: int | None = None,
        account_ids: list[int] | None = None,
    ) -> dict[int, dict[str, Any]]:
        return await merchants.merchant_usage(
            self.db,
            owner_user_id=owner_user_id,
            account_ids=account_ids,
        )

    async def merchant_websites(self, ids: set[int] | list[int]) -> dict[int, str]:
        return await merchants.merchant_websites(self.db, ids)

    async def merchant_names(self, ids: set[int] | list[int]) -> dict[int, str]:
        return await merchants.merchant_names(self.db, ids)

    async def assign_merchant(
        self,
        transaction_ids: Sequence[int],
        merchant_id: int | None,
        *,
        owner_user_id: int | None = None,
        category_id: int | None = None,
    ) -> int:
        return await merchants.assign_merchant(
            self.db,
            transaction_ids,
            merchant_id,
            owner_user_id=owner_user_id,
            category_id=category_id,
        )

    async def merchant_category_summary(
        self, merchant_id: int, *, owner_user_id: int | None = None
    ) -> MerchantCategorySummary:
        return await merchants.merchant_category_summary(
            self.db,
            merchant_id,
            owner_user_id=owner_user_id,
        )

    async def payee_groups(
        self, *, owner_user_id: int | None = None, limit: int = 200
    ) -> tuple[list[PayeeGroup], int, int]:
        return await merchants.payee_groups(
            self.db,
            owner_user_id=owner_user_id,
            limit=limit,
        )

    async def assign_payee_group(
        self,
        keys: Sequence[str],
        merchant_id: int,
        *,
        owner_user_id: int | None = None,
        category_id: int | None = None,
    ) -> int:
        return await merchants.assign_payee_group(
            self.db,
            keys,
            merchant_id,
            owner_user_id=owner_user_id,
            category_id=category_id,
        )

    async def similar_unassigned(
        self, transaction_id: int, *, owner_user_id: int | None = None
    ) -> list[FinanceTransaction]:
        return await merchants.similar_unassigned(
            self.db,
            transaction_id,
            owner_user_id=owner_user_id,
        )
