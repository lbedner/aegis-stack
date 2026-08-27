"""Hot read paths issue a bounded number of queries, independent of row count.

Each test runs the same path at two sizes and asserts the query count does
not grow with N — the property a per-row loop breaks. Counts are measured
with a cursor-level listener, so ORM caching cannot mask a round trip.
"""

from datetime import date

import pytest
from sqlalchemy import event
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import declare_recurring
from app.services.finance.domains.planning import budgets
from app.services.finance.service import FinanceService
from app.services.finance.utils import current_period_month


class QueryCounter:
    """Counts statements hitting the database through a sync engine."""

    def __init__(self, async_engine) -> None:
        self._engine = async_engine.sync_engine
        self.count = 0

    def _increment(self, *args: object, **kwargs: object) -> None:
        self.count += 1

    def __enter__(self) -> "QueryCounter":
        event.listen(self._engine, "before_cursor_execute", self._increment)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._increment)


async def _checking(svc: FinanceService) -> int:
    account = await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
        current_balance=500_000,
    )
    return account.id


async def _budget_line(svc: FinanceService, hint: str, cents: int) -> None:
    category = await svc.get_or_create_category_from_hint(hint)
    assert category is not None
    await svc.upsert_budget_line(
        owner_user_id=1,
        period_month=current_period_month(),
        category_id=category.id,
        payee_key=None,
        payee_label=None,
        allocated_amount=cents,
    )


class TestProjectionDrawdownsAreBatched:
    @pytest.mark.asyncio
    async def test_query_count_does_not_grow_with_budget_lines(
        self, svc: FinanceService, async_engine
    ) -> None:
        await _checking(svc)
        for hint in ("Groceries", "Fuel"):
            await _budget_line(svc, hint, 40_000)

        with QueryCounter(async_engine) as small:
            await svc.project_balances(owner_user_id=1, days=60)

        for hint in ("Dining", "Streaming", "Utilities", "Travel"):
            await _budget_line(svc, hint, 25_000)

        with QueryCounter(async_engine) as large:
            await svc.project_balances(owner_user_id=1, days=60)

        assert large.count == small.count


class TestBulkSoftDeleteIsBatched:
    async def _split_parents(
        self, svc: FinanceService, account_id: int, n: int
    ) -> list[int]:
        ids: list[int] = []
        for i in range(n):
            txn = await svc.create_transaction(
                account_id=account_id,
                amount=-10_000 - i,
                txn_date=date(2026, 8, 1),
                owner_user_id=1,
                name=f"SPLIT {i}",
            )
            await svc.create_split(
                parent_transaction_id=txn.id, amount=-5_000, owner_user_id=1
            )
            txn.is_split = True
            svc.db.add(txn)
            ids.append(txn.id)
        await svc.db.flush()
        return ids

    @pytest.mark.asyncio
    async def test_query_count_does_not_grow_with_deleted_rows(
        self, svc: FinanceService, async_engine
    ) -> None:
        account_id = await _checking(svc)

        first = await self._split_parents(svc, account_id, 2)
        with QueryCounter(async_engine) as small:
            deleted = await svc.soft_delete_transactions(first, owner_user_id=1)
        assert deleted == 2

        second = await self._split_parents(svc, account_id, 6)
        with QueryCounter(async_engine) as large:
            deleted = await svc.soft_delete_transactions(second, owner_user_id=1)
        assert deleted == 6

        assert large.count == small.count


class TestAnalystSnapshotIsBatched:
    @pytest.mark.asyncio
    async def test_query_count_does_not_grow_with_goals(
        self, svc: FinanceService, async_db_session: AsyncSession, async_engine
    ) -> None:
        from app.services.finance.domains.detection import analyst

        if not hasattr(analyst, "build_finance_snapshot"):
            # The analyst rides the AI service; without AI the package's
            # modules render empty, so the import succeeds but carries
            # nothing. (The old single-module layout failed the import
            # instead - importing an empty PACKAGE succeeds.)
            pytest.skip("analyst not present in this stack (no AI)")

        await _checking(svc)
        await svc.create_virtual_goal(
            owner_user_id=1, name="Vacation", target_amount=500_000
        )

        # Warm-up: first call pays one-time get-or-create costs (budget
        # row, currency) that would skew the comparison.
        await analyst.build_finance_snapshot(async_db_session, owner_user_id=1)
        with QueryCounter(async_engine) as small:
            await analyst.build_finance_snapshot(async_db_session, owner_user_id=1)

        for name in ("Roof", "Car", "Emergency"):
            await svc.create_virtual_goal(
                owner_user_id=1, name=name, target_amount=250_000
            )
        with QueryCounter(async_engine) as large:
            await analyst.build_finance_snapshot(async_db_session, owner_user_id=1)

        assert large.count == small.count


class TestBudgetSuggestionAliasesAreBatched:
    async def _confirmed_uncategorized_stream(
        self,
        svc: FinanceService,
        db: AsyncSession,
        account_id: int,
        name: str,
    ) -> None:
        # The alias exists (hint creates category + alias); the stream is
        # user-declared but stripped of its category, so the suggestion
        # pass must fall back to the alias table for it.
        await svc.get_or_create_category_from_hint(name)
        txns = [
            await svc.create_transaction(
                account_id=account_id,
                amount=-12_000,
                txn_date=date(2026, m, 3),
                owner_user_id=1,
                name=name,
            )
            for m in range(1, 8)
        ]
        from sqlmodel import select

        from app.services.finance.models import FinanceRecurringStream

        await declare_recurring(db, [t.id for t in txns], owner_user_id=1)
        rows = (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.name == name
                )
            )
        ).all()
        assert rows
        for stream in rows:
            stream.category_id = None
            db.add(stream)
        await db.flush()

    @pytest.mark.asyncio
    async def test_query_count_does_not_grow_with_streams(
        self, svc: FinanceService, async_db_session: AsyncSession, async_engine
    ) -> None:
        account_id = await _checking(svc)

        await self._confirmed_uncategorized_stream(
            svc, async_db_session, account_id, "Rent"
        )
        # Warm-up: the first call pays one-time get-or-create costs
        # (budget row, currency) that would skew the comparison.
        await budgets.suggest_budget_lines(async_db_session, owner_user_id=1)
        with QueryCounter(async_engine) as small:
            await budgets.suggest_budget_lines(async_db_session, owner_user_id=1)

        for name in ("Water", "Power", "Internet"):
            await self._confirmed_uncategorized_stream(
                svc, async_db_session, account_id, name
            )
        with QueryCounter(async_engine) as large:
            await budgets.suggest_budget_lines(async_db_session, owner_user_id=1)

        assert large.count == small.count
