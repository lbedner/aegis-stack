"""GL-01: the ``'goal'`` account type and the goal-metadata contract.

A goal is an account wearing goal metadata - no goal tables. Virtual
goals are hidden manual accounts (net worth and listings already exclude
hidden accounts; the exclusion is regression-pinned here because the
whole design leans on it). Targets live in ``metadata_`` behind the
typed accessors in ``app/services/finance/goals.py`` - the service layer
owns the shape, SQL never reads it.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.planning.goals import (
    GOAL_ACCOUNT_TYPE,
    GoalMeta,
    MonthlyFigures,
    allocate_month,
    clear_goal_metadata,
    goal_eta,
    goal_metadata,
    goal_monthly_need,
    goal_progress,
    set_goal_metadata,
)
from app.services.finance.service import FinanceService


class TestMetadataContract:
    def test_round_trip(self) -> None:
        written = set_goal_metadata(
            {"reconciled_through": "2026-08-01"},  # neighbours survive
            target_amount=300_000,
            target_date=date(2027, 6, 1),
            monthly_contribution=25_000,
        )
        meta = goal_metadata(written)
        assert meta == GoalMeta(
            target_amount=300_000,
            status="active",
            target_date=date(2027, 6, 1),
            monthly_contribution=25_000,
        )
        assert written["reconciled_through"] == "2026-08-01"

    def test_stored_shape_is_json_native(self) -> None:
        """The stored form is the storage contract: plain JSON keys and
        values, no model objects leaking into ``metadata_``."""
        written = set_goal_metadata(
            None,
            target_amount=300_000,
            target_date=date(2027, 6, 1),
            monthly_contribution=25_000,
        )
        assert written == {
            "goal_target_amount": 300_000,
            "goal_status": "active",
            "goal_target_date": "2027-06-01",
            "goal_monthly_contribution": 25_000,
            "goal_contribution_kind": "fixed",
            "goal_contribution_bps": None,
            "goal_priority": 100,
        }

    def test_minimal_goal_defaults(self) -> None:
        meta = goal_metadata(set_goal_metadata(None, target_amount=100_000))
        assert meta is not None
        assert meta.status == "active"
        assert meta.target_date is None
        assert meta.monthly_contribution is None

    def test_no_goal_metadata_reads_as_none(self) -> None:
        assert goal_metadata(None) is None
        assert goal_metadata({}) is None
        assert goal_metadata({"pause_note": "x"}) is None

    def test_unknown_status_is_rejected_hard(self) -> None:
        with pytest.raises(ValueError):
            set_goal_metadata(None, target_amount=100_000, status="dreaming")

    def test_nonpositive_target_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_goal_metadata(None, target_amount=0)
        with pytest.raises(ValueError):
            set_goal_metadata(None, target_amount=-5)

    def test_negative_monthly_contribution_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_goal_metadata(None, target_amount=100, monthly_contribution=-1)

    def test_corrupt_stored_status_raises_not_swallows(self) -> None:
        corrupt = {"goal_target_amount": 100_000, "goal_status": "vibing"}
        with pytest.raises(ValueError):
            goal_metadata(corrupt)

    def test_clear_strips_only_goal_keys(self) -> None:
        written = set_goal_metadata({"pause_note": "keep me"}, target_amount=100_000)
        cleared = clear_goal_metadata(written)
        assert goal_metadata(cleared) is None
        assert cleared["pause_note"] == "keep me"


class TestGoalAccountType:
    @pytest.mark.asyncio
    async def test_a_goal_account_inserts(self, async_db_session: AsyncSession) -> None:
        account = await FinanceService(async_db_session).create_manual_account(
            owner_user_id=1,
            name="Vacation",
            account_type=GOAL_ACCOUNT_TYPE,
            classification="asset",
        )
        await async_db_session.commit()
        assert account.id is not None

    @pytest.mark.asyncio
    async def test_hidden_goal_account_is_excluded_everywhere(
        self, async_db_session: AsyncSession
    ) -> None:
        """The design's load-bearing wall, pinned: a hidden goal account
        adds nothing to net worth (its money already sits in checking)
        and never appears in account listings."""
        service = FinanceService(async_db_session)
        await service.create_manual_account(
            owner_user_id=1,
            name="Chase Checking",
            account_type="checking",
            classification="asset",
            current_balance=100_000,
        )
        goal = await service.create_manual_account(
            owner_user_id=1,
            name="Vacation",
            account_type=GOAL_ACCOUNT_TYPE,
            classification="asset",
            current_balance=30_000,
        )
        goal.is_hidden = True
        async_db_session.add(goal)
        await async_db_session.commit()

        net_worth = await service.get_net_worth(owner_user_id=1)
        assert net_worth.total_assets_amount == 100_000  # goal's 30k absent

        accounts, total = await service.list_accounts(owner_user_id=1)
        assert total == 1
        assert [a.name for a in accounts] == ["Chase Checking"]


class TestPureMath:
    """GL-02's derived trio - pure, structured, the analyst's future
    material (it must never do this math itself)."""

    def test_progress_is_a_fraction_clamped_at_one(self) -> None:
        assert goal_progress(balance=120_000, target=300_000) == 0.4
        assert goal_progress(balance=350_000, target=300_000) == 1.0
        assert goal_progress(balance=-500, target=300_000) == 0.0

    def test_monthly_need_from_target_date(self) -> None:
        # $3,000 target, $1,200 saved, due in 6 months -> $300/mo.
        need = goal_monthly_need(
            GoalMeta(
                target_amount=300_000, status="active", target_date=date(2027, 2, 10)
            ),
            balance=120_000,
            today=date(2026, 8, 10),
        )
        assert need == 30_000

    def test_monthly_need_due_this_month_wants_the_rest_now(self) -> None:
        need = goal_monthly_need(
            GoalMeta(
                target_amount=300_000, status="active", target_date=date(2026, 8, 20)
            ),
            balance=250_000,
            today=date(2026, 8, 10),
        )
        assert need == 50_000

    def test_monthly_need_without_date_is_the_declared_rate(self) -> None:
        meta = GoalMeta(
            target_amount=300_000, status="active", monthly_contribution=25_000
        )
        assert goal_monthly_need(meta, balance=0, today=date(2026, 8, 10)) == 25_000

    def test_monthly_need_is_zero_when_reached_or_paused(self) -> None:
        reached = GoalMeta(target_amount=100_000, status="reached")
        paused = GoalMeta(
            target_amount=100_000, status="paused", monthly_contribution=5_000
        )
        overfull = GoalMeta(
            target_amount=100_000, status="active", target_date=date(2027, 1, 1)
        )
        today = date(2026, 8, 10)
        assert goal_monthly_need(reached, balance=0, today=today) == 0
        assert goal_monthly_need(paused, balance=0, today=today) == 0
        assert goal_monthly_need(overfull, balance=150_000, today=today) == 0

    def test_eta_at_a_rate(self) -> None:
        # $1,800 to go at $300/mo -> six months out.
        eta = goal_eta(
            balance=120_000,
            target=300_000,
            monthly_rate=30_000,
            today=date(2026, 8, 10),
        )
        assert eta == date(2027, 2, 10)

    def test_eta_reached_is_today(self) -> None:
        eta = goal_eta(
            balance=300_000, target=300_000, monthly_rate=0, today=date(2026, 8, 10)
        )
        assert eta == date(2026, 8, 10)

    def test_eta_without_a_rate_is_never(self) -> None:
        today = date(2026, 8, 10)
        assert goal_eta(balance=0, target=100, monthly_rate=0, today=today) is None
        assert goal_eta(balance=0, target=100, monthly_rate=None, today=today) is None


class TestGoalService:
    @pytest.mark.asyncio
    async def test_create_virtual_goal(self, async_db_session: AsyncSession) -> None:
        service = FinanceService(async_db_session)
        account = await service.create_virtual_goal(
            owner_user_id=1,
            name="Vacation",
            target_amount=300_000,
            target_date=date(2027, 6, 1),
        )
        assert account.account_type == GOAL_ACCOUNT_TYPE
        assert account.is_hidden is True
        assert account.is_manual is True
        meta = goal_metadata(account.metadata_)
        assert meta is not None and meta.target_amount == 300_000

    @pytest.mark.asyncio
    async def test_contribute_moves_the_balance(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        account = await service.create_virtual_goal(
            owner_user_id=1, name="Vacation", target_amount=300_000
        )
        await service.contribute_to_goal(
            account.id, amount=25_000, owner_user_id=1, when=date(2026, 8, 1)
        )
        await service.contribute_to_goal(
            account.id, amount=10_000, owner_user_id=1, when=date(2026, 9, 1)
        )
        refreshed = await service.get_account(account.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 35_000

    @pytest.mark.asyncio
    async def test_contribute_to_a_linked_goal_is_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        """A linked goal's contributions are its real transfers - a manual
        top-up would double-count against the account's own register."""
        service = FinanceService(async_db_session)
        savings = await service.create_manual_account(
            owner_user_id=1,
            name="CHASE SAVINGS",
            account_type="savings",
            classification="asset",
        )
        await service.flag_account_as_goal(
            savings.id, owner_user_id=1, target_amount=1_200_000
        )
        with pytest.raises(ValueError):
            await service.contribute_to_goal(savings.id, amount=10_000, owner_user_id=1)

    @pytest.mark.asyncio
    async def test_flag_and_unflag_leave_the_account_intact(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        savings = await service.create_manual_account(
            owner_user_id=1,
            name="CHASE SAVINGS",
            account_type="savings",
            classification="asset",
            current_balance=65_900,
        )
        await service.flag_account_as_goal(
            savings.id, owner_user_id=1, target_amount=1_200_000
        )
        flagged = await service.get_account(savings.id, owner_user_id=1)
        assert flagged is not None and goal_metadata(flagged.metadata_) is not None
        assert flagged.is_hidden is False  # linked goals stay visible

        await service.unflag_goal(savings.id, owner_user_id=1)
        unflagged = await service.get_account(savings.id, owner_user_id=1)
        assert unflagged is not None
        assert goal_metadata(unflagged.metadata_) is None
        assert unflagged.current_balance == 65_900  # untouched

    @pytest.mark.asyncio
    async def test_status_transitions(self, async_db_session: AsyncSession) -> None:
        service = FinanceService(async_db_session)
        account = await service.create_virtual_goal(
            owner_user_id=1, name="Vacation", target_amount=300_000
        )
        await service.set_goal_status(account.id, "paused", owner_user_id=1)
        paused = await service.get_account(account.id, owner_user_id=1)
        assert goal_metadata(paused.metadata_).status == "paused"

        await service.set_goal_status(account.id, "active", owner_user_id=1)
        active = await service.get_account(account.id, owner_user_id=1)
        assert goal_metadata(active.metadata_).status == "active"

        with pytest.raises(ValueError):
            await service.set_goal_status(account.id, "vibing", owner_user_id=1)


class TestGoalsInTheProjection:
    """GL-05: active goals emit monthly outflows in project_balances -
    committing to a dream visibly costs the chart. Paused emits nothing,
    and a linked goal's synthetic outflow yields for any month a real
    transfer already booked (or commit+transfer double-drops the line)."""

    async def _cash(self, service: FinanceService) -> int:
        account = await service.create_manual_account(
            owner_user_id=1,
            name="Checking",
            account_type="checking",
            classification="asset",
            current_balance=1_000_000,
        )
        return account.id

    @pytest.mark.asyncio
    async def test_a_virtual_goal_drains_the_walk_monthly(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        await self._cash(service)
        await service.create_virtual_goal(
            owner_user_id=1,
            name="Vacation",
            target_amount=300_000,
            monthly_contribution=25_000,
        )
        projection = await service.project_balances(
            owner_user_id=1, days=90, today=date(2026, 8, 10)
        )
        goal_points = [p for p in projection.points if p.name == "Vacation"]
        assert len(goal_points) == 3  # Sep 1, Oct 1, Nov 1
        assert all(p.amount == -25_000 for p in goal_points)
        assert projection.points[-1].balance <= 1_000_000 - 3 * 25_000

    @pytest.mark.asyncio
    async def test_a_paused_goal_emits_nothing(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        await self._cash(service)
        goal = await service.create_virtual_goal(
            owner_user_id=1,
            name="Vacation",
            target_amount=300_000,
            monthly_contribution=25_000,
        )
        await service.set_goal_status(goal.id, "paused", owner_user_id=1)
        projection = await service.project_balances(
            owner_user_id=1, days=90, today=date(2026, 8, 10)
        )
        assert not [p for p in projection.points if p.name == "Vacation"]

    @pytest.mark.asyncio
    async def test_a_linked_goals_month_yields_to_a_real_transfer(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        cash_id = await self._cash(service)
        savings = await service.create_manual_account(
            owner_user_id=1,
            name="CHASE SAVINGS",
            account_type="savings",
            classification="asset",
        )
        await service.flag_account_as_goal(
            savings.id,
            owner_user_id=1,
            target_amount=1_200_000,
            monthly_contribution=30_000,
        )
        # A real transfer into the goal account, booked in September.
        out_leg = await service.create_transaction(
            account_id=cash_id,
            amount=-30_000,
            txn_date=date(2026, 9, 3),
            owner_user_id=1,
            name="To savings",
        )
        in_leg = await service.create_transaction(
            account_id=savings.id,
            amount=30_000,
            txn_date=date(2026, 9, 3),
            owner_user_id=1,
            name="From checking",
        )
        out_leg.is_transfer = True
        in_leg.is_transfer = True
        async_db_session.add(out_leg)
        async_db_session.add(in_leg)
        await async_db_session.flush()

        projection = await service.project_balances(
            owner_user_id=1, days=90, today=date(2026, 8, 10)
        )
        goal_points = [p for p in projection.points if p.name == "CHASE SAVINGS"]
        months = {p.date.month for p in goal_points}
        assert 9 not in months  # September yielded to the real transfer
        assert {10, 11} <= months


class TestAutoContribute:
    """GL-10: the monthly auto-contribute job books each toggled-on
    virtual goal's declared amount as a 'goal_auto' valuation on the 1st.
    The plan books it; you must actively pause to not save. Idempotent
    per month; paused/linked/toggle-off goals are skipped."""

    @pytest.mark.asyncio
    async def test_books_once_and_only_once(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        goal = await service.create_virtual_goal(
            owner_user_id=1,
            name="Vacation",
            target_amount=300_000,
            monthly_contribution=25_000,
        )
        await service.set_goal_auto_contribute(goal.id, True, owner_user_id=1)

        first = await service.auto_contribute_goals(
            owner_user_id=1, today=date(2026, 9, 1)
        )
        again = await service.auto_contribute_goals(
            owner_user_id=1,
            today=date(2026, 9, 15),  # rerun mid-month
        )

        assert first == 1
        assert again == 0
        refreshed = await service.get_account(goal.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 25_000  # once, not twice

    @pytest.mark.asyncio
    async def test_next_month_books_again(self, async_db_session: AsyncSession) -> None:
        service = FinanceService(async_db_session)
        goal = await service.create_virtual_goal(
            owner_user_id=1,
            name="Vacation",
            target_amount=300_000,
            monthly_contribution=25_000,
        )
        await service.set_goal_auto_contribute(goal.id, True, owner_user_id=1)
        await service.auto_contribute_goals(owner_user_id=1, today=date(2026, 9, 1))
        await service.auto_contribute_goals(owner_user_id=1, today=date(2026, 10, 1))
        refreshed = await service.get_account(goal.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 50_000

    @pytest.mark.asyncio
    async def test_paused_toggle_off_and_linked_are_skipped(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        # Toggle off (the default): never booked.
        await service.create_virtual_goal(
            owner_user_id=1,
            name="Quiet",
            target_amount=100_000,
            monthly_contribution=10_000,
        )
        # Toggled on but paused: skipped.
        paused = await service.create_virtual_goal(
            owner_user_id=1,
            name="Paused",
            target_amount=100_000,
            monthly_contribution=10_000,
        )
        await service.set_goal_auto_contribute(paused.id, True, owner_user_id=1)
        await service.set_goal_status(paused.id, "paused", owner_user_id=1)
        # Linked: reality books it, never the job.
        savings = await service.create_manual_account(
            owner_user_id=1,
            name="CHASE SAVINGS",
            account_type="savings",
            classification="asset",
        )
        await service.flag_account_as_goal(
            savings.id,
            owner_user_id=1,
            target_amount=1_000_000,
            monthly_contribution=30_000,
        )

        booked = await service.auto_contribute_goals(
            owner_user_id=1, today=date(2026, 9, 1)
        )
        assert booked == 0


class TestAllocationEngine:
    """The pure allocation engine: contribution rules evaluated in
    priority order against the month's code-owned figures. Modes are
    goal-set templates on top of exactly this."""

    def _goal(self, name: str, **kw) -> tuple[GoalMeta, int]:
        balance = kw.pop("balance", 0)
        defaults = dict(target_amount=1_000_000, status="active")
        defaults.update(kw)
        return (
            GoalMeta(**defaults),
            balance,
            name,
        )

    def test_percent_of_income_evaluates_monthly(self) -> None:
        figures = MonthlyFigures(income_total=820_000, committed=0)
        meta, balance, name = self._goal(
            "Retire", contribution_kind="percent_income", contribution_bps=1_000
        )
        asks = allocate_month(figures, [(name, meta, balance)])
        assert asks == {"Retire": 82_000}  # 10% of $8,200

    def test_percent_of_zero_income_is_zero(self) -> None:
        figures = MonthlyFigures(income_total=0, committed=0)
        meta, balance, name = self._goal(
            "Retire", contribution_kind="percent_income", contribution_bps=1_000
        )
        assert allocate_month(figures, [(name, meta, balance)]) == {"Retire": 0}

    def test_surplus_takes_whats_left_never_below_zero(self) -> None:
        # $8,200 income, $7,000 committed, one $500 fixed goal above the
        # sweep -> the sweep gets the remaining $700, not $1,200.
        figures = MonthlyFigures(income_total=820_000, committed=700_000)
        fixed = self._goal("Starter", monthly_contribution=50_000, priority=1)
        sweep = self._goal("Snowball", contribution_kind="surplus", priority=2)
        asks = allocate_month(
            figures,
            [("Starter", fixed[0], fixed[1]), ("Snowball", sweep[0], sweep[1])],
        )
        assert asks["Starter"] == 50_000
        assert asks["Snowball"] == 70_000

        # Committed already exceeds income -> the sweep asks nothing.
        broke = MonthlyFigures(income_total=820_000, committed=900_000)
        asks = allocate_month(broke, [("Snowball", sweep[0], sweep[1])])
        assert asks["Snowball"] == 0

    def test_two_surplus_goals_fund_in_priority_order(self) -> None:
        figures = MonthlyFigures(income_total=500_000, committed=400_000)
        first = self._goal(
            "Debt",
            contribution_kind="surplus",
            priority=1,
            target_amount=60_000,
        )
        second = self._goal("Fund", contribution_kind="surplus", priority=2)
        asks = allocate_month(
            figures, [("Fund", second[0], second[1]), ("Debt", first[0], first[1])]
        )
        # Priority 1 takes up to its remaining target ($600), priority 2
        # gets the rest ($400) - order comes from priority, not list order.
        assert asks["Debt"] == 60_000
        assert asks["Fund"] == 40_000

    def test_every_ask_caps_at_remaining_to_target(self) -> None:
        figures = MonthlyFigures(income_total=820_000, committed=0)
        meta, balance, name = self._goal(
            "Nearly", monthly_contribution=50_000, balance=980_000
        )
        asks = allocate_month(figures, [(name, meta, balance)])
        assert asks["Nearly"] == 20_000  # not the full $500

    def test_paused_and_reached_ask_nothing(self) -> None:
        figures = MonthlyFigures(income_total=820_000, committed=0)
        paused = self._goal("Paused", status="paused", monthly_contribution=50_000)
        full = self._goal("Full", monthly_contribution=50_000, balance=1_000_000)
        asks = allocate_month(
            figures,
            [("Paused", paused[0], paused[1]), ("Full", full[0], full[1])],
        )
        assert asks == {"Paused": 0, "Full": 0}

    def test_metadata_round_trips_the_rule(self) -> None:
        written = set_goal_metadata(
            None,
            target_amount=1_000_000,
            contribution_kind="percent_income",
            contribution_bps=1_500,
            priority=2,
        )
        meta = goal_metadata(written)
        assert meta is not None
        assert meta.contribution_kind == "percent_income"
        assert meta.contribution_bps == 1_500
        assert meta.priority == 2
        # Old goals with no kind read as fixed at default priority.
        legacy = goal_metadata(
            set_goal_metadata(None, target_amount=100, monthly_contribution=10)
        )
        assert legacy is not None
        assert legacy.contribution_kind == "fixed"
        assert legacy.priority == 100

    def test_bad_rules_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_goal_metadata(None, target_amount=100, contribution_kind="vibes")
        with pytest.raises(ValueError):
            set_goal_metadata(
                None,
                target_amount=100,
                contribution_kind="percent_income",
                contribution_bps=0,
            )
        with pytest.raises(ValueError):
            set_goal_metadata(
                None,
                target_amount=100,
                contribution_kind="percent_income",
                contribution_bps=10_001,
            )


class TestConsumersReadTheEngine:
    """GL-14: month_net, the projection, and auto-contribute all charge
    the EVALUATED allocation, not the raw declared amount."""

    async def _income(self, service: FinanceService) -> int:
        account = await service.create_manual_account(
            owner_user_id=1,
            name="Checking",
            account_type="checking",
            classification="asset",
            current_balance=1_000_000,
        )
        await service.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=820_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        return account.id

    @pytest.mark.asyncio
    async def test_a_percent_goal_moves_the_month_by_its_evaluation(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        await self._income(service)
        goal = await service.create_virtual_goal(
            owner_user_id=1,
            name="Retire",
            target_amount=10_000_000,
            contribution_kind="percent_income",
            contribution_bps=1_000,
        )
        stats = (await service.budget_summary(owner_user_id=1)).stats
        assert stats.goals_total == 82_000  # 10% of $8,200
        assert stats.month_net == 820_000 - 82_000

        allocations = await service.goal_allocations(
            owner_user_id=1, today=date(2026, 8, 10)
        )
        assert allocations[goal.id] == 82_000

    @pytest.mark.asyncio
    async def test_the_projection_charges_the_evaluation(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        await self._income(service)
        await service.create_virtual_goal(
            owner_user_id=1,
            name="Retire",
            target_amount=10_000_000,
            contribution_kind="percent_income",
            contribution_bps=1_000,
        )
        projection = await service.project_balances(
            owner_user_id=1, days=60, today=date(2026, 8, 10)
        )
        goal_points = [p for p in projection.points if p.name == "Retire"]
        assert goal_points and all(p.amount == -82_000 for p in goal_points)

    @pytest.mark.asyncio
    async def test_auto_contribute_books_the_evaluation(
        self, async_db_session: AsyncSession
    ) -> None:
        service = FinanceService(async_db_session)
        await self._income(service)
        goal = await service.create_virtual_goal(
            owner_user_id=1,
            name="Retire",
            target_amount=10_000_000,
            contribution_kind="percent_income",
            contribution_bps=1_000,
        )
        await service.set_goal_auto_contribute(goal.id, True, owner_user_id=1)
        booked = await service.auto_contribute_goals(
            owner_user_id=1, today=date(2026, 9, 1)
        )
        assert booked == 1
        refreshed = await service.get_account(goal.id, owner_user_id=1)
        assert refreshed is not None
        assert refreshed.current_balance == 82_000

    @pytest.mark.asyncio
    async def test_pausing_via_status_keeps_the_rule(
        self, async_db_session: AsyncSession
    ) -> None:
        """set_goal_status must not flatten a percent rule back to fixed."""
        service = FinanceService(async_db_session)
        await self._income(service)
        goal = await service.create_virtual_goal(
            owner_user_id=1,
            name="Retire",
            target_amount=10_000_000,
            contribution_kind="percent_income",
            contribution_bps=1_000,
        )
        await service.set_goal_status(goal.id, "paused", owner_user_id=1)
        await service.set_goal_status(goal.id, "active", owner_user_id=1)
        refreshed = await service.get_account(goal.id, owner_user_id=1)
        meta = goal_metadata(refreshed.metadata_)
        assert meta is not None
        assert meta.contribution_kind == "percent_income"
        assert meta.contribution_bps == 1_000
