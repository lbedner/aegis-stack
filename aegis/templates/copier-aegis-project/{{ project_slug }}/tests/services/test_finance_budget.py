"""Tests for the Budget tab's service layer.

Covers ``get_or_create_budget`` idempotency, ``upsert_budget_line`` for both
target shapes, ``budget_summary``'s spend math (category and payee level,
plus the Fixed/Non-monthly recurring split), ``parse_budget_goal``'s
deterministic matching, and a concrete N+1 check on ``budget_summary``.
"""

from contextlib import contextmanager
from datetime import date, datetime

import pytest
from sqlalchemy import event
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.constants import PAUSE_INDEFINITE
from app.services.finance.finance_service import FinanceService

_MONTH = 202607


async def _account(svc, name="Checking", owner_user_id=1):
    return await svc.create_manual_account(
        name=name,
        account_type="checking",
        classification="asset",
        owner_user_id=owner_user_id,
    )


async def _txn(
    svc, account_id, amount, day, *, name=None, category_id=None, owner_user_id=1
):
    return await svc.create_transaction(
        account_id=account_id,
        amount=amount,
        txn_date=day,
        owner_user_id=owner_user_id,
        name=name,
        category_id=category_id,
    )


async def _category(db, name: str):
    from app.services.finance.models import FinanceCategory

    row = FinanceCategory(
        owner_user_id=1,
        name=name,
        slug=name.lower().replace(" ", "-").replace(":", "-"),
        classification="expense",
    )
    db.add(row)
    await db.flush()
    return row


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
    async def test_idempotent_across_periods(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        first = await svc.get_or_create_budget(owner_user_id=1, period_month=_MONTH)
        second = await svc.get_or_create_budget(
            owner_user_id=1, period_month=_MONTH + 1
        )
        assert first.id == second.id
        assert first.name == "Monthly"
        assert first.period == "monthly"

    @pytest.mark.asyncio
    async def test_scoped_per_owner(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        mine = await svc.get_or_create_budget(owner_user_id=1, period_month=_MONTH)
        theirs = await svc.get_or_create_budget(owner_user_id=2, period_month=_MONTH)
        assert mine.id != theirs.id


class TestUpsertBudgetLine:
    @pytest.mark.asyncio
    async def test_category_target_create_and_replace(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")

        created = await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=50_000,
        )
        assert created["category_id"] == groceries.id
        assert created["allocated_amount"] == 50_000
        assert created["spent_amount"] == 0
        assert created["status"] == "good"

        replaced = await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=75_000,
        )
        # Same line, not a duplicate.
        assert replaced["id"] == created["id"]
        assert replaced["allocated_amount"] == 75_000

    @pytest.mark.asyncio
    async def test_payee_target(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        line = await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=None,
            payee_key="starbucks",
            payee_label="Starbucks",
            allocated_amount=6_000,
        )
        assert line["category_id"] is None
        assert line["payee_key"] == "starbucks"
        assert line["payee_label"] == "Starbucks"

    @pytest.mark.asyncio
    async def test_both_targets_rejected_by_db_check(
        self, async_db_session: AsyncSession
    ) -> None:
        from sqlalchemy.exc import IntegrityError

        svc = FinanceService(async_db_session)
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
    async def test_delete_removes_line(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        line = await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=_MONTH,
            category_id=None,
            payee_key="starbucks",
            payee_label="Starbucks",
            allocated_amount=6_000,
        )
        assert await svc.delete_budget_line(line["id"], owner_user_id=1) is True
        assert await svc.delete_budget_line(line["id"], owner_user_id=1) is False

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        assert await svc.delete_budget_line(999_999, owner_user_id=1) is False


class TestBudgetSummary:
    @pytest.mark.asyncio
    async def test_category_and_payee_spend_math(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        assert summary["period_month"] == _MONTH
        flexible = next(b for b in summary["buckets"] if b["name"] == "flexible")
        by_category = {
            line["category_id"]: line
            for line in flexible["lines"]
            if line["category_id"]
        }
        by_payee = {
            line["payee_key"]: line for line in flexible["lines"] if line["payee_key"]
        }
        assert by_category[groceries.id]["spent_amount"] == 12_000
        assert by_category[groceries.id]["status"] == "critical"  # 120% of 100
        assert by_payee["STARBUCKS"]["spent_amount"] == 1_800
        assert by_payee["STARBUCKS"]["status"] == "warn"  # 90% of 20

    @pytest.mark.asyncio
    async def test_recurring_streams_are_context_not_limits(
        self, async_db_session: AsyncSession
    ) -> None:
        """Fixed/Non-monthly show detected commitments for CONTEXT - never
        a spend-vs-allocation "critical" the way Flexible lines do, even
        when this period's actual charge equals (or exceeds) the typical
        amount. A bill isn't over budget on itself."""
        svc = FinanceService(async_db_session)
        checking = await _account(svc)
        rent = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=185_000,
            next_expected_date=date(2026, 8, 1),
        )
        txn = await _txn(svc, checking.id, -185_000, date(2026, 7, 1))
        txn.recurring_stream_id = rent.id
        async_db_session.add(txn)
        await async_db_session.flush()

        summary = await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        fixed = next(b for b in summary["buckets"] if b["name"] == "fixed")
        assert len(fixed["lines"]) == 1
        line = fixed["lines"][0]
        assert line["allocated_amount"] == 185_000
        assert line["spent_amount"] == 185_000
        assert line["status"] != "critical"

    @pytest.mark.asyncio
    async def test_commitment_flags_when_it_moves_vs_last_month(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await _account(svc)
        stream = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Streaming Bundle",
            direction="outflow",
            frequency="monthly",
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
        fixed = next(b for b in summary["buckets"] if b["name"] == "fixed")
        line = fixed["lines"][0]
        assert line["status"] == "warn"
        assert line["variance_amount"] == 800

    @pytest.mark.asyncio
    async def test_commitment_on_schedule_when_stable(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await _account(svc)
        stream = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Internet",
            direction="outflow",
            frequency="monthly",
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
        fixed = next(b for b in summary["buckets"] if b["name"] == "fixed")
        line = fixed["lines"][0]
        assert line["status"] == "good"
        assert line["variance_amount"] == 0

    @pytest.mark.asyncio
    async def test_stats_block(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
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
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=185_000,
            next_expected_date=date(2026, 8, 1),
        )

        summary = await svc.budget_summary(owner_user_id=1, period_month=_MONTH)
        stats = summary["stats"]
        assert stats["flexible_spent"] == 12_000
        assert stats["flexible_allocated"] == 10_000
        assert stats["flexible_count"] == 1
        assert stats["over_budget_count"] == 1
        assert stats["over_budget_labels"] == [groceries.name]
        assert stats["on_track_count"] == 0
        assert stats["fixed_total"] == 185_000
        assert stats["fixed_count"] == 1

    @pytest.mark.asyncio
    async def test_no_n_plus_1_as_line_count_grows(
        self, async_db_session: AsyncSession, async_engine
    ) -> None:
        """Query count must not grow with the number of budget lines - the
        whole point of tallying spend in one fetch instead of per line."""
        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await _account(svc, "Checking")
        savings = await _account(svc, "Savings")
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=checking.id,
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Side income",
            direction="inflow",
            frequency="monthly",
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
        stats = summary["stats"]
        flexible = next(b for b in summary["buckets"] if b["name"] == "flexible")

        assert stats["income_total"] == 500_000
        assert stats["income_count"] == 1
        assert flexible["lines"][0]["spent_amount"] == 20_000

    @pytest.mark.asyncio
    async def test_no_filter_counts_every_account(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await _account(svc, "Checking")
        savings = await _account(svc, "Savings")
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=checking.id,
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Side income",
            direction="inflow",
            frequency="monthly",
            expected_amount=100_000,
            next_expected_date=date(2026, 8, 15),
            account_id=savings.id,
        )

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert stats["income_total"] == 600_000
        assert stats["income_count"] == 2


class TestParseBudgetGoal:
    @pytest.mark.asyncio
    async def test_matches_payee_with_default_fifty_percent(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await _account(svc)
        for day in (1, 8, 15, 22):
            await _txn(
                svc, checking.id, -600, date(2026, 7, day), name="Starbucks Store 123"
            )

        result = await svc.parse_budget_goal(
            owner_user_id=1, text="I wanna cut back on Starbucks"
        )
        assert result["matched"] is True
        assert result["target_type"] == "payee"
        assert result["payee_label"] == "Starbucks Store 123"
        # $24 over ~90 days -> ~$8/mo baseline, 50% default -> ~$4 limit.
        assert result["baseline_monthly"] == 800
        assert result["suggested_limit"] == 400

    @pytest.mark.asyncio
    async def test_explicit_percentage_in_text(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await _account(svc)
        for day in (1, 8, 15, 22):
            await _txn(svc, checking.id, -1_000, date(2026, 7, day), name="Starbucks")

        result = await svc.parse_budget_goal(
            owner_user_id=1, text="cut Starbucks to 30%"
        )
        assert result["matched"] is True
        assert result["suggested_limit"] == round(result["baseline_monthly"] * 0.30)

    @pytest.mark.asyncio
    async def test_matches_category_when_no_payee_hits(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        assert result["matched"] is True
        assert result["target_type"] == "category"
        assert result["category_id"] == groceries.id

    @pytest.mark.asyncio
    async def test_no_match_writes_nothing_and_reports_unmatched(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        result = await svc.parse_budget_goal(
            owner_user_id=1, text="something entirely unrelated"
        )
        assert result["matched"] is False
        assert result["category_id"] is None
        assert result["payee_key"] is None


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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
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
        stats = summary["stats"]

        assert stats["income_total"] == 500_000
        assert stats["income_count"] == 1
        assert stats["fixed_total"] == 200_000
        assert stats["fixed_count"] == 1
        # 5,000 - 2,000 - 1,000
        assert stats["month_net"] == 200_000

    @pytest.mark.asyncio
    async def test_a_negative_month_says_so(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=300_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
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

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert stats["month_net"] == -50_000

    @pytest.mark.asyncio
    async def test_a_non_monthly_bill_counts_at_its_monthly_share(
        self, async_db_session: AsyncSession
    ) -> None:
        """The Bills cell is captioned "/ month", so a quarterly $300 bill
        belongs there at $100 - its face value is what it costs when it
        lands, not what it costs this month."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Water",
            direction="outflow",
            frequency="quarterly",
            expected_amount=30_000,
            next_expected_date=date(2026, 8, 1),
            account_id=account.id,
        )

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert stats["fixed_total"] == 10_000

    @pytest.mark.asyncio
    async def test_the_cells_reconcile_to_the_verdict(
        self, async_db_session: AsyncSession
    ) -> None:
        """The invariant behind the header strip: the three figures on
        display must subtract to the fourth. They were computed on
        different footings once - the Bills cell summed face values while
        the verdict subtracted monthly-equivalents - so the strip visibly
        failed its own arithmetic by the size of the non-monthly bills.
        """
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        for name, freq, amount in (
            ("Rent", "monthly", 200_000),
            ("Water", "quarterly", 30_000),
            ("Insurance", "annually", 120_000),
        ):
            await svc.create_recurring_stream(
                owner_user_id=1,
                name=name,
                direction="outflow",
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

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert (
            stats["income_total"] - stats["fixed_total"] - stats["flexible_allocated"]
            == stats["month_net"]
        )

    @pytest.mark.asyncio
    async def test_unconfirmed_rhythms_count_for_nothing(
        self, async_db_session: AsyncSession
    ) -> None:
        """Same commitment gate as the forecast and the rollup: a
        detector guess is not income you can spend."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Maybe refunds",
            direction="inflow",
            frequency="monthly",
            expected_amount=900_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        stream.is_user_confirmed = False
        stream.source = "derived"
        async_db_session.add(stream)
        await async_db_session.flush()

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert stats["income_total"] == 0
        assert stats["income_count"] == 0


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
        from app.services.finance.finance_service import plan_budget_trims

        lines = [
            {
                "id": 1,
                "label": "Groceries",
                "allocated_amount": 100_000,
                "spent_amount": 40_000,
            },
            {
                "id": 2,
                "label": "Fun",
                "allocated_amount": 40_000,
                "spent_amount": 10_000,
            },
        ]
        plan = plan_budget_trims(lines, deficit=45_000)

        assert plan["residual"] == 0
        by_id = {c["id"]: c for c in plan["cuts"]}
        # Slack 60k and 30k -> cuts 30k and 15k.
        assert by_id[1]["suggested_amount"] == 70_000
        assert by_id[2]["suggested_amount"] == 25_000
        assert sum(c["cut"] for c in plan["cuts"]) == 45_000

    def test_a_line_never_drops_below_what_is_already_spent(self) -> None:
        from app.services.finance.finance_service import plan_budget_trims

        lines = [
            {
                "id": 1,
                "label": "Groceries",
                "allocated_amount": 100_000,
                "spent_amount": 95_000,
            },
        ]
        plan = plan_budget_trims(lines, deficit=50_000)

        assert plan["cuts"][0]["suggested_amount"] == 95_000
        assert plan["residual"] == 45_000

    def test_an_exhausted_line_is_left_out(self) -> None:
        from app.services.finance.finance_service import plan_budget_trims

        lines = [
            {
                "id": 1,
                "label": "Overrun",
                "allocated_amount": 30_000,
                "spent_amount": 30_000,
            },
            {"id": 2, "label": "Fun", "allocated_amount": 40_000, "spent_amount": 0},
        ]
        plan = plan_budget_trims(lines, deficit=10_000)

        assert [c["id"] for c in plan["cuts"]] == [2]

    def test_a_positive_month_needs_no_plan(self) -> None:
        from app.services.finance.finance_service import plan_budget_trims

        plan = plan_budget_trims(
            [{"id": 1, "label": "A", "allocated_amount": 10_000, "spent_amount": 0}],
            deficit=0,
        )
        assert plan["cuts"] == []
        assert plan["residual"] == 0

    def test_rounding_never_overshoots_the_floor(self) -> None:
        from app.services.finance.finance_service import plan_budget_trims

        lines = [
            {
                "id": i,
                "label": f"L{i}",
                "allocated_amount": 10_000,
                "spent_amount": 3_333,
            }
            for i in (1, 2, 3)
        ]
        plan = plan_budget_trims(lines, deficit=20_001)

        for cut in plan["cuts"]:
            assert cut["suggested_amount"] >= 3_333
        assert plan["residual"] == 0

    @pytest.mark.asyncio
    async def test_a_negative_month_ships_its_trim_plan(
        self, async_db_session: AsyncSession
    ) -> None:
        """The package: stats say the month is negative, trims say which
        budgets to lower and to what - one payload, so the tab can offer
        the fix beside the verdict and a later AI layer reads the same
        structure."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=200_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
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

        assert summary["stats"]["month_net"] == -50_000
        trims = summary["trims"]
        assert len(trims) == 1
        assert trims[0]["suggested_amount"] == 50_000
        assert trims[0]["cut"] == 50_000


class TestGoalsJoinTheEquation:
    """GL-04 (tracker #939): active goals' monthly need rides the stats
    strip and month_net subtracts it - one arithmetic statement, checkable
    by hand: income - bills - budgets - goals = net."""

    async def _income_and_budget(self, svc: FinanceService) -> None:
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )

    @pytest.mark.asyncio
    async def test_active_goals_subtract_from_the_month(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert stats["goals_total"] == 75_000
        assert stats["goals_count"] == 2
        assert stats["month_net"] == 500_000 - 75_000

    @pytest.mark.asyncio
    async def test_paused_and_reached_goals_ask_nothing(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert stats["goals_total"] == 0
        assert stats["goals_count"] == 0
        assert stats["month_net"] == 500_000

    @pytest.mark.asyncio
    async def test_the_equation_still_balances_by_hand(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._income_and_budget(svc)
        account_id = (await svc.list_accounts(owner_user_id=1))[0][0].id
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
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

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]

        assert (
            stats["income_total"]
            - stats["fixed_total"]
            - stats["flexible_allocated"]
            - stats["goals_total"]
            == stats["month_net"]
        )
        assert stats["month_net"] == 500_000 - 200_000 - 100_000 - 25_000


class TestGoalPauseTier:
    """GL-06: pause a goal before cutting a budget. Rows carry ``kind``;
    the budget floor/rounding math is untouched; residual stays honest."""

    LINES = [
        {
            "id": 1,
            "label": "Groceries",
            "allocated_amount": 100_000,
            "spent_amount": 40_000,
        },
    ]
    GOALS = [
        {"account_id": 71, "label": "Vacation", "monthly_need": 25_000},
        {"account_id": 72, "label": "Roof", "monthly_need": 50_000},
    ]

    def test_a_small_gap_pauses_before_it_cuts(self) -> None:
        from app.services.finance.finance_service import plan_budget_trims

        plan = plan_budget_trims(self.LINES, deficit=40_000, goals=self.GOALS)
        kinds = [row["kind"] for row in plan["cuts"]]
        # Largest goal first: pausing Roof (+$500) over-covers the $400 gap
        # on its own - no budget is touched.
        assert kinds == ["pause_goal"]
        assert plan["cuts"][0]["label"] == "Roof"
        assert plan["cuts"][0]["recovered"] == 50_000
        assert plan["residual"] == 0

    def test_a_large_gap_pauses_everything_then_cuts(self) -> None:
        from app.services.finance.finance_service import plan_budget_trims

        plan = plan_budget_trims(self.LINES, deficit=100_000, goals=self.GOALS)
        kinds = [row["kind"] for row in plan["cuts"]]
        assert kinds == ["pause_goal", "pause_goal", "cut_budget"]
        cut = plan["cuts"][-1]
        # 100k - 75k of pauses = 25k left; slack is 60k, floor untouched.
        assert cut["cut"] == 25_000
        assert cut["suggested_amount"] == 75_000
        assert plan["residual"] == 0

    def test_residual_stays_honest_past_all_tiers(self) -> None:
        from app.services.finance.finance_service import plan_budget_trims

        plan = plan_budget_trims(self.LINES, deficit=200_000, goals=self.GOALS)
        # 75k paused + 60k slack = 135k coverable; the rest is bills/income.
        assert plan["residual"] == 65_000

    def test_no_goals_is_exactly_the_old_plan(self) -> None:
        from app.services.finance.finance_service import plan_budget_trims

        with_arg = plan_budget_trims(self.LINES, deficit=45_000, goals=[])
        without = plan_budget_trims(self.LINES, deficit=45_000)
        assert with_arg == without
        assert all(row["kind"] == "cut_budget" for row in with_arg["cuts"])


class TestMonthOutlook:
    """The header equation computed per FUTURE month, bills at face value
    on their real cadence - so 'fine this month' and 'broke in October'
    can both be seen from the Budget page."""

    async def _base(self, svc: FinanceService) -> int:
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=200_000,
            next_expected_date=date(2026, 8, 1),
            account_id=account.id,
        )
        return account.id

    @pytest.mark.asyncio
    async def test_an_annual_bill_lands_in_its_month_at_face_value(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account_id = await self._base(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Geico",
            direction="outflow",
            frequency="annually",
            expected_amount=250_000,
            next_expected_date=date(2026, 10, 12),
            account_id=account_id,
        )

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=4, today=date(2026, 8, 10)
        )

        assert [entry["period_month"] for entry in outlook] == [
            202608,
            202609,
            202610,
            202611,
        ]
        september, october = outlook[1], outlook[2]
        assert september["bills_due"] == 200_000  # just rent
        assert october["bills_due"] == 450_000  # rent + the whole Geico
        assert september["month_net"] == 300_000
        assert october["month_net"] == 50_000
        assert october["month_net"] < september["month_net"]

    @pytest.mark.asyncio
    async def test_muted_and_paused_stay_out(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account_id = await self._base(svc)
        eleanor = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Eleanor",
            direction="outflow",
            frequency="monthly",
            expected_amount=220_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account_id,
        )
        await svc.pause_recurring(eleanor.id, until=PAUSE_INDEFINITE, owner_user_id=1)

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=3, today=date(2026, 8, 10)
        )
        assert all(entry["bills_due"] == 200_000 for entry in outlook[1:])

    @pytest.mark.asyncio
    async def test_goals_and_budgets_ask_every_month(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._base(svc)
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

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=3, today=date(2026, 8, 10)
        )
        for entry in outlook[1:]:
            assert entry["budgets"] == 100_000
            assert entry["goals"] == 25_000
            assert entry["month_net"] == 500_000 - 200_000 - 100_000 - 25_000

    @pytest.mark.asyncio
    async def test_the_outlook_honours_the_account_filter(
        self, async_db_session: AsyncSession
    ) -> None:
        """Same scoping rule as the header it pages: narrowed to one
        account, only that account's streams count."""
        svc = FinanceService(async_db_session)
        checking_id = await self._base(svc)
        savings = await _account(svc, name="Savings")
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Side income",
            direction="inflow",
            frequency="monthly",
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
        assert everything[1]["income_due"] == 600_000
        assert just_checking[1]["income_due"] == 500_000
        assert just_checking[1]["bills_due"] == 200_000

    @pytest.mark.asyncio
    async def test_the_outlook_carries_the_running_balance(
        self, async_db_session: AsyncSession
    ) -> None:
        """Rate without level lies: +$3,000/mo of net means nothing if the
        account holds $500 and a big bill lands first. Each month carries
        where cash STARTS and ENDS, compounding from today's real balance
        of the selected accounts."""
        svc = FinanceService(async_db_session)
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
        assert first["start_balance"] == 50_000
        assert first["end_balance"] == 50_000 + first["month_net"]
        assert second["start_balance"] == first["end_balance"]
        assert second["end_balance"] == second["start_balance"] + second["month_net"]


class TestStatDetails:
    """Per-row backup for the header cells: what the popup shows when a
    cell is clicked. Income and Bills mirror the cells' own math
    (commitment gate, monthly-equivalent factors) row for row; the
    everything-else rows are the run-rate bucket grouped by category, so
    the user can see WHICH spending no plan covers."""

    @pytest.mark.asyncio
    async def test_income_and_bills_rows_mirror_the_cells(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Mortgage",
            direction="outflow",
            frequency="monthly",
            expected_amount=220_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Car insurance",
            direction="outflow",
            frequency="annually",
            expected_amount=120_000,
            next_expected_date=date(2027, 1, 1),
            account_id=account.id,
        )
        muted = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Old gym",
            direction="outflow",
            frequency="monthly",
            expected_amount=5_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await svc.mute_recurring(muted.id, owner_user_id=1)

        details = await svc.budget_stat_details(
            owner_user_id=1, today=date(2026, 8, 10)
        )

        assert [(r["label"], r["value"]) for r in details["income"]] == [
            ("Paycheck", 500_000)
        ]
        # Monthly-equivalent, biggest first; the annual bill names its
        # real cadence so $100/mo is not mistaken for the face value.
        bills = details["bills"]
        assert [(r["label"], r["value"]) for r in bills] == [
            ("Mortgage", 220_000),
            ("Car insurance", 10_000),
        ]
        assert "annually" in (bills[1]["caption"] or "")
        # The popup's sum IS the cell's figure.
        summary = await svc.budget_summary(owner_user_id=1)
        assert sum(r["value"] for r in bills) == summary["stats"]["fixed_total"]

    @pytest.mark.asyncio
    async def test_everything_else_rows_group_the_bucket(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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

        rows = details["everything_else"]
        assert [(r["label"], r["value"]) for r in rows] == [("Uncategorized", 33_000)]
        assert "4 rows" in (rows[0]["caption"] or "")
        # The rows sum to the cell's rate, always.
        rate = await svc.uncovered_spending_rate(
            owner_user_id=1, today=date(2026, 8, 10)
        )
        assert sum(r["value"] for r in rows) == rate
        assert details["window"] == "May - Jul 2026 average"


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
        self, async_db_session: AsyncSession
    ) -> None:
        """A reconciliation adjustment is bookkeeping (making the ledger
        agree with a statement), not money the user chose to spend - it
        must not inflate the observed run rate."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
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
        assert rate == 10_000  # $300 over 3 months; the adjustment is invisible

    @pytest.mark.asyncio
    async def test_uncovered_spend_becomes_the_run_rate(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=100_000,
        )
        rent = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        for month in (5, 6, 7):
            await self._spend(
                svc, account.id, date(2026, month, 12), 60_000, name="Random"
            )

        stats = (await svc.budget_summary(owner_user_id=1))["stats"]
        assert stats["everything_else"] == 60_000
        assert stats["month_net"] == 500_000 - 60_000

        outlook = await svc.budget_month_outlook(
            owner_user_id=1, months=2, today=date(2026, 8, 10)
        )
        assert outlook[1]["everything_else"] == 60_000
        assert outlook[1]["month_net"] == 500_000 - 60_000
