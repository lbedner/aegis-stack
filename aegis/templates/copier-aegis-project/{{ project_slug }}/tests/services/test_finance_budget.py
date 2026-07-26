"""Tests for the Budget tab's service layer.

Covers ``get_or_create_budget`` idempotency, ``upsert_budget_line`` for both
target shapes, ``budget_summary``'s spend math (category and payee level,
plus the Fixed/Non-monthly recurring split), ``parse_budget_goal``'s
deterministic matching, and a concrete N+1 check on ``budget_summary``.
"""

from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import event
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.finance_service import FinanceService

_MONTH = 202607


async def _account(svc, name="Checking", owner_user_id=1):
    return await svc.create_manual_account(
        name=name,
        account_type="checking",
        classification="asset",
        owner_user_id=owner_user_id,
    )


async def _txn(svc, account_id, amount, day, *, name=None, category_id=None, owner_user_id=1):
    return await svc.create_transaction(
        account_id=account_id,
        amount=amount,
        txn_date=day,
        owner_user_id=owner_user_id,
        name=name,
        category_id=category_id,
    )


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
        await _txn(
            svc, checking.id, -6_000, date(2026, 7, 3), category_id=groceries.id
        )
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
            line["category_id"]: line for line in flexible["lines"] if line["category_id"]
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
