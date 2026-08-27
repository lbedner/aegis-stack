"""Budget lines, suggestions, the month summary and the outlook.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.finance.domains.planning import budgets
from app.services.finance.models import (
    FinanceBudget,
    FinanceBudgetCategory,
)
from app.services.finance.schemas import (
    BudgetLineResponse,
    BudgetMonthOutlook,
    BudgetStatDetailsResponse,
    BudgetSuggestion,
    BudgetSummaryResponse,
    DismissedBudgetSuggestion,
    GoalParseResponse,
)
from app.services.finance.service.base import FinanceServiceBase


class BudgetsMixin(FinanceServiceBase):
    """Budget lines, suggestions, the month summary and the outlook."""

    async def get_or_create_budget(
        self, *, owner_user_id: int | None, period_month: int
    ) -> FinanceBudget:
        return await budgets.get_or_create_budget(
            self.db,
            owner_user_id=owner_user_id,
            period_month=period_month,
        )

    async def spend_for_target(
        self,
        *,
        owner_user_id: int | None,
        period_month: int,
        category_id: int | None,
        payee_key: str | None,
    ) -> int:
        return await budgets.spend_for_target(
            self.db,
            owner_user_id=owner_user_id,
            period_month=period_month,
            category_id=category_id,
            payee_key=payee_key,
        )

    async def suggest_budget_lines(
        self,
        *,
        owner_user_id: int | None = None,
        today: date | None = None,
    ) -> list[BudgetSuggestion]:
        return await budgets.suggest_budget_lines(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
        )

    async def dismissal_markers(
        self, *, owner_user_id: int | None
    ) -> list[FinanceBudgetCategory]:
        return await budgets.dismissal_markers(self.db, owner_user_id=owner_user_id)

    async def list_dismissed_suggestions(
        self, *, owner_user_id: int | None = None
    ) -> list[DismissedBudgetSuggestion]:
        return await budgets.list_dismissed_suggestions(
            self.db,
            owner_user_id=owner_user_id,
        )

    async def dismiss_budget_suggestions(
        self, *, owner_user_id: int | None = None, category_ids: list[int]
    ) -> int:
        return await budgets.dismiss_budget_suggestions(
            self.db,
            owner_user_id=owner_user_id,
            category_ids=category_ids,
        )

    async def restore_budget_suggestions(
        self, *, owner_user_id: int | None = None, category_ids: list[int]
    ) -> int:
        return await budgets.restore_budget_suggestions(
            self.db,
            owner_user_id=owner_user_id,
            category_ids=category_ids,
        )

    async def upsert_budget_line(
        self,
        *,
        owner_user_id: int | None,
        period_month: int | None,
        category_id: int | None,
        payee_key: str | None,
        payee_label: str | None,
        allocated_amount: int,
        rollover_enabled: bool = False,
    ) -> BudgetLineResponse:
        return await budgets.upsert_budget_line(
            self.db,
            owner_user_id=owner_user_id,
            period_month=period_month,
            category_id=category_id,
            payee_key=payee_key,
            payee_label=payee_label,
            allocated_amount=allocated_amount,
            rollover_enabled=rollover_enabled,
        )

    async def delete_budget_line(
        self, line_id: int, *, owner_user_id: int | None = None
    ) -> bool:
        return await budgets.delete_budget_line(
            self.db,
            line_id,
            owner_user_id=owner_user_id,
        )

    async def budget_summary(
        self,
        *,
        owner_user_id: int | None = None,
        period_month: int | None = None,
        account_ids: list[int] | None = None,
        today: date | None = None,
    ) -> BudgetSummaryResponse:
        return await budgets.budget_summary(
            self.db,
            owner_user_id=owner_user_id,
            period_month=period_month,
            account_ids=account_ids,
            today=today,
        )

    async def uncovered_spending_rate(
        self,
        *,
        owner_user_id: int | None = None,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> int:
        return await budgets.uncovered_spending_rate(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
            account_ids=account_ids,
        )

    async def uncovered_spend_filters(
        self,
        *,
        owner_user_id: int | None,
        today: date | None,
        account_ids: list[int] | None,
    ) -> tuple[list[Any], tuple[date, date]]:
        return await budgets.uncovered_spend_filters(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
            account_ids=account_ids,
        )

    async def budget_stat_details(
        self,
        *,
        owner_user_id: int | None = None,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> BudgetStatDetailsResponse:
        return await budgets.budget_stat_details(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
            account_ids=account_ids,
        )

    async def budget_month_outlook(
        self,
        *,
        owner_user_id: int | None = None,
        months: int = 6,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> list[BudgetMonthOutlook]:
        return await budgets.budget_month_outlook(
            self.db,
            owner_user_id=owner_user_id,
            months=months,
            today=today,
            account_ids=account_ids,
        )

    async def parse_budget_goal(
        self, *, owner_user_id: int | None, text: str
    ) -> GoalParseResponse:
        return await budgets.parse_budget_goal(
            self.db,
            owner_user_id=owner_user_id,
            text=text,
        )
