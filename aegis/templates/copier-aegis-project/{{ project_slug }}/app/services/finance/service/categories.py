"""The category taxonomy and the suggestions over it.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from app.services.finance.domains.ledger import (
    categories,
)
from app.services.finance.domains.ledger import (
    categories as categories_service,
)
from app.services.finance.models import (
    FinanceCategory,
    FinanceTransaction,
)
from app.services.finance.schemas import (
    CategorySuggestionListResponse,
    CategoryUsageResponse,
)
from app.services.finance.service.base import FinanceServiceBase


class CategoriesMixin(FinanceServiceBase):
    """The category taxonomy and the suggestions over it."""

    async def resolve_category_alias(self, category_hint: str | None) -> int | None:
        return await categories.resolve_category_alias(self.db, category_hint)

    async def get_or_create_category_from_hint(
        self, hint: str | None
    ) -> FinanceCategory | None:
        return await categories.get_or_create_category_from_hint(self.db, hint)

    async def get_or_create_pfc_category(self, pfc_primary: str) -> FinanceCategory:
        return await categories.get_or_create_pfc_category(self.db, pfc_primary)

    async def category_names(self, ids: set[int] | list[int]) -> dict[int, str]:
        return await categories.category_names(self.db, ids)

    async def list_categories(self) -> list[FinanceCategory]:
        return await categories.list_categories(self.db)

    async def category_usage(
        self,
        *,
        owner_user_id: int | None = None,
        days: int | None = None,
    ) -> list[CategoryUsageResponse]:
        return await categories.category_usage(
            self.db,
            owner_user_id=owner_user_id,
            days=days,
        )

    async def spending_by_category(
        self,
        *,
        owner_user_id: int | None = None,
        days: int = 30,
        account_ids: list[int] | None = None,
    ) -> list[tuple[str, int]]:
        return await categories.spending_by_category(
            self.db,
            owner_user_id=owner_user_id,
            days=days,
            account_ids=account_ids,
        )

    async def spending_transactions(
        self,
        *,
        owner_user_id: int | None = None,
        days: int = 30,
        account_ids: list[int] | None = None,
        categories: list[str] | None = None,
    ) -> list[FinanceTransaction]:
        return await categories_service.spending_transactions(
            self.db,
            owner_user_id=owner_user_id,
            days=days,
            account_ids=account_ids,
            categories=categories,
        )

    async def spending_summary(
        self, *, owner_user_id: int | None = None, month: str | None = None
    ) -> list[tuple[str, int]]:
        return await categories.spending_summary(
            self.db,
            owner_user_id=owner_user_id,
            month=month,
        )

    async def categorize_transaction(
        self,
        transaction_id: int,
        category_id: int,
        *,
        owner_user_id: int | None = None,
        source: str = "user",
    ) -> FinanceTransaction | None:
        return await categories.categorize_transaction(
            self.db,
            transaction_id,
            category_id,
            owner_user_id=owner_user_id,
            source=source,
        )

    async def suggest_categories(
        self,
        *,
        owner_user_id: int | None = None,
        transaction_ids: list[int] | set[int] | None = None,
    ) -> CategorySuggestionListResponse:
        return await categories.suggest_categories(
            self.db,
            owner_user_id=owner_user_id,
            transaction_ids=transaction_ids,
        )
