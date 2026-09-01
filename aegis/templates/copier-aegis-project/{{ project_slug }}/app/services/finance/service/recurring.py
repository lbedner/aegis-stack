"""Recurring streams: bills, income, matching and the forecast.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from app.services.finance.domains.planning import recurring
from app.services.finance.models import (
    FinanceRecurringStream,
    FinanceTransaction,
)
from app.services.finance.schemas import ProjectionResponse
from app.services.finance.service.base import FinanceServiceBase


class RecurringMixin(FinanceServiceBase):
    """Recurring streams: bills, income, matching and the forecast."""

    async def list_recurring(
        self, *, owner_user_id: int | None = None
    ) -> list[FinanceRecurringStream]:
        return await recurring.list_recurring(self.db, owner_user_id=owner_user_id)

    async def create_recurring_stream(
        self,
        *,
        owner_user_id: int | None,
        name: str,
        direction: str,
        frequency: str,
        expected_amount: int,
        next_expected_date: date,
        account_id: int | None = None,
        is_subscription: bool = False,
        subject_id: int | None = None,
    ) -> FinanceRecurringStream:
        return await recurring.create_recurring_stream(
            self.db,
            owner_user_id=owner_user_id,
            name=name,
            direction=direction,
            frequency=frequency,
            expected_amount=expected_amount,
            next_expected_date=next_expected_date,
            account_id=account_id,
            is_subscription=is_subscription,
            subject_id=subject_id,
        )

    async def transfer_stream_ids(self, stream_ids: Sequence[int]) -> set[int]:
        return await recurring.transfer_stream_ids(self.db, stream_ids)

    async def payment_stream_ids(self, stream_ids: Sequence[int]) -> set[int]:
        return await recurring.payment_stream_ids(self.db, stream_ids)

    async def get_recurring(
        self, stream_id: int, owner_user_id: int | None
    ) -> FinanceRecurringStream | None:
        return await recurring.get_recurring(self.db, stream_id, owner_user_id)

    async def mute_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> FinanceRecurringStream | None:
        return await recurring.mute_recurring(
            self.db,
            stream_id,
            owner_user_id=owner_user_id,
        )

    async def unmute_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> FinanceRecurringStream | None:
        return await recurring.unmute_recurring(
            self.db,
            stream_id,
            owner_user_id=owner_user_id,
        )

    async def attach_transaction_to_stream(
        self,
        transaction_id: int,
        stream_id: int,
        *,
        owner_user_id: int | None = None,
    ) -> FinanceRecurringStream | None:
        return await recurring.attach_transaction_to_stream(
            self.db,
            transaction_id,
            stream_id,
            owner_user_id=owner_user_id,
        )

    async def recurring_match_candidates(
        self,
        stream_id: int,
        *,
        owner_user_id: int | None = None,
        limit: int = 20,
    ) -> list[FinanceTransaction]:
        return await recurring.recurring_match_candidates(
            self.db,
            stream_id,
            owner_user_id=owner_user_id,
            limit=limit,
        )

    async def pause_recurring(
        self,
        stream_id: int,
        *,
        until: date,
        note: str | None = None,
        owner_user_id: int | None = None,
    ) -> FinanceRecurringStream | None:
        return await recurring.pause_recurring(
            self.db,
            stream_id,
            until=until,
            note=note,
            owner_user_id=owner_user_id,
        )

    async def resume_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> FinanceRecurringStream | None:
        return await recurring.resume_recurring(
            self.db,
            stream_id,
            owner_user_id=owner_user_id,
        )

    async def confirm_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> FinanceRecurringStream | None:
        return await recurring.confirm_recurring(
            self.db,
            stream_id,
            owner_user_id=owner_user_id,
        )

    async def update_recurring(
        self,
        stream_id: int,
        *,
        owner_user_id: int | None = None,
        name: str | None = None,
        frequency: str | None = None,
        expected_amount: int | None = None,
        next_expected_date: date | None = None,
        category_id: int | None = None,
        account_id: int | None = None,
    ) -> FinanceRecurringStream | None:
        return await recurring.update_recurring(
            self.db,
            stream_id,
            owner_user_id=owner_user_id,
            name=name,
            frequency=frequency,
            expected_amount=expected_amount,
            next_expected_date=next_expected_date,
            category_id=category_id,
            account_id=account_id,
        )

    async def stream_category_names(
        self, stream_ids: Sequence[int] | set[int]
    ) -> dict[int, str]:
        return await recurring.stream_category_names(self.db, stream_ids)

    async def project_balances(
        self,
        *,
        owner_user_id: int | None = None,
        days: int = 180,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> ProjectionResponse:
        return await recurring.project_balances(
            self.db,
            owner_user_id=owner_user_id,
            days=days,
            today=today,
            account_ids=account_ids,
        )

    async def goal_drawdowns(
        self,
        *,
        owner_user_id: int | None,
        today: date,
        horizon: date,
    ) -> list[tuple[date, str, int, dict[str, Any]]]:
        return await recurring.goal_drawdowns(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
            horizon=horizon,
        )

    async def budget_drawdowns(
        self,
        *,
        owner_user_id: int | None,
        today: date,
        horizon: date,
        skip_categories: set[int],
    ) -> list[tuple[date, str, int, dict[str, Any]]]:
        return await recurring.budget_drawdowns(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
            horizon=horizon,
            skip_categories=skip_categories,
        )

    async def delete_recurring(
        self, stream_id: int, *, owner_user_id: int | None = None
    ) -> bool:
        return await recurring.delete_recurring(
            self.db,
            stream_id,
            owner_user_id=owner_user_id,
        )
