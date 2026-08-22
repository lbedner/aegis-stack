"""Goals and envelopes - the two kinds of set-aside account.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from datetime import date

from app.services.finance.domains.planning import (
    allocation,
    envelopes,
    goals,
)
from app.services.finance.domains.planning.allocation import MonthlyFigures
from app.services.finance.domains.planning.goals import DEFAULT_PRIORITY
from app.services.finance.models import FinanceAccount
from app.services.finance.service.base import FinanceServiceBase


class GoalsMixin(FinanceServiceBase):
    """Goals and envelopes - the two kinds of set-aside account."""

    async def list_goals(
        self, *, owner_user_id: int | None = None
    ) -> list[FinanceAccount]:
        return await goals.list_goals(self.db, owner_user_id=owner_user_id)

    async def goal_allocations(
        self,
        *,
        owner_user_id: int | None,
        today: date,
        figures: MonthlyFigures | None = None,
    ) -> dict[int, int]:
        return await allocation.goal_allocations(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
            figures=figures,
        )

    async def goal_month_figures(
        self, *, owner_user_id: int | None, today: date
    ) -> MonthlyFigures:
        return await allocation.month_figures(
            self.db, owner_user_id=owner_user_id, today=today
        )

    async def goal_rate(self, account: FinanceAccount, *, today: date) -> int | None:
        return await goals.goal_rate(self.db, account, today=today)

    async def goal_rates(
        self, accounts: list[FinanceAccount], *, today: date
    ) -> dict[int, int | None]:
        return await goals.goal_rates(self.db, accounts, today=today)

    async def create_virtual_goal(
        self,
        *,
        owner_user_id: int | None,
        name: str,
        target_amount: int,
        target_date: date | None = None,
        monthly_contribution: int | None = None,
        contribution_kind: str = "fixed",
        contribution_bps: int | None = None,
        priority: int = DEFAULT_PRIORITY,
        target_rule: str = "fixed",
        target_factor: int | None = None,
        target_scope: list[int] | None = None,
    ) -> FinanceAccount:
        return await goals.create_virtual_goal(
            self.db,
            owner_user_id=owner_user_id,
            name=name,
            target_amount=target_amount,
            target_date=target_date,
            monthly_contribution=monthly_contribution,
            contribution_kind=contribution_kind,
            contribution_bps=contribution_bps,
            priority=priority,
            target_rule=target_rule,
            target_factor=target_factor,
            target_scope=target_scope,
        )

    async def flag_account_as_goal(
        self,
        account_id: int,
        *,
        owner_user_id: int | None,
        target_amount: int,
        target_date: date | None = None,
        monthly_contribution: int | None = None,
        contribution_kind: str = "fixed",
        contribution_bps: int | None = None,
        priority: int = DEFAULT_PRIORITY,
        target_rule: str = "fixed",
        target_factor: int | None = None,
        target_scope: list[int] | None = None,
    ) -> FinanceAccount | None:
        return await goals.flag_account_as_goal(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
            target_amount=target_amount,
            target_date=target_date,
            monthly_contribution=monthly_contribution,
            contribution_kind=contribution_kind,
            contribution_bps=contribution_bps,
            priority=priority,
            target_rule=target_rule,
            target_factor=target_factor,
            target_scope=target_scope,
        )

    async def unflag_goal(
        self, account_id: int, *, owner_user_id: int | None
    ) -> FinanceAccount | None:
        return await goals.unflag_goal(self.db, account_id, owner_user_id=owner_user_id)

    async def contribute_to_goal(
        self,
        account_id: int,
        *,
        amount: int,
        owner_user_id: int | None,
        when: date | None = None,
    ) -> FinanceAccount:
        return await goals.contribute_to_goal(
            self.db,
            account_id,
            amount=amount,
            owner_user_id=owner_user_id,
            when=when,
        )

    async def set_goal_status(
        self, account_id: int, status: str, *, owner_user_id: int | None
    ) -> FinanceAccount | None:
        return await goals.set_goal_status(
            self.db,
            account_id,
            status,
            owner_user_id=owner_user_id,
        )

    async def set_goal_auto_contribute(
        self, account_id: int, enabled: bool, *, owner_user_id: int | None
    ) -> FinanceAccount | None:
        return await goals.set_goal_auto_contribute(
            self.db,
            account_id,
            enabled,
            owner_user_id=owner_user_id,
        )

    async def auto_contribute_goals(
        self, *, owner_user_id: int | None, today: date
    ) -> int:
        return await goals.auto_contribute_goals(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
        )

    async def create_envelope(
        self,
        *,
        owner_user_id: int | None,
        name: str,
        monthly_credit: int | None = None,
        cadence: str = "monthly",
        starting_balance: int = 0,
    ) -> FinanceAccount:
        return await envelopes.create_envelope(
            self.db,
            owner_user_id=owner_user_id,
            name=name,
            monthly_credit=monthly_credit,
            cadence=cadence,
            starting_balance=starting_balance,
        )

    async def list_envelopes(
        self, *, owner_user_id: int | None = None
    ) -> list[FinanceAccount]:
        return await envelopes.list_envelopes(self.db, owner_user_id=owner_user_id)

    async def walk_envelope(
        self,
        account_id: int,
        *,
        delta: int,
        owner_user_id: int | None,
        when: date | None,
        note: str | None,
        source: str = "manual",
    ) -> FinanceAccount:
        return await envelopes.walk_envelope(
            self.db,
            account_id,
            delta=delta,
            owner_user_id=owner_user_id,
            when=when,
            note=note,
            source=source,
        )

    async def credit_envelope(
        self,
        account_id: int,
        *,
        amount: int,
        owner_user_id: int | None,
        when: date | None = None,
        note: str | None = None,
    ) -> FinanceAccount:
        return await envelopes.credit_envelope(
            self.db,
            account_id,
            amount=amount,
            owner_user_id=owner_user_id,
            when=when,
            note=note,
        )

    async def spend_from_envelope(
        self,
        account_id: int,
        *,
        amount: int,
        owner_user_id: int | None,
        when: date | None = None,
        note: str | None = None,
    ) -> FinanceAccount:
        return await envelopes.spend_from_envelope(
            self.db,
            account_id,
            amount=amount,
            owner_user_id=owner_user_id,
            when=when,
            note=note,
        )

    async def set_envelope_auto_credit(
        self, account_id: int, enabled: bool, *, owner_user_id: int | None
    ) -> FinanceAccount | None:
        return await envelopes.set_envelope_auto_credit(
            self.db,
            account_id,
            enabled,
            owner_user_id=owner_user_id,
        )

    async def update_envelope(
        self,
        account_id: int,
        *,
        owner_user_id: int | None,
        monthly_credit: int | None,
        auto_credit: bool,
        cadence: str = "monthly",
    ) -> FinanceAccount | None:
        return await envelopes.update_envelope(
            self.db,
            account_id,
            owner_user_id=owner_user_id,
            monthly_credit=monthly_credit,
            auto_credit=auto_credit,
            cadence=cadence,
        )

    async def auto_credit_envelopes(
        self, *, owner_user_id: int | None, today: date
    ) -> int:
        return await envelopes.auto_credit_envelopes(
            self.db,
            owner_user_id=owner_user_id,
            today=today,
        )
