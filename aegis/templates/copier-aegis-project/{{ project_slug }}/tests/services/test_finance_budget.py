"""Tests for the Budget tab's service layer.

Covers ``get_or_create_budget`` idempotency, ``upsert_budget_line`` for both
target shapes, ``budget_summary``'s spend math (category and payee level,
plus the Fixed/Non-monthly recurring split), ``parse_budget_goal``'s
deterministic matching, and a concrete N+1 check on ``budget_summary``.
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import PAUSE_INDEFINITE
from app.services.finance.schemas import BudgetLineResponse, GoalAsk
from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_category as _category
from tests.services._finance_factories import seed_stream
from tests.services._finance_factories import seed_txn as _txn


def _trim_line(
    id: int, label: str, allocated_amount: int, spent_amount: int
) -> BudgetLineResponse:
    """A flexible line as the trim planner sees it (label = category name)."""
    return BudgetLineResponse(
        id=id,
        category_id=None,
        category_name=label,
        payee_key=None,
        payee_label=None,
        allocated_amount=allocated_amount,
        spent_amount=spent_amount,
        status="good",
    )


_MONTH = 202607


@contextmanager
def _count_queries(async_engine):
    count = 0

    def _tick(*_args, **_kwargs):
        nonlocal count
        count += 1

    sync_engine = async_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _tick)
    try:
        yield lambda: count
    finally:
        event.remove(sync_engine, "before_cursor_execute", _tick)


class TestGetOrCreateBudget:
    @pytest.mark.asyncio
    async def test_idempotent_across_periods(self, svc: FinanceService) -> None:
        first = await svc.get_or_create_budget(owner_user_id=1, period_month=_MONTH)
        second = await svc.get_or_create_budget(
            owner_user_id=1, period_month=_MONTH + 1
        )
        assert first.id == second.id
        assert first.name == "Monthly"
        assert first.period == "monthly"

    @pytest.mark.asyncio
    async def test_scoped_per_owner(self, svc: FinanceService) -> None:
        mine = await svc.get_or_create_budget(owner_user_id=1, period_month=_MONTH)
        theirs = await svc.get_or_create_budget(owner_user_id=2, period_month=_MONTH)
        assert mine.id != theirs.id


class TestUpsertBudgetLine:
    @pytest.mark.asyncio
    async def test_category_target_create_and_replace(
        self, svc: FinanceService
    ) -> None:
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")

        created = await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=50_000,
        )
        assert created.category_id == groceries.id
        assert created.allocated_amount == 50_000
        assert created.spent_amount == 0
        assert created.status == "good"

        replaced = await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=75_000,
        )
        # Same line, not a duplicate.
        assert replaced.id == created.id
        assert replaced.allocated_amount == 75_000

    @pytest.mark.asyncio
    async def test_payee_target(self, svc: FinanceService) -> None:
        line = await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=None,
            payee_key="starbucks",
            payee_label="Starbucks",
            allocated_amount=6_000,
        )
        assert line.category_id is None
        assert line.payee_key == "starbucks"
        assert line.payee_label == "Starbucks"

    @pytest.mark.asyncio
    async def test_both_targets_rejected_by_db_check(self, svc: FinanceService) -> None:
        from sqlalchemy.exc import IntegrityError

        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")
        with pytest.raises(IntegrityError):
            await svc.upsert_budget_line(
                owner_user_id=1,
                period_month=_MONTH,
                category_id=groceries.id,
                payee_key="starbucks",
                payee_label="Starbucks",
                allocated_amount=1,
            )


class TestDeleteBudgetLine:
    @pytest.mark.asyncio
    async def test_delete_removes_line(self, svc: FinanceService) -> None:
        line = await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=None,
            payee_key="starbucks",
            payee_label="Starbucks",
            allocated_amount=6_000,
        )
        assert await svc.delete_budget_line(line.id, owner_user_id=1) is True
        assert await svc.delete_budget_line(line.id, owner_user_id=1) is False

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, svc: FinanceService) -> None:
        assert await svc.delete_budget_line(999_999, owner_user_id=1) is False


class TestBudgetSummary:
    @pytest.mark.asyncio
    async def test_category_and_payee_spend_math(self, svc: FinanceService) -> None:
        checking = await _account(svc)
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")

        # $120 of groceries this month.
        await _txn(svc, checking.id, -6_000, date(2026, 7, 3), category_id=groceries.id)
        await _txn(
            svc, checking.id, -6_000, date(2026, 7, 10), category_id=groceries.id
        )
        # $18 at Starbucks this month.
        await _txn(svc, checking.id, -1_800, date(2026, 7, 5), name="Starbucks")
        # Outside the period - must not count.
        await _txn(
            svc, checking.id, -99_999, date(2026, 6, 15), category_id=groceries.id
        )

        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=10_000,
        )
        # The key must be the SAME normalized key ``budget_summary`` tallies
        # transactions under - a caller-chosen casing would silently miss.
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=None,
            payee_key="STARBUCKS",
            payee_label="Starbucks",
            allocated_amount=2_000,
        )

        summary = await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        assert summary.period_month == _MONTH
        flexible = next(b for b in summary.buckets if b.name == "flexible")
        by_category = {
            line.category_id: line for line in flexible.lines if line.category_id
        }
        by_payee = {line.payee_key: line for line in flexible.lines if line.payee_key}
        assert by_category[groceries.id].spent_amount == 12_000
        assert by_category[groceries.id].status == "critical"  # 120% of 100
        assert by_payee["STARBUCKS"].spent_amount == 1_800
        assert by_payee["STARBUCKS"].status == "warn"  # 90% of 20

    @pytest.mark.asyncio
    async def test_recurring_streams_are_context_not_limits(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Fixed/Non-monthly show detected commitments for CONTEXT - never
        a spend-vs-allocation "critical" the way Flexible lines do, even
        when this period's actual charge equals (or exceeds) the typical
        amount. A bill isn't over budget on itself."""
        checking = await _account(svc)
        rent = await seed_stream(
            svc,
            name="Rent",
            expected_amount=185_000,
            next_expected_date=date(2026, 8, 1),
        )
        txn = await _txn(svc, checking.id, -185_000, date(2026, 7, 1))
        txn.recurring_stream_id = rent.id
        async_db_session.add(txn)
        await async_db_session.flush()

        summary = await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        fixed = next(b for b in summary.buckets if b.name == "fixed")
        assert len(fixed.lines) == 1
        line = fixed.lines[0]
        assert line.allocated_amount == 185_000
        assert line.spent_amount == 185_000
        assert line.status != "critical"

    @pytest.mark.asyncio
    async def test_commitment_flags_when_it_moves_vs_last_month(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc)
        stream = await seed_stream(
            svc,
            name="Streaming Bundle",
            expected_amount=6_100,
            next_expected_date=date(2026, 8, 1),
        )
        prior = await _txn(svc, checking.id, -6_100, date(2026, 6, 15))
        prior.recurring_stream_id = stream.id
        current = await _txn(svc, checking.id, -6_900, date(2026, 7, 15))
        current.recurring_stream_id = stream.id
        async_db_session.add_all([prior, current])
        await async_db_session.flush()

        summary = await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        fixed = next(b for b in summary.buckets if b.name == "fixed")
        line = fixed.lines[0]
        assert line.status == "warn"
        assert line.variance_amount == 800

    @pytest.mark.asyncio
    async def test_commitment_on_schedule_when_stable(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc)
        stream = await seed_stream(
            svc,
            name="Internet",
            expected_amount=8_000,
            next_expected_date=date(2026, 8, 1),
        )
        prior = await _txn(svc, checking.id, -8_000, date(2026, 6, 15))
        prior.recurring_stream_id = stream.id
        current = await _txn(svc, checking.id, -8_000, date(2026, 7, 15))
        current.recurring_stream_id = stream.id
        async_db_session.add_all([prior, current])
        await async_db_session.flush()

        summary = await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        fixed = next(b for b in summary.buckets if b.name == "fixed")
        line = fixed.lines[0]
        assert line.status == "good"
        assert line.variance_amount == 0

    @pytest.mark.asyncio
    async def test_stats_block(self, svc: FinanceService) -> None:
        checking = await _account(svc)
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")
        await _txn(
            svc, checking.id, -12_000, date(2026, 7, 3), category_id=groceries.id
        )
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=10_000,
        )
        await seed_stream(
            svc,
            name="Rent",
            expected_amount=185_000,
            next_expected_date=date(2026, 8, 1),
        )

        summary = await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        stats = summary.stats
        assert stats.flexible_spent == 12_000
        assert stats.flexible_allocated == 10_000
        assert stats.flexible_count == 1
        assert stats.over_budget_count == 1
        assert stats.over_budget_labels == [groceries.name]
        assert stats.on_track_count == 0
        assert stats.fixed_total == 185_000
        assert stats.fixed_count == 1

    @pytest.mark.asyncio
    async def test_no_n_plus_1_as_line_count_grows(
        self, svc: FinanceService, async_engine
    ) -> None:
        """Query count must not grow with the number of budget lines - the
        whole point of tallying spend in one fetch instead of per line."""
        categories = [
            await svc.get_or_create_category_from_hint(f"Test:Cat{i}")
            for i in range(10)
        ]
        # Warm up: create the budget row itself so both counted calls see
        # an already-existing budget (an idempotency INSERT would otherwise
        # only fire on whichever call happens to run first).
        await svc.budget_summary(owner_user_id=1, period_month=_MONTH)

        for cat in categories[:2]:
            await svc.upsert_budget_line(
                owner_user_id=1,
                period_month=_MONTH,
                category_id=cat.id,
                payee_key=None,
                payee_label=None,
                allocated_amount=1_000,
            )
        # Second warm-up, same reason: the first read of a month with no
        # lines of its own seeds it from the last one that had them, and
        # that one-off copy would otherwise land inside the first count.
        await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        with _count_queries(async_engine) as count_at_two:
            await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        queries_at_two = count_at_two()

        for cat in categories[2:]:
            await svc.upsert_budget_line(
                owner_user_id=1,
                period_month=_MONTH,
                category_id=cat.id,
                payee_key=None,
                payee_label=None,
                allocated_amount=1_000,
            )
        with _count_queries(async_engine) as count_at_ten:
            await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        queries_at_ten = count_at_ten()

        assert queries_at_ten == queries_at_two


class TestAccountScoping:
    """``account_ids`` narrows income, bills, and budget spend to the
    selected accounts - the same scope Overview/Projected/Bills & Income
    already respect. Without it the Budget tab's numbers include money
    from accounts the user explicitly excluded from the filter."""

    @pytest.mark.asyncio
    async def test_income_and_spend_are_scoped_to_selected_accounts(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc, "Checking")
        savings = await _account(svc, "Savings")
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=checking.id,
        )
        await seed_stream(
            svc,
            name="Side income",
            direction="inflow",
            expected_amount=100_000,
            next_expected_date=date(2026, 8, 15),
            account_id=savings.id,
        )
        groceries = await _category(async_db_session, "Groceries")
        await _txn(
            svc, checking.id, -20_000, date(2026, 7, 5), category_id=groceries.id
        )
        await _txn(svc, savings.id, -5_000, date(2026, 7, 6), category_id=groceries.id)
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )

        summary = await svc.budget_summary(
            owner_user_id=1, period_month=_MONTH, account_ids=[checking.id]
        )
        stats = summary.stats
        flexible = next(b for b in summary.buckets if b.name == "flexible")

        assert stats.income_total == 500_000
        assert stats.income_count == 1
        assert flexible.lines[0].spent_amount == 20_000

    @pytest.mark.asyncio
    async def test_no_filter_counts_every_account(self, svc: FinanceService) -> None:
        checking = await _account(svc, "Checking")
        savings = await _account(svc, "Savings")
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=checking.id,
        )
        await seed_stream(
            svc,
            name="Side income",
            direction="inflow",
            expected_amount=100_000,
            next_expected_date=date(2026, 8, 15),
            account_id=savings.id,
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.income_total == 600_000
        assert stats.income_count == 2


class TestParseBudgetGoal:
    @pytest.mark.asyncio
    async def test_matches_payee_with_default_fifty_percent(
        self, svc: FinanceService
    ) -> None:
        checking = await _account(svc)
        for day in (1, 8, 15, 22):
            await _txn(
                svc, checking.id, -600, date(2026, 7, day), name="Starbucks Store 123"
            )

        result = await svc.parse_budget_goal(
            owner_user_id=1, text="I wanna cut back on Starbucks"
        )
        assert result.matched is True
        assert result.target_type == "payee"
        assert result.payee_label == "Starbucks Store 123"
        assert result.label == "Starbucks Store 123"
        assert result.fraction == 0.5
        # Copy is the frontend's job now - the service returns data only.
        assert not hasattr(result, "message")
        # $24 over ~90 days -> ~$8/mo baseline, 50% default -> ~$4 limit.
        assert result.baseline_monthly == 800
        assert result.suggested_limit == 400

    @pytest.mark.asyncio
    async def test_explicit_percentage_in_text(self, svc: FinanceService) -> None:
        checking = await _account(svc)
        for day in (1, 8, 15, 22):
            await _txn(svc, checking.id, -1_000, date(2026, 7, day), name="Starbucks")

        result = await svc.parse_budget_goal(
            owner_user_id=1, text="cut Starbucks to 30%"
        )
        assert result.matched is True
        assert result.fraction == 0.30
        assert result.suggested_limit == round(result.baseline_monthly * 0.30)

    @pytest.mark.asyncio
    async def test_matches_category_when_no_payee_hits(
        self, svc: FinanceService
    ) -> None:
        checking = await _account(svc)
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")
        for day in (1, 8, 15, 22):
            await _txn(
                svc,
                checking.id,
                -4_000,
                date(2026, 7, day),
                category_id=groceries.id,
            )

        result = await svc.parse_budget_goal(
            owner_user_id=1, text="I need to cut back on groceries"
        )
        assert result.matched is True
        assert result.target_type == "category"
        assert result.category_id == groceries.id

    @pytest.mark.asyncio
    async def test_no_match_writes_nothing_and_reports_unmatched(
        self, svc: FinanceService
    ) -> None:
        result = await svc.parse_budget_goal(
            owner_user_id=1, text="something entirely unrelated"
        )
        assert result.matched is False
        assert result.category_id is None
        assert result.payee_key is None
        assert not hasattr(result, "message")


class TestTheMonthOutlook:
    """The header's verdict: income minus bills minus budget, signed.

    "Am I going to come in negative this month" was answerable only by
    opening the Projected tab and reading the line. The three numbers
    that decide it - confirmed income, confirmed bills, budget
    allocations, all monthly-equivalent - now ride the summary the
    Budget tab already fetches, so every edit re-answers it on the spot.
    """

    @pytest.mark.asyncio
    async def test_the_three_totals_and_the_net(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await seed_stream(
            svc,
            name="Rent",
            expected_amount=200_000,
            next_expected_date=date(2026, 8, 1),
            account_id=account.id,
        )
        groceries = await _category(async_db_session, "Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )

        summary = await svc.budget_summary(owner_user_id=1)
        stats = summary.stats

        assert stats.income_total == 500_000
        assert stats.income_count == 1
        assert stats.fixed_total == 200_000
        assert stats.fixed_count == 1
        # 5,000 - 2,000 - 1,000
        assert stats.month_net == 200_000

    @pytest.mark.asyncio
    async def test_a_negative_month_says_so(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=300_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await seed_stream(
            svc,
            name="Rent",
            expected_amount=250_000,
            next_expected_date=date(2026, 8, 1),
            account_id=account.id,
        )
        groceries = await _category(async_db_session, "Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.month_net == -50_000

    @pytest.mark.asyncio
    async def test_a_non_monthly_bill_counts_at_its_monthly_share(
        self, svc: FinanceService
    ) -> None:
        """The Bills cell is captioned "/ month", so a quarterly $300 bill
        belongs there at $100 - its face value is what it costs when it
        lands, not what it costs this month."""
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Water",
            frequency="quarterly",
            expected_amount=30_000,
            next_expected_date=date(2026, 8, 1),
            account_id=account.id,
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.fixed_total == 10_000

    @pytest.mark.asyncio
    async def test_the_cells_reconcile_to_the_verdict(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The invariant behind the header strip: the three figures on
        display must subtract to the fourth. They were computed on
        different footings once - the Bills cell summed face values while
        the verdict subtracted monthly-equivalents - so the strip visibly
        failed its own arithmetic by the size of the non-monthly bills.
        """
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        for name, freq, amount in (
            ("Rent", "monthly", 200_000),
            ("Water", "quarterly", 30_000),
            ("Insurance", "annually", 120_000),
        ):
            await seed_stream(
                svc,
                name=name,
                frequency=freq,
                expected_amount=amount,
                next_expected_date=date(2026, 8, 1),
                account_id=account.id,
            )
        groceries = await _category(async_db_session, "Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert (
            stats.income_total - stats.fixed_total - stats.flexible_allocated
            == stats.month_net
        )

    @pytest.mark.asyncio
    async def test_unconfirmed_rhythms_count_for_nothing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Same commitment gate as the forecast and the rollup: a
        detector guess is not income you can spend."""
        account = await _account(svc)
        stream = await seed_stream(
            svc,
            name="Maybe refunds",
            direction="inflow",
            expected_amount=900_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        stream.is_user_confirmed = False
        stream.source = "derived"
        async_db_session.add(stream)
        await async_db_session.flush()

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.income_total == 0
        assert stats.income_count == 0


class TestTrimPlan:
    """Deterministic cuts that close a negative month.

    The rules, stated once: a line's FLOOR is what it has already spent
    this period (a budget below money already gone is a lie, not a
    plan); cuts distribute proportionally to each line's slack above its
    floor; whatever slack cannot cover is reported as ``residual`` - the
    part of the gap that belongs to bills or income, not budgets. Pure
    function, so the future decision layer can call the same math.
    """

    def test_cuts_are_proportional_to_slack(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        lines = [
            _trim_line(1, "Groceries", 100_000, 40_000),
            _trim_line(2, "Fun", 40_000, 10_000),
        ]
        plan = plan_budget_trims(lines, deficit=45_000)

        assert plan.residual == 0
        by_id = {c.id: c for c in plan.cuts}
        # Slack 60k and 30k -> cuts 30k and 15k.
        assert by_id[1].suggested_amount == 70_000
        assert by_id[2].suggested_amount == 25_000
        assert sum(c.cut for c in plan.cuts) == 45_000

    def test_a_line_never_drops_below_what_is_already_spent(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        lines = [_trim_line(1, "Groceries", 100_000, 95_000)]
        plan = plan_budget_trims(lines, deficit=50_000)

        assert plan.cuts[0].suggested_amount == 95_000
        assert plan.residual == 45_000

    def test_an_exhausted_line_is_left_out(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        lines = [
            _trim_line(1, "Overrun", 30_000, 30_000),
            _trim_line(2, "Fun", 40_000, 0),
        ]
        plan = plan_budget_trims(lines, deficit=10_000)

        assert [c.id for c in plan.cuts] == [2]

    def test_a_positive_month_needs_no_plan(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        plan = plan_budget_trims([_trim_line(1, "A", 10_000, 0)], deficit=0)
        assert plan.cuts == []
        assert plan.residual == 0

    def test_rounding_never_overshoots_the_floor(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        lines = [_trim_line(i, f"L{i}", 10_000, 3_333) for i in (1, 2, 3)]
        plan = plan_budget_trims(lines, deficit=20_001)

        for cut in plan.cuts:
            assert cut.suggested_amount >= 3_333
        assert plan.residual == 0

    @pytest.mark.asyncio
    async def test_a_negative_month_ships_its_trim_plan(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The package: stats say the month is negative, trims say which
        budgets to lower and to what - one payload, so the tab can offer
        the fix beside the verdict and a later AI layer reads the same
        structure."""
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=200_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await seed_stream(
            svc,
            name="Rent",
            expected_amount=150_000,
            next_expected_date=date(2026, 8, 1),
            account_id=account.id,
        )
        groceries = await _category(async_db_session, "Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )

        summary = await svc.budget_summary(owner_user_id=1)

        assert summary.stats.month_net == -50_000
        trims = summary.trims
        assert len(trims) == 1
        assert trims[0].suggested_amount == 50_000
        assert trims[0].cut == 50_000


class TestGoalsJoinTheEquation:
    """GL-04 (tracker #939): active goals' monthly need rides the stats
    strip and month_net subtracts it - one arithmetic statement, checkable
    by hand: income - bills - budgets - goals = net."""

    async def _income_and_budget(self, svc: FinanceService) -> None:
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )

    @pytest.mark.asyncio
    async def test_active_goals_subtract_from_the_month(
        self, svc: FinanceService
    ) -> None:
        await self._income_and_budget(svc)
        await svc.create_virtual_goal(
            owner_user_id=1,
            name="Vacation",
            target_amount=300_000,
            monthly_contribution=25_000,
        )
        await svc.create_virtual_goal(
            owner_user_id=1,
            name="Roof",
            target_amount=1_200_000,
            monthly_contribution=50_000,
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.goals_total == 75_000
        assert stats.goals_count == 2
        assert stats.month_net == 500_000 - 75_000

    @pytest.mark.asyncio
    async def test_paused_and_reached_goals_ask_nothing(
        self, svc: FinanceService
    ) -> None:
        await self._income_and_budget(svc)
        paused = await svc.create_virtual_goal(
            owner_user_id=1,
            name="Paused",
            target_amount=100_000,
            monthly_contribution=10_000,
        )
        await svc.set_goal_status(paused.id, "paused", owner_user_id=1)
        full = await svc.create_virtual_goal(
            owner_user_id=1,
            name="Full",
            target_amount=50_000,
            monthly_contribution=10_000,
        )
        await svc.contribute_to_goal(
            full.id, amount=50_000, owner_user_id=1, when=date(2026, 8, 1)
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.goals_total == 0
        assert stats.goals_count == 0
        assert stats.month_net == 500_000

    @pytest.mark.asyncio
    async def test_the_equation_still_balances_by_hand(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await self._income_and_budget(svc)
        account_id = (await svc.list_accounts(owner_user_id=1))[0][0].id
        await seed_stream(
            svc,
            name="Rent",
            expected_amount=200_000,
            next_expected_date=date(2026, 8, 1),
            account_id=account_id,
        )
        groceries = await _category(async_db_session, "Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )
        await svc.create_virtual_goal(
            owner_user_id=1,
            name="Vacation",
            target_amount=300_000,
            monthly_contribution=25_000,
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert (
            stats.income_total
            - stats.fixed_total
            - stats.flexible_allocated
            - stats.goals_total
            == stats.month_net
        )
        assert stats.month_net == 500_000 - 200_000 - 100_000 - 25_000


class TestGoalPauseTier:
    """GL-06: pause a goal before cutting a budget. Rows carry ``kind``;
    the budget floor/rounding math is untouched; residual stays honest."""

    LINES = [_trim_line(1, "Groceries", 100_000, 40_000)]
    GOALS = [
        GoalAsk(account_id=71, label="Vacation", monthly_need=25_000),
        GoalAsk(account_id=72, label="Roof", monthly_need=50_000),
    ]

    def test_a_small_gap_pauses_before_it_cuts(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        plan = plan_budget_trims(self.LINES, deficit=40_000, goals=self.GOALS)
        kinds = [row.kind for row in plan.cuts]
        # Largest goal first: pausing Roof (+$500) over-covers the $400 gap
        # on its own - no budget is touched.
        assert kinds == ["pause_goal"]
        assert plan.cuts[0].label == "Roof"
        assert plan.cuts[0].recovered == 50_000
        assert plan.residual == 0

    def test_a_large_gap_pauses_everything_then_cuts(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        plan = plan_budget_trims(self.LINES, deficit=100_000, goals=self.GOALS)
        kinds = [row.kind for row in plan.cuts]
        assert kinds == ["pause_goal", "pause_goal", "cut_budget"]
        cut = plan.cuts[-1]
        # 100k - 75k of pauses = 25k left; slack is 60k, floor untouched.
        assert cut.cut == 25_000
        assert cut.suggested_amount == 75_000
        assert plan.residual == 0

    def test_residual_stays_honest_past_all_tiers(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        plan = plan_budget_trims(self.LINES, deficit=200_000, goals=self.GOALS)
        # 75k paused + 60k slack = 135k coverable; the rest is bills/income.
        assert plan.residual == 65_000

    def test_no_goals_is_exactly_the_old_plan(self) -> None:
        from app.services.finance.domains.planning.budgets import plan_budget_trims

        with_arg = plan_budget_trims(self.LINES, deficit=45_000, goals=[])
        without = plan_budget_trims(self.LINES, deficit=45_000)
        assert with_arg == without
        assert all(row.kind == "cut_budget" for row in with_arg.cuts)


class TestMonthOutlook:
    """The header equation computed per FUTURE month, bills at face value
    on their real cadence - so 'fine this month' and 'broke in October'
    can both be seen from the Budget page."""

    async def _base(self, svc: FinanceService) -> int:
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await seed_stream(
            svc,
            name="Rent",
            expected_amount=200_000,
            next_expected_date=date(2026, 8, 1),
            account_id=account.id,
        )
        return account.id

    @pytest.mark.asyncio
    async def test_an_annual_bill_lands_in_its_month_at_face_value(
        self, svc: FinanceService
    ) -> None:
        account_id = await self._base(svc)
        await seed_stream(
            svc,
            name="Geico",
            frequency="annually",
            expected_amount=250_000,
            next_expected_date=date(2026, 10, 12),
            account_id=account_id,
        )

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=4, today=date(2026, 8, 10)
        )

        assert [entry.period_month for entry in outlook] == [
            202608,
            202609,
            202610,
            202611,
        ]
        september, october = outlook[1], outlook[2]
        assert september.bills_due == 200_000  # just rent
        assert october.bills_due == 450_000  # rent + the whole Geico
        assert september.month_net == 300_000
        assert october.month_net == 50_000
        assert october.month_net < september.month_net

    @pytest.mark.asyncio
    async def test_muted_and_paused_stay_out(self, svc: FinanceService) -> None:
        account_id = await self._base(svc)
        eleanor = await seed_stream(
            svc,
            name="Eleanor",
            expected_amount=220_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account_id,
        )
        await svc.pause_recurring(eleanor.id, until=PAUSE_INDEFINITE, owner_user_id=1)

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=3, today=date(2026, 8, 10)
        )
        assert all(entry.bills_due == 200_000 for entry in outlook[1:])

    @pytest.mark.asyncio
    async def test_goals_and_budgets_ask_every_month(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        await self._base(svc)
        groceries = await _category(async_db_session, "Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            # The month the outlook is asked about, not whichever month
            # the suite runs in: allocations are keyed by period.
            period_month=202608,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )
        await svc.create_virtual_goal(
            owner_user_id=1,
            name="Vacation",
            target_amount=300_000,
            monthly_contribution=25_000,
        )

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=3, today=date(2026, 8, 10)
        )
        for entry in outlook[1:]:
            assert entry.budgets == 100_000
            assert entry.goals == 25_000
            assert entry.month_net == 500_000 - 200_000 - 100_000 - 25_000

    @pytest.mark.asyncio
    async def test_the_outlook_honours_the_account_filter(
        self, svc: FinanceService
    ) -> None:
        """Same scoping rule as the header it pages: narrowed to one
        account, only that account's streams count."""
        checking_id = await self._base(svc)
        savings = await _account(svc, name="Savings")
        await seed_stream(
            svc,
            name="Side income",
            direction="inflow",
            expected_amount=100_000,
            next_expected_date=date(2026, 9, 10),
            account_id=savings.id,
        )

        everything = await svc.budget_month_outlook(
            owner_user_id=1, months=3, today=date(2026, 8, 10)
        )
        just_checking = await svc.budget_month_outlook(
            owner_user_id=1,
            months=3,
            today=date(2026, 8, 10),
            account_ids=[checking_id],
        )
        assert everything[1].income_due == 600_000
        assert just_checking[1].income_due == 500_000
        assert just_checking[1].bills_due == 200_000

    @pytest.mark.asyncio
    async def test_the_outlook_carries_the_running_balance(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Rate without level lies: +$3,000/mo of net means nothing if the
        account holds $500 and a big bill lands first. Each month carries
        where cash STARTS and ENDS, compounding from today's real balance
        of the selected accounts."""
        account_id = await self._base(svc)
        account = await svc.get_account(account_id, owner_user_id=1)
        account.current_balance = 50_000  # $500 in the bank today
        account.balance_as_of = datetime(2026, 8, 10)
        async_db_session.add(account)
        await async_db_session.flush()

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=3, today=date(2026, 8, 10)
        )

        first, second = outlook[0], outlook[1]
        assert first.start_balance == 50_000
        assert first.end_balance == 50_000 + first.month_net
        assert second.start_balance == first.end_balance
        assert second.end_balance == second.start_balance + second.month_net

    @pytest.mark.asyncio
    async def test_an_overdue_bill_still_counts_this_month(
        self, svc: FinanceService
    ) -> None:
        """Money late is money owed. The outlook used to step straight
        past every missed occurrence, so a month reading $2,000 of bills
        quietly excluded the $1,000 sitting overdue in the bills table -
        the two pages disagreed about the same month."""
        account_id = await self._base(svc)
        await seed_stream(
            svc,
            name="Water",
            frequency="once",
            expected_amount=9_000,
            next_expected_date=date(2026, 7, 20),
            account_id=account_id,
        )
        await seed_stream(
            svc,
            name="Internet",
            expected_amount=8_000,
            next_expected_date=date(2026, 8, 4),
            account_id=account_id,
        )

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=3, today=date(2026, 8, 10)
        )

        # Rent (Aug 1, missed) + Internet (Aug 4, missed) + the one-time
        # Water bill from July: all still owed, all in this month.
        assert outlook[0].bills_due == 200_000 + 8_000 + 9_000

    @pytest.mark.asyncio
    async def test_a_hand_entered_bill_survives_an_account_filter(
        self, svc: FinanceService
    ) -> None:
        """A bill typed in by hand belongs to no account, so narrowing to
        an account says nothing about it - the rule the forecast and
        AccountFilter.allows both follow. The outlook dropped them, which
        is why the same bill showed on the projection and vanished from
        the month strip."""
        checking_id = await self._base(svc)
        await seed_stream(
            svc,
            name="Property tax",
            expected_amount=45_000,
            next_expected_date=date(2026, 9, 5),
            account_id=None,
        )

        just_checking = await svc.budget_month_outlook(
            owner_user_id=1,
            months=3,
            today=date(2026, 8, 10),
            account_ids=[checking_id],
        )

        assert just_checking[1].bills_due == 200_000 + 45_000


class TestStatDetails:
    """Per-row backup for the header cells: what the popup shows when a
    cell is clicked. Income and Bills mirror the cells' own math
    (commitment gate, monthly-equivalent factors) row for row; the
    everything-else rows are the run-rate bucket grouped by category, so
    the user can see WHICH spending no plan covers."""

    @pytest.mark.asyncio
    async def test_income_and_bills_rows_mirror_the_cells(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await seed_stream(
            svc,
            name="Mortgage",
            expected_amount=220_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await seed_stream(
            svc,
            name="Car insurance",
            frequency="annually",
            expected_amount=120_000,
            next_expected_date=date(2027, 1, 1),
            account_id=account.id,
        )
        muted = await seed_stream(
            svc,
            name="Old gym",
            expected_amount=5_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await svc.mute_recurring(muted.id, owner_user_id=1)

        details = await svc.budget_stat_details(
            owner_user_id=1, today=date(2026, 8, 10)
        )

        assert [(r.label, r.value) for r in details.income] == [("Paycheck", 500_000)]
        # Monthly-equivalent, biggest first; the annual bill names its
        # real cadence so $100/mo is not mistaken for the face value.
        bills = details.bills
        assert [(r.label, r.value) for r in bills] == [
            ("Mortgage", 220_000),
            ("Car insurance", 10_000),
        ]
        assert bills[1].frequency == "annually"
        assert bills[1].per_period_amount == 120_000
        # The popup's sum IS the cell's figure.
        summary = await svc.budget_summary(owner_user_id=1)
        assert sum(r.value for r in bills) == summary.stats.fixed_total

    @pytest.mark.asyncio
    async def test_everything_else_rows_group_the_bucket(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        for month in (5, 6, 7):
            await svc.create_transaction(
                account_id=account.id,
                amount=-30_000,
                txn_date=date(2026, month, 12),
                owner_user_id=1,
                name="Dentist",
            )
        await svc.create_transaction(
            account_id=account.id,
            amount=-9_000,
            txn_date=date(2026, 7, 2),
            owner_user_id=1,
            name="Cash",
        )

        details = await svc.budget_stat_details(
            owner_user_id=1, today=date(2026, 8, 10)
        )

        rows = details.everything_else
        assert [(r.label, r.value) for r in rows] == [("Uncategorized", 33_000)]
        assert rows[0].transaction_count == 4
        # The rows sum to the cell's rate, always.
        rate = await svc.uncovered_spending_rate(
            owner_user_id=1, today=date(2026, 8, 10)
        )
        assert sum(r.value for r in rows) == rate
        assert details.window_start == date(2026, 5, 1)
        assert details.window_end == date(2026, 8, 1)


class TestEverythingElse:
    """The sixth term: observed spending no bill and no limit covers.

    The equation used to assume you only spend what's planned - ~40% of
    real spending was invisible, so every future month read '+' while
    the bank bled. The run-rate is the trailing 3 full months' average
    of uncovered spend, from the same register everything else reads.
    """

    async def _spend(
        self, svc: FinanceService, account_id: int, when: date, cents: int, **kw
    ):
        return await svc.create_transaction(
            account_id=account_id,
            amount=-cents,
            txn_date=when,
            owner_user_id=1,
            **kw,
        )

    @pytest.mark.asyncio
    async def test_reconcile_adjustments_are_not_spending(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A reconciliation adjustment is bookkeeping (making the ledger
        agree with a statement), not money the user chose to spend - it
        must not inflate the observed run rate."""
        account = await _account(svc)
        # Two months of it, so the real spending qualifies as a rate at
        # all (see TestOneOffsDoNotBecomeARate) and the adjustment's
        # absence is what this test is actually measuring.
        await self._spend(
            svc, account.id, date(2026, 6, 12), 30_000, name="Real spending"
        )
        await self._spend(
            svc, account.id, date(2026, 7, 12), 30_000, name="Real spending"
        )
        adjustment = await self._spend(
            svc, account.id, date(2026, 7, 20), 53_115, name="Adjustment"
        )
        adjustment.external_id_source = "reconcile"
        async_db_session.add(adjustment)
        await async_db_session.flush()

        rate = await svc.uncovered_spending_rate(
            owner_user_id=1, today=date(2026, 8, 10)
        )
        assert rate == 20_000  # $600 over 3 months; the adjustment is invisible

    @pytest.mark.asyncio
    async def test_uncovered_spend_becomes_the_run_rate(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        # $600 of unbudgeted, unbilled spending in each of the 3 full
        # months before "today" (Aug 10) - May, June, July.
        for month in (5, 6, 7):
            await self._spend(
                svc, account.id, date(2026, month, 12), 60_000, name="Random stuff"
            )
        # Current-month spending must NOT ride the trailing window.
        await self._spend(svc, account.id, date(2026, 8, 5), 99_900, name="This month")

        rate = await svc.uncovered_spending_rate(
            owner_user_id=1, today=date(2026, 8, 10)
        )
        assert rate == 60_000

    @pytest.mark.asyncio
    async def test_billed_and_budgeted_spend_is_covered(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        groceries = await _category(async_db_session, "Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            # The month the rate is asked about; None would budget
            # whichever month the suite happens to run in.
            period_month=202608,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )
        rent = await seed_stream(
            svc,
            name="Rent",
            expected_amount=200_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        for month in (5, 6, 7):
            budgeted = await self._spend(
                svc, account.id, date(2026, month, 3), 90_000, name="Wegmans"
            )
            budgeted.category_id = groceries.id
            billed = await self._spend(
                svc, account.id, date(2026, month, 1), 200_000, name="Rent"
            )
            billed.recurring_stream_id = rent.id
            uncovered = await self._spend(
                svc, account.id, date(2026, month, 20), 30_000, name="Mystery"
            )
            async_db_session.add(budgeted)
            async_db_session.add(billed)
            async_db_session.add(uncovered)
        await async_db_session.flush()

        rate = await svc.uncovered_spending_rate(
            owner_user_id=1, today=date(2026, 8, 10)
        )
        assert rate == 30_000

    @pytest.mark.asyncio
    async def test_the_equation_and_outlook_subtract_it(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        await seed_stream(
            svc,
            name="Paycheck",
            direction="inflow",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        for month in (5, 6, 7):
            await self._spend(
                svc, account.id, date(2026, month, 12), 60_000, name="Random"
            )

        # Pinned, like every other date in this test: the trailing window
        # this reads is relative to today, so an unpinned call silently
        # changes what it measures at every month boundary.
        stats = (
            await svc.budget_summary(owner_user_id=1, today=date(2026, 8, 10))
        ).stats
        assert stats.everything_else == 60_000
        assert stats.month_net == 500_000 - 60_000

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=2, today=date(2026, 8, 10)
        )
        assert outlook[1].everything_else == 60_000
        assert outlook[1].month_net == 500_000 - 60_000


def _commitment_lines(summary) -> dict[int, BudgetLineResponse]:
    """Fixed/Non-monthly lines by stream id (a commitment line's ``id`` IS
    its stream's - these are streams shown for context, not budget rows)."""
    return {
        line.id: line
        for bucket in summary.buckets
        if bucket.name in ("fixed", "non_monthly")
        for line in bucket.lines
    }


class TestCommitmentLinesCarryTheirMonthlySlice:
    """The Fixed/Non-monthly lines are rendered under a "/mo" heading, so
    the number on each line has to BE a monthly number.

    The aggregate always did this (``commitment_rollup`` multiplies by the
    cadence factor) but the per-line field was the raw face value, so a
    six-month insurance premium read as if it were charged every month -
    and the card's total, being the sum of those lines, inherited it.
    """

    @pytest.mark.asyncio
    async def test_a_semi_annual_premium_reads_as_a_sixth(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        geico = await seed_stream(
            svc,
            name="Geico",
            frequency="semi_annually",
            expected_amount=177_945,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )

        summary = await svc.budget_summary(owner_user_id=1)

        assert _commitment_lines(summary)[geico.id].allocated_amount == 29_658

    @pytest.mark.asyncio
    async def test_a_monthly_bill_is_untouched(self, svc: FinanceService) -> None:
        account = await _account(svc)
        rent = await seed_stream(
            svc,
            name="Rent",
            expected_amount=200_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )

        summary = await svc.budget_summary(owner_user_id=1)

        assert _commitment_lines(summary)[rent.id].allocated_amount == 200_000

    @pytest.mark.asyncio
    async def test_the_lines_sum_to_the_headline_total(
        self, svc: FinanceService
    ) -> None:
        """The card's header is the sum of its lines, and the header strip
        uses the rollup. Two footings for one figure is what made the
        Budget tab disagree with itself."""
        account = await _account(svc)
        for name, frequency, amount in (
            ("Geico", "semi_annually", 177_945),
            ("Garbage", "bimonthly", 12_622),
            ("Rent", "monthly", 200_000),
        ):
            await seed_stream(
                svc,
                name=name,
                frequency=frequency,
                expected_amount=amount,
                next_expected_date=date(2026, 9, 1),
                account_id=account.id,
            )

        summary = await svc.budget_summary(owner_user_id=1)
        commitment_total = sum(
            line.allocated_amount
            for bucket in summary.buckets
            if bucket.name in ("fixed", "non_monthly")
            for line in bucket.lines
        )

        assert commitment_total == summary.stats.fixed_total

    @pytest.mark.asyncio
    async def test_a_one_time_bill_is_not_a_commitment_line(
        self, svc: FinanceService
    ) -> None:
        """A one-off has no monthly slice - its factor is zero, so it would
        render as "$0.00 /mo", which is worse than absent. It already shows
        on the forecast timeline and in the outlook at its real date.
        """
        account = await _account(svc)
        dentist = await seed_stream(
            svc,
            name="Dentist",
            frequency="once",
            expected_amount=230_000,
            next_expected_date=date(2026, 9, 10),
            account_id=account.id,
        )

        summary = await svc.budget_summary(owner_user_id=1)

        assert dentist.id not in _commitment_lines(summary)
        assert summary.stats.fixed_total == 0


def _one_time_lines(summary) -> dict[int, BudgetLineResponse]:
    """One-time lines by stream id, same convention as ``_commitment_lines``."""
    return {
        line.id: line
        for bucket in summary.buckets
        if bucket.name == "one_time"
        for line in bucket.lines
    }


class TestOneTimePlansGetTheirOwnGroup:
    """A one-off stream is a deliberate entry - a dentist visit, a gift -
    not detector noise. Dropping it from Fixed/Non-monthly was right (it
    has no monthly share), but dropping it from the card entirely hid
    plans the user typed in on purpose. It gets its own group: face
    value and a date, never a "/mo"."""

    @staticmethod
    async def _one_off(svc: FinanceService, name: str, amount: int, due: date):
        account = await _account(svc)
        return await seed_stream(
            svc,
            name=name,
            frequency="once",
            expected_amount=amount,
            next_expected_date=due,
            account_id=account.id,
        )

    @pytest.mark.asyncio
    async def test_a_one_time_bill_lands_in_the_one_time_group(
        self, svc: FinanceService
    ) -> None:
        dentist = await self._one_off(svc, "Dentist", 230_000, date(2026, 9, 10))

        summary = await svc.budget_summary(owner_user_id=1)

        line = _one_time_lines(summary)[dentist.id]
        assert line.allocated_amount == 230_000  # face value, not a share
        assert line.due_date == date(2026, 9, 10)
        assert line.payee_label == "Dentist"

    @pytest.mark.asyncio
    async def test_the_group_total_is_face_value_and_stays_out_of_fixed(
        self, svc: FinanceService
    ) -> None:
        """The group sums whole amounts, and none of it leaks into the
        monthly commitment math - a one-off is not a rate at any weight."""
        await self._one_off(svc, "Dentist", 230_000, date(2026, 9, 10))
        await self._one_off(svc, "Mimi", 100_000, date(2026, 9, 20))
        await self._one_off(svc, "School Clothes", 24_000, date(2026, 8, 30))

        summary = await svc.budget_summary(owner_user_id=1)

        one_time = next(b for b in summary.buckets if b.name == "one_time")
        assert one_time.total_allocated == 354_000
        assert summary.stats.fixed_total == 0

    @pytest.mark.asyncio
    async def test_the_group_lists_soonest_first(self, svc: FinanceService) -> None:
        await self._one_off(svc, "Dentist", 230_000, date(2026, 9, 10))
        await self._one_off(svc, "School Clothes", 24_000, date(2026, 8, 30))

        summary = await svc.budget_summary(owner_user_id=1)

        one_time = next(b for b in summary.buckets if b.name == "one_time")
        assert [line.payee_label for line in one_time.lines] == [
            "School Clothes",
            "Dentist",
        ]

    @pytest.mark.asyncio
    async def test_a_muted_one_off_stays_hidden(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        dentist = await self._one_off(svc, "Dentist", 230_000, date(2026, 9, 10))
        dentist.is_muted = True
        async_db_session.add(dentist)
        await async_db_session.commit()

        summary = await svc.budget_summary(owner_user_id=1)

        assert dentist.id not in _one_time_lines(summary)


class TestTheSummaryClockIsInjectable:
    """budget_summary was the one read API stuck on the real clock - which
    is exactly where the suite's time bombs lived: a pause that expires
    against date.today() flips assertions on a calendar day, and tests
    could only dodge it with relative dates. The clock is a parameter
    now; this pins both sides of a pause boundary on fixed days."""

    @pytest.mark.asyncio
    async def test_a_pause_boundary_reads_the_injected_clock(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        stream = await seed_stream(
            svc,
            name="Rent",
            expected_amount=200_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await svc.pause_recurring(stream.id, until=date(2026, 11, 1), owner_user_id=1)

        paused = await svc.budget_summary(owner_user_id=1, today=date(2026, 10, 31))
        resumed = await svc.budget_summary(owner_user_id=1, today=date(2026, 11, 1))

        assert paused.stats.fixed_total == 0
        assert resumed.stats.fixed_total == 200_000


class TestOneOffsDoNotBecomeARate:
    """Averaging the whole 3-month window asserts that all of it recurs:
    a single car repair then reads as a monthly habit for three months.

    A rate must be earned twice. History decides whether a habit exists
    at all (active in at least half the months of the category's record,
    12-month lookback); the window then sizes the rate, with each month
    capped at 3x the median month and the excess split off. Whatever
    fails either bar is still real money - it reports at face value as
    a one-off instead of being amortized.
    """

    @staticmethod
    def _month_in_window(months_back: int, day: int = 4) -> date:
        """A day inside one of the three FULL months before this one -
        the window the uncovered-spend rate measures."""
        first = date.today().replace(day=1)
        month_index = first.month - 1 - months_back
        year = first.year + month_index // 12
        return date(year, month_index % 12 + 1, day)

    async def _uncovered(
        self,
        svc: FinanceService,
        session: AsyncSession,
        category: str,
        rows: list[tuple[date, int]],
    ) -> None:
        account = await _account(svc)
        cat = await _category(session, category)
        for when, amount in rows:
            await _txn(svc, account.id, amount, when, category_id=cat.id)

    @pytest.mark.asyncio
    async def test_a_repeated_category_still_amortizes(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Two steady months of a two-month-old category: the habit bar
        judges a category against its OWN record, so a young category
        amortizes without needing a year of history first."""
        await self._uncovered(
            svc,
            async_db_session,
            "Home:Lawn & Garden",
            [
                (self._month_in_window(1), -30_000),
                (self._month_in_window(2), -30_000),
            ],
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.everything_else == 20_000  # $600 over three months
        assert stats.one_off_total == 0

    @pytest.mark.asyncio
    async def test_a_single_month_category_is_a_one_off_not_a_rate(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """One active month means a median of zero, so nothing survives
        the cap into the rate - but dropping it from the rate must not
        hide it: the whole amount moves to the one-off side intact."""
        await self._uncovered(
            svc,
            async_db_session,
            "Auto & Transport:Service & Parts",
            [(self._month_in_window(2, day=25), -173_467)],
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.everything_else == 0
        assert stats.one_off_total == 173_467

    @pytest.mark.asyncio
    async def test_three_charges_in_one_month_are_still_one_month(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The unit of evidence is the MONTH, not the transaction:
        three charges on consecutive days are one active month, and one
        active month is a one-off however many rows it took."""
        await self._uncovered(
            svc,
            async_db_session,
            "Shopping:Hobbies",
            [
                (self._month_in_window(2, day=3), -10_000),
                (self._month_in_window(2, day=4), -10_000),
                (self._month_in_window(2, day=5), -10_000),
            ],
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.everything_else == 0
        assert stats.one_off_total == 30_000

    @pytest.mark.asyncio
    async def test_the_breakdown_lists_one_offs_separately(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The popup renders only the rate rows, so those must sum to
        the cell they explain - and the one-offs must stay classified
        separately in the payload, because that split is exactly what
        keeps the rate honest."""
        await self._uncovered(
            svc,
            async_db_session,
            "Home:Lawn & Garden",
            [
                (self._month_in_window(1), -30_000),
                (self._month_in_window(2), -30_000),
            ],
        )
        await self._uncovered(
            svc,
            async_db_session,
            "Auto & Transport:Service & Parts",
            [(self._month_in_window(2, day=25), -173_467)],
        )

        details = await svc.budget_stat_details(owner_user_id=1)
        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert sum(r.value for r in details.everything_else) == stats.everything_else
        one_offs = {r.label: r.value for r in details.one_offs}
        assert one_offs["Auto & Transport:Service & Parts"] == 173_467
        assert "Home:Lawn & Garden" not in one_offs

    @pytest.mark.asyncio
    async def test_a_sparse_history_disqualifies_the_rate_entirely(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The 3-month window has no memory: dental work that clustered
        into the window's months read as a habit even though the category
        had been quiet for most of a year. A rate needs a habit, and a
        habit means active in at least half the months since the category
        was first seen (12-month lookback) - the window only sizes it.
        """
        account = await _account(svc)
        cat = await _category(async_db_session, "Health & Fitness:Dentist")
        # A checkup 11 months ago, then the root-canal saga inside the
        # window: 3 active months out of 11 is not a habit.
        await _txn(
            svc, account.id, -15_000, self._month_in_window(11), category_id=cat.id
        )
        for months_back, amount in ((3, -21_000), (2, -187_000), (1, -11_626)):
            await _txn(
                svc,
                account.id,
                amount,
                self._month_in_window(months_back),
                category_id=cat.id,
            )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.everything_else == 0
        # Only the window's spending is the card's population - the old
        # checkup is history, evidence but not a bill.
        assert stats.one_off_total == 219_626

    @pytest.mark.asyncio
    async def test_an_old_category_is_judged_on_the_full_year(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The span is the category's RECORD, not its recent filtered
        activity: toys bought since 2020 with a quiet year and two buys
        in the window is still a sparse category, even though the last
        twelve months' uncovered rows all fall inside the window."""
        account = await _account(svc)
        cat = await _category(async_db_session, "Kids:Toys")
        old = date.today().replace(day=15)
        for _ in range(20):
            old = (old.replace(day=1) - timedelta(days=1)).replace(day=15)
        await _txn(svc, account.id, -15_000, old, category_id=cat.id)
        for months_back in (1, 2):
            await _txn(
                svc,
                account.id,
                -30_000,
                self._month_in_window(months_back),
                category_id=cat.id,
            )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.everything_else == 0
        assert stats.one_off_total == 60_000

    @pytest.mark.asyncio
    async def test_a_spike_beside_a_small_month_is_not_averaged(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The case that survived the first rule: a $1,734 repair in one
        month and a $36 charge in another are two months of evidence, so
        the category qualified as a rate and both got averaged into
        $590/mo. The typical month is $36; the repair is a one-off.
        """
        await self._uncovered(
            svc,
            async_db_session,
            "Auto & Transport:Service & Parts",
            [
                (self._month_in_window(2, day=25), -173_467),
                (self._month_in_window(1, day=20), -3_605),
            ],
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        # Median month is $36.05, so the spike contributes at most 3x that.
        assert stats.everything_else == 4_807
        assert stats.one_off_total == 162_652

    @pytest.mark.asyncio
    async def test_steady_months_are_left_alone(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The cap must only bite on outliers: three ordinary months of
        groceries-shaped spending stay a plain average."""
        await self._uncovered(
            svc,
            async_db_session,
            "Home:Lawn & Garden",
            [
                (self._month_in_window(1), -30_000),
                (self._month_in_window(2), -33_000),
                (self._month_in_window(3), -27_000),
            ],
        )

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.everything_else == 30_000
        assert stats.one_off_total == 0
