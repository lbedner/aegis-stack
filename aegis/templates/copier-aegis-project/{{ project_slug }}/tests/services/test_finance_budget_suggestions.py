"""Auto-budget: what your own spending says next month will cost.

Derived backwards from history, which only works where spending is
CONSISTENT. The failure mode is the same one that made a convenience
store a yearly subscription: an average with no dispersion check invents
a pattern. Auto & Transport ran $36 one month and $2,301 another - a mean
of $844 is wrong every single month.

So a candidate has to show up in most months AND stay inside a spread
bound, and the amount is a median so one repair bill cannot set the year.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.finance_service import FinanceService
from app.services.finance.models import FinanceCategory

TODAY = date(2026, 8, 2)


async def _category(db: AsyncSession, name: str) -> FinanceCategory:
    row = FinanceCategory(
        owner_user_id=1, name=name,
        slug=name.lower().replace(" ", "-").replace(":", "-").replace("&", "and"),
        classification="expense",
    )
    db.add(row)
    await db.flush()
    return row


async def _account(svc: FinanceService):
    return await svc.create_manual_account(
        name="Checking", account_type="checking",
        classification="asset", owner_user_id=1,
    )


async def _spend(svc, account_id, category_id, amounts: dict[int, int], *, transfer=False):
    """``{month: dollars}`` across 2026."""
    for month, dollars in amounts.items():
        txn = await svc.create_transaction(
            account_id=account_id, amount=-dollars * 100,
            txn_date=date(2026, month, 12), owner_user_id=1, name="X",
            category_id=category_id,
        )
        if transfer:
            txn.is_transfer = True


class TestSuggestions:
    @pytest.mark.asyncio
    async def test_a_steady_category_is_suggested(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        await _spend(svc, account.id, groceries.id,
                     {2: 1300, 3: 1400, 4: 1350, 5: 1500, 6: 1380, 7: 1420})

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert [p["category_id"] for p in picks] == [groceries.id]
        # Median of the months, not the mean - and in cents.
        assert 130_000 <= picks[0]["suggested_amount"] <= 150_000

    @pytest.mark.asyncio
    async def test_a_lumpy_category_is_not(
        self, async_db_session: AsyncSession
    ) -> None:
        """$36 one month, $2,301 another. The mean predicts nothing."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        repairs = await _category(async_db_session, "Auto & Transport:Service")
        await _spend(svc, account.id, repairs.id,
                     {2: 36, 3: 40, 4: 2301, 5: 50, 6: 45, 7: 1800})

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []

    @pytest.mark.asyncio
    async def test_a_one_off_is_not(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        once = await _category(async_db_session, "Shopping")
        await _spend(svc, account.id, once.id, {5: 900})

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []

    @pytest.mark.asyncio
    async def test_transfers_are_never_suggested(
        self, async_db_session: AsyncSession
    ) -> None:
        """The three biggest rows by value are credit-card payments and
        transfers - money moving between your own accounts, not spending.
        Budgeting them would double-count against the forecast."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        moving = await _category(async_db_session, "Transfer:Credit Card Payment")
        await _spend(svc, account.id, moving.id,
                     {2: 3600, 3: 3700, 4: 3650, 5: 3690, 6: 3600, 7: 3700},
                     transfer=True)

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []

    @pytest.mark.asyncio
    async def test_a_category_a_bill_already_covers_is_skipped(
        self, async_db_session: AsyncSession
    ) -> None:
        """Mortgage is steady as a rock and already a bill. Budgeting it
        too would charge the forecast twice for one payment."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        rent = await _category(async_db_session, "Home:Mortgage & Rent")
        await _spend(svc, account.id, rent.id,
                     {2: 2553, 3: 2553, 4: 2553, 5: 2553, 6: 2553, 7: 2553})
        stream = await svc.create_recurring_stream(
            owner_user_id=1, name="Mortgage", direction="outflow",
            frequency="monthly", expected_amount=255_300,
            next_expected_date=date(2026, 9, 1), account_id=account.id,
        )
        await svc.update_recurring(stream.id, owner_user_id=1, category_id=rent.id)

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert [p["category_id"] for p in picks] == []

    @pytest.mark.asyncio
    async def test_a_line_you_already_set_is_not_re_suggested(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        await _spend(svc, account.id, groceries.id,
                     {2: 1300, 3: 1400, 4: 1350, 5: 1500, 6: 1380, 7: 1420})
        await svc.upsert_budget_line(
            owner_user_id=1, period_month=None, category_id=groceries.id,
            payee_key=None, payee_label=None, allocated_amount=140_000,
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []


class TestBudgetsInTheForecast:
    """A budget line is money you expect to spend, so the forecast should
    know about it - without charging you twice for the same spending.
    """

    async def _setup(self, svc, db):
        account = await _account(svc)
        groceries = await _category(db, "Food & Dining:Groceries")
        return account, groceries

    @pytest.mark.asyncio
    async def test_a_budget_line_draws_the_balance_down(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account, groceries = await self._setup(svc, async_db_session)
        await svc.upsert_budget_line(
            owner_user_id=1, period_month=None, category_id=groceries.id,
            payee_key=None, payee_label=None, allocated_amount=140_000,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=90, today=TODAY
        )

        assert "Food & Dining:Groceries" in {p.name for p in result.points}
        drawn = [p for p in result.points if p.name == "Food & Dining:Groceries"]
        assert all(p.amount < 0 for p in drawn)

    @pytest.mark.asyncio
    async def test_a_category_a_bill_covers_is_not_charged_twice(
        self, async_db_session: AsyncSession
    ) -> None:
        """The rule: bills win. A budget line on a category a recurring
        bill already pays would subtract the same money a second time."""
        svc = FinanceService(async_db_session)
        account, groceries = await self._setup(svc, async_db_session)
        stream = await svc.create_recurring_stream(
            owner_user_id=1, name="Grocery delivery", direction="outflow",
            frequency="monthly", expected_amount=140_000,
            next_expected_date=date(2026, 8, 15), account_id=account.id,
        )
        await svc.update_recurring(
            stream.id, owner_user_id=1, category_id=groceries.id
        )
        await svc.upsert_budget_line(
            owner_user_id=1, period_month=None, category_id=groceries.id,
            payee_key=None, payee_label=None, allocated_amount=140_000,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=90, today=TODAY
        )

        names = [p.name for p in result.points]
        assert "Grocery delivery" in names          # the bill projects
        assert "Food & Dining:Groceries" not in names  # the budget does not


class TestBillOverlapUsesInferredCategories:
    """A bill's category is usually INFERRED, not stored.

    ``finance_recurring_stream.category_id`` is a provider field the local
    detector never fills, so most bills carry none - their category comes
    from their member transactions. Checking only the stored column missed
    nearly every real overlap, and suggested a budget line for a category
    a bill was already paying.
    """

    @pytest.mark.asyncio
    async def test_a_bill_with_no_stored_category_still_blocks(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.categorize import declare_recurring

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        productivity = await _category(
            async_db_session, "Bills & Utilities:Productivity"
        )
        # A real subscription: consistent monthly spend, categorised on the
        # TRANSACTIONS, declared as a bill - and the stream itself keeps a
        # null category_id.
        txns = []
        for month in range(2, 8):
            txn = await svc.create_transaction(
                account_id=account.id, amount=-46_000,
                txn_date=date(2026, month, 11), owner_user_id=1,
                name="ANTHROPIC", category_id=productivity.id,
            )
            txns.append(txn)
        await declare_recurring(
            async_db_session, [t.id for t in txns], owner_user_id=1
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert productivity.id not in {p["category_id"] for p in picks}


class TestOnlyForecastChargingBillsBlock:
    """Blocking is about double-counting, so only what the FORECAST
    charges can block.

    Groceries had 19 merchant rhythms inferring that category - Shop Rite,
    Adams, Stop & Shop, a dozen Apple Pay variants - totalling $2,818/mo
    on paper. Every one failed the commitment gate and projected nothing,
    yet together they blocked the single most important budget line the
    user has.
    """

    @pytest.mark.asyncio
    async def test_a_shopping_rhythm_does_not_block_its_category(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        await _spend(svc, account.id, groceries.id,
                     {2: 1300, 3: 1400, 4: 1350, 5: 1500, 6: 1380, 7: 1420})
        # A detected merchant rhythm: varying amounts, never confirmed -
        # exactly what is_commitment refuses, so it projects nothing.
        stream = await svc.create_recurring_stream(
            owner_user_id=1, name="Shop Rite", direction="outflow",
            frequency="weekly", expected_amount=120_000,
            next_expected_date=date(2026, 8, 9), account_id=account.id,
        )
        stream.source = "derived"
        stream.is_user_confirmed = False
        stream.is_subscription = False
        stream.amount_is_variable = True
        stream.category_id = groceries.id
        async_db_session.add(stream)
        await async_db_session.flush()

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert groceries.id in {p["category_id"] for p in picks}
