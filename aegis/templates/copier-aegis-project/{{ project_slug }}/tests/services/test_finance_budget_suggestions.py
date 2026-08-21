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

from tests.services._finance_factories import seed_account as _account, seed_category as _category
from app.services.finance.models import FinanceCategory
from app.services.finance.service import FinanceService

TODAY = date(2026, 8, 2)



async def _spend(
    svc, account_id, category_id, amounts: dict[int, int], *, transfer=False
):
    """``{month: dollars}`` across 2026."""
    for month, dollars in amounts.items():
        txn = await svc.create_transaction(
            account_id=account_id,
            amount=-dollars * 100,
            txn_date=date(2026, month, 12),
            owner_user_id=1,
            name="X",
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
        await _spend(
            svc,
            account.id,
            groceries.id,
            {2: 1300, 3: 1400, 4: 1350, 5: 1500, 6: 1380, 7: 1420},
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert [p.category_id for p in picks] == [groceries.id]
        # Median of the months, not the mean - and in cents.
        assert 130_000 <= picks[0].suggested_amount <= 150_000

    @pytest.mark.asyncio
    async def test_a_lumpy_category_is_not(
        self, async_db_session: AsyncSession
    ) -> None:
        """$36 one month, $2,301 another. The mean predicts nothing."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        repairs = await _category(async_db_session, "Auto & Transport:Service")
        await _spend(
            svc, account.id, repairs.id, {2: 36, 3: 40, 4: 2301, 5: 50, 6: 45, 7: 1800}
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []

    @pytest.mark.asyncio
    async def test_a_one_off_is_not(self, async_db_session: AsyncSession) -> None:
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
        await _spend(
            svc,
            account.id,
            moving.id,
            {2: 3600, 3: 3700, 4: 3650, 5: 3690, 6: 3600, 7: 3700},
            transfer=True,
        )

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
        await _spend(
            svc,
            account.id,
            rent.id,
            {2: 2553, 3: 2553, 4: 2553, 5: 2553, 6: 2553, 7: 2553},
        )
        stream = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Mortgage",
            direction="outflow",
            frequency="monthly",
            expected_amount=255_300,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await svc.update_recurring(stream.id, owner_user_id=1, category_id=rent.id)

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert [p.category_id for p in picks] == []

    @pytest.mark.asyncio
    async def test_a_line_you_already_set_is_not_re_suggested(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        await _spend(
            svc,
            account.id,
            groceries.id,
            {2: 1300, 3: 1400, 4: 1350, 5: 1500, 6: 1380, 7: 1420},
        )
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=140_000,
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
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=140_000,
        )

        result = await svc.project_balances(owner_user_id=1, days=90, today=TODAY)

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
            owner_user_id=1,
            name="Grocery delivery",
            direction="outflow",
            frequency="monthly",
            expected_amount=140_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await svc.update_recurring(stream.id, owner_user_id=1, category_id=groceries.id)
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=140_000,
        )

        result = await svc.project_balances(owner_user_id=1, days=90, today=TODAY)

        names = [p.name for p in result.points]
        assert "Grocery delivery" in names  # the bill projects
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
        from app.services.finance.domains.detection import declare_recurring

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
                account_id=account.id,
                amount=-46_000,
                txn_date=date(2026, month, 11),
                owner_user_id=1,
                name="ANTHROPIC",
                category_id=productivity.id,
            )
            txns.append(txn)
        await declare_recurring(async_db_session, [t.id for t in txns], owner_user_id=1)

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert productivity.id not in {p.category_id for p in picks}


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
        await _spend(
            svc,
            account.id,
            groceries.id,
            {2: 1300, 3: 1400, 4: 1350, 5: 1500, 6: 1380, 7: 1420},
        )
        # A detected merchant rhythm: varying amounts, never confirmed -
        # exactly what is_commitment refuses, so it projects nothing.
        stream = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Shop Rite",
            direction="outflow",
            frequency="weekly",
            expected_amount=120_000,
            next_expected_date=date(2026, 8, 9),
            account_id=account.id,
        )
        stream.source = "derived"
        stream.is_user_confirmed = False
        stream.is_subscription = False
        stream.amount_is_variable = True
        stream.category_id = groceries.id
        async_db_session.add(stream)
        await async_db_session.flush()

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert groceries.id in {p.category_id for p in picks}


class TestSuggestionDismissals:
    """FIN-35: a declined suggestion stays declined - across reloads and
    month rollovers (the marker lives on the standing budget row) - until
    restored, and its marker never renders as a budget line."""

    async def _steady_groceries(self, svc: FinanceService, db: AsyncSession):
        account = await _account(svc)
        groceries = await _category(db, "Food & Dining:Groceries")
        await _spend(
            svc,
            account.id,
            groceries.id,
            {2: 1300, 3: 1400, 4: 1350, 5: 1500, 6: 1380, 7: 1420},
        )
        return account, groceries

    @pytest.mark.asyncio
    async def test_dismissed_suggestion_stays_gone_until_restored(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        _, groceries = await self._steady_groceries(svc, async_db_session)

        before = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)
        assert groceries.id in [p.category_id for p in before]

        assert (
            await svc.dismiss_budget_suggestions(
                owner_user_id=1, category_ids=[groceries.id]
            )
            == 1
        )
        assert await svc.suggest_budget_lines(owner_user_id=1, today=TODAY) == []
        dismissed = await svc.list_dismissed_suggestions(owner_user_id=1)
        assert [d.category_id for d in dismissed] == [groceries.id]
        assert dismissed[0].category_name == "Food & Dining:Groceries"

        # Idempotent: declining again records nothing new.
        assert (
            await svc.dismiss_budget_suggestions(
                owner_user_id=1, category_ids=[groceries.id]
            )
            == 0
        )

        assert (
            await svc.restore_budget_suggestions(
                owner_user_id=1, category_ids=[groceries.id]
            )
            == 1
        )
        after = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)
        assert groceries.id in [p.category_id for p in after]
        assert await svc.list_dismissed_suggestions(owner_user_id=1) == []

    @pytest.mark.asyncio
    async def test_dismissal_marker_is_not_a_budget_line(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        _, groceries = await self._steady_groceries(svc, async_db_session)
        await svc.dismiss_budget_suggestions(
            owner_user_id=1, category_ids=[groceries.id]
        )
        summary = await svc.budget_summary(owner_user_id=1)
        for bucket in summary.buckets:
            for line in bucket.lines:
                assert line.category_id != groceries.id


class TestConfirmedBillSuppression:
    """FIN-35 (b): a CONFIRMED bill's category is suppressed by PRESENCE.
    The magnitude test stays for unconfirmed detector rhythms only."""

    @pytest.mark.asyncio
    async def test_confirmed_bill_suppresses_even_with_no_members(
        self, async_db_session: AsyncSession
    ) -> None:
        """The FIN-34 shape: bill membership stripped, stored category
        intact, expected amount too small for the magnitude test - the
        category must still never be suggested."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        rent = await _category(async_db_session, "Home:Mortgage & Rent")
        await _spend(
            svc,
            account.id,
            rent.id,
            {2: 2553, 3: 2553, 4: 2553, 5: 2553, 6: 2553, 7: 2553},
        )
        stream = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Mortgage",
            direction="outflow",
            frequency="monthly",
            # A sliver of the real spend: the magnitude test alone would
            # NOT suppress this. Presence must.
            expected_amount=100,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await svc.update_recurring(stream.id, owner_user_id=1, category_id=rent.id)

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)
        assert rent.id not in [p.category_id for p in picks]

    @pytest.mark.asyncio
    async def test_confirmed_bill_with_no_category_resolves_via_name_alias(
        self, async_db_session: AsyncSession
    ) -> None:
        """No stored category and no members to infer from: the stream's
        own name through the alias table still claims the category."""
        from app.services.finance.models import FinanceCategoryAlias

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        rent = await _category(async_db_session, "Home:Mortgage & Rent")
        async_db_session.add(
            FinanceCategoryAlias(
                category_id=rent.id,
                alias_text="Mortgage",
                normalized_alias="MORTGAGE",
            )
        )
        await async_db_session.flush()
        await _spend(
            svc,
            account.id,
            rent.id,
            {2: 2553, 3: 2553, 4: 2553, 5: 2553, 6: 2553, 7: 2553},
        )
        await svc.create_recurring_stream(
            owner_user_id=1,
            name="Mortgage",
            direction="outflow",
            frequency="monthly",
            expected_amount=100,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)
        assert rent.id not in [p.category_id for p in picks]


class TestTheForecastStaysInSyncWithActuals:
    """A budget line is an ENVELOPE, not an event.

    What belongs in a balance walk is the UNSPENT remainder. Money already
    spent has left the account and is in the starting balance already, so
    charging the whole allocation on top counts it twice - and every real
    transaction widens the gap, which means the forecast drifts further
    from reality exactly as more evidence arrives.

    The invariant that fixes it:

        spent_so_far + projected_remainder == allocated

    A transaction landing moves money from the right side to the left, so
    the projected end balance does not move at all. That is the whole
    point, and ``test_the_end_balance_does_not_move`` is the test that
    says so.
    """

    ALLOCATED = 80_000  # $800

    async def _budgeted(self, svc, db):
        account = await _account(svc)
        groceries = await _category(db, "Food & Dining:Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=self.ALLOCATED,
        )
        return account, groceries

    @staticmethod
    def _budget_points(result, name="Food & Dining:Groceries"):
        return [p for p in result.points if p.name.startswith(name)]

    @pytest.mark.asyncio
    async def test_only_the_unspent_remainder_is_charged_this_month(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account, groceries = await self._budgeted(svc, async_db_session)
        await _spend(svc, account.id, groceries.id, {8: 600})

        result = await svc.project_balances(owner_user_id=1, days=20, today=TODAY)

        points = self._budget_points(result)
        assert len(points) == 1
        assert points[0].amount == -(self.ALLOCATED - 60_000)

    @pytest.mark.asyncio
    async def test_the_end_balance_does_not_move_when_a_transaction_lands(
        self, async_db_session: AsyncSession
    ) -> None:
        """THE test. Spending against a budgeted category moves money from
        "projected" to "already gone" - two sides of one envelope - so the
        forecast must land in exactly the same place."""
        svc = FinanceService(async_db_session)
        account, groceries = await self._budgeted(svc, async_db_session)

        before = await svc.project_balances(owner_user_id=1, days=20, today=TODAY)
        await _spend(svc, account.id, groceries.id, {8: 600})
        after = await svc.project_balances(owner_user_id=1, days=20, today=TODAY)

        assert after.end_balance == before.end_balance

    @pytest.mark.asyncio
    async def test_a_fully_spent_envelope_charges_nothing_more(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account, groceries = await self._budgeted(svc, async_db_session)
        await _spend(svc, account.id, groceries.id, {8: 800})

        result = await svc.project_balances(owner_user_id=1, days=20, today=TODAY)

        assert self._budget_points(result) == []

    @pytest.mark.asyncio
    async def test_an_overspent_envelope_charges_nothing_more(
        self, async_db_session: AsyncSession
    ) -> None:
        """The overage already left the account. Charging anything further
        this month would be inventing spending."""
        svc = FinanceService(async_db_session)
        account, groceries = await self._budgeted(svc, async_db_session)
        await _spend(svc, account.id, groceries.id, {8: 950})

        result = await svc.project_balances(owner_user_id=1, days=20, today=TODAY)

        assert self._budget_points(result) == []

    @pytest.mark.asyncio
    async def test_the_remainder_is_dated_at_month_end(
        self, async_db_session: AsyncSession
    ) -> None:
        """It has not happened yet, so it must not dent the line today -
        which is also why every budget line used to pile up at the very
        start of the projection."""
        svc = FinanceService(async_db_session)
        await self._budgeted(svc, async_db_session)

        result = await svc.project_balances(owner_user_id=1, days=20, today=TODAY)

        assert self._budget_points(result)[0].date == date(2026, 8, 31)


class TestAnOverageIsMadeUpNextMonth:
    """Going over does not have to be a write-off. The overage carries
    into the next envelope as a TIGHTER budget, so the forecast shows you
    making it up without anyone editing the budget.

    Across the two months the total still comes to two months of budget:
    $950 spent + $650 projected == $800 + $800.
    """

    ALLOCATED = 80_000

    async def _overspent(self, svc, db, dollars: int):
        account = await _account(svc)
        groceries = await _category(db, "Food & Dining:Groceries")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=None,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=self.ALLOCATED,
        )
        await _spend(svc, account.id, groceries.id, {8: dollars})
        return account, groceries

    @staticmethod
    def _budget_points(result):
        return [p for p in result.points if p.name.startswith("Food & Dining")]

    @pytest.mark.asyncio
    async def test_an_overage_tightens_next_month(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._overspent(svc, async_db_session, 950)

        result = await svc.project_balances(owner_user_id=1, days=75, today=TODAY)

        points = self._budget_points(result)
        assert len(points) == 1
        assert points[0].date == date(2026, 9, 30)
        assert points[0].amount == -(self.ALLOCATED - 15_000)

    @pytest.mark.asyncio
    async def test_the_tightened_month_says_why(
        self, async_db_session: AsyncSession
    ) -> None:
        """A number smaller than the budget, with no explanation, reads as
        a bug in the forecast."""
        svc = FinanceService(async_db_session)
        await self._overspent(svc, async_db_session, 950)

        result = await svc.project_balances(owner_user_id=1, days=75, today=TODAY)

        assert "overspend" in self._budget_points(result)[0].name.lower()

    @pytest.mark.asyncio
    async def test_the_carry_reaches_only_the_next_month(
        self, async_db_session: AsyncSession
    ) -> None:
        """You make it up once. The month after is a clean envelope."""
        svc = FinanceService(async_db_session)
        await self._overspent(svc, async_db_session, 950)

        result = await svc.project_balances(owner_user_id=1, days=105, today=TODAY)

        points = self._budget_points(result)
        assert [p.amount for p in points] == [
            -(self.ALLOCATED - 15_000),
            -self.ALLOCATED,
        ]

    @pytest.mark.asyncio
    async def test_a_carry_bigger_than_the_envelope_clamps_at_zero(
        self, async_db_session: AsyncSession
    ) -> None:
        """A negative outflow is income. Blowing two months of grocery
        budget must not forecast the supermarket paying you."""
        svc = FinanceService(async_db_session)
        await self._overspent(svc, async_db_session, 2_000)

        result = await svc.project_balances(owner_user_id=1, days=75, today=TODAY)

        assert all(p.amount <= 0 for p in result.points)
        assert self._budget_points(result) == []

    @pytest.mark.asyncio
    async def test_an_unspent_envelope_does_not_inflate_next_month(
        self, async_db_session: AsyncSession
    ) -> None:
        """The forecast already assumes this month's envelope gets used,
        so there is nothing left over to carry."""
        svc = FinanceService(async_db_session)
        await self._overspent(svc, async_db_session, 200)

        result = await svc.project_balances(owner_user_id=1, days=75, today=TODAY)

        assert [p.amount for p in self._budget_points(result)] == [
            -(self.ALLOCATED - 20_000),
            -self.ALLOCATED,
        ]


class TestOneQuietMonthIsNotErratic:
    """The dispersion gate has to answer "is this steady", and
    ``max / min`` answers something else: "how far apart are the two most
    extreme months". A single outlier destroys it.

    Measured on a real ledger: a $300/month portfolio contribution that
    was IDENTICAL in five of six months scored 4.3x and was rejected, as
    were steady clothing, fuel and gifts lines. Nothing at all was being
    suggested. The amount already uses a median precisely so one repair
    bill cannot set the year; the spread test just never got the same
    treatment.

    Median absolute deviation over the median asks how far a TYPICAL
    month sits from the typical month, which is the actual question.
    """

    @pytest.mark.asyncio
    async def test_a_steady_category_with_one_big_month_is_suggested(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        portfolio = await _category(async_db_session, "Investing:Portfolio")
        # Five identical months and one that is four times bigger.
        await _spend(
            svc,
            account.id,
            portfolio.id,
            {2: 300, 3: 300, 4: 300, 5: 300, 6: 300, 7: 1_200},
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert [p.category_name for p in picks] == ["Investing:Portfolio"]
        # The MEDIAN month, not dragged up by the outlier.
        assert picks[0].suggested_amount == 30_000
        assert picks[0].unusual_months == 1

    @pytest.mark.asyncio
    async def test_genuinely_erratic_spending_is_still_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        """The half that must not regress: this is the "stuff I will not
        spend money on again" that a budget line would be wrong about."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        odd = await _category(async_db_session, "Shopping:Whatever")
        await _spend(
            svc,
            account.id,
            odd.id,
            {2: 20, 3: 700, 4: 50, 5: 900, 6: 30, 7: 600},
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []

    @pytest.mark.asyncio
    async def test_the_reported_figure_counts_the_odd_months(
        self, async_db_session: AsyncSession
    ) -> None:
        """A flat category reports 0 - no month looked unlike the rest."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        flat = await _category(async_db_session, "Bills & Utilities:Flat")
        await _spend(
            svc,
            account.id,
            flat.id,
            {2: 100, 3: 100, 4: 100, 5: 100, 6: 100, 7: 100},
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks[0].unusual_months == 0


class TestUncategorizedIsNeverABudgetLine:
    @pytest.mark.asyncio
    async def test_uncategorized_spending_is_not_suggested(
        self, async_db_session: AsyncSession
    ) -> None:
        """It is steady on real data - $278/month - and it passes every
        numeric gate. "Budget your uncategorized spending" is still not a
        line anyone can act on; the fix is to categorize it."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        junk = await _category(async_db_session, "Uncategorized")
        await _spend(
            svc,
            account.id,
            junk.id,
            {2: 250, 3: 260, 4: 270, 5: 280, 6: 250, 7: 260},
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []

    @pytest.mark.asyncio
    async def test_a_real_category_beside_it_still_is(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        junk = await _category(async_db_session, "Misc")
        real = await _category(async_db_session, "Food & Dining:Groceries")
        await _spend(
            svc, account.id, junk.id, {2: 250, 3: 260, 4: 270, 5: 280, 6: 250, 7: 260}
        )
        await _spend(
            svc, account.id, real.id, {2: 800, 3: 810, 4: 790, 5: 805, 6: 795, 7: 800}
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert [p.category_name for p in picks] == ["Food & Dining:Groceries"]

    @pytest.mark.asyncio
    async def test_two_odd_months_is_not_steady(
        self, async_db_session: AsyncSession
    ) -> None:
        """Where a median-of-deviations went wrong: four tightly clustered
        months make auto repairs look placid, and it would be budgeted at
        $47 while actually costing $2,301 twice a year."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        repairs = await _category(async_db_session, "Auto & Transport:Repairs")
        await _spend(
            svc,
            account.id,
            repairs.id,
            {2: 36, 3: 40, 4: 2_301, 5: 50, 6: 45, 7: 1_800},
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []


class TestOnlyExpensesAreBudgeted:
    """A budget line is about money SPENT. Categories carry a
    classification (expense / income / transfer) and only expenses
    qualify.

    Found live: with the steadiness gate fixed, the single largest
    suggestion became "Transfer" at $1,599/month - money moving between
    the user's own accounts. The transaction-level guard
    (``is_transfer``) misses these because pairing never flagged them, so
    the category's own classification is the reliable signal.
    """

    @pytest.mark.asyncio
    async def test_a_transfer_category_is_never_suggested(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        moving = FinanceCategory(
            owner_user_id=1,
            name="Transfer:Credit Card Payment",
            slug="transfer-credit-card-payment",
            classification="transfer",
        )
        async_db_session.add(moving)
        await async_db_session.flush()
        await _spend(
            svc,
            account.id,
            moving.id,
            {2: 1_600, 3: 1_590, 4: 1_610, 5: 1_600, 6: 1_595, 7: 1_605},
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert picks == []

    @pytest.mark.asyncio
    async def test_an_expense_category_beside_it_still_is(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        moving = FinanceCategory(
            owner_user_id=1,
            name="Transfer Out",
            slug="transfer-out",
            classification="transfer",
        )
        async_db_session.add(moving)
        await async_db_session.flush()
        real = await _category(async_db_session, "Food & Dining:Groceries")
        await _spend(
            svc,
            account.id,
            moving.id,
            {2: 1_600, 3: 1_590, 4: 1_610, 5: 1_600, 6: 1_595, 7: 1_605},
        )
        await _spend(
            svc, account.id, real.id, {2: 800, 3: 810, 4: 790, 5: 805, 6: 795, 7: 800}
        )

        picks = await svc.suggest_budget_lines(owner_user_id=1, today=TODAY)

        assert [p.category_name for p in picks] == ["Food & Dining:Groceries"]


class TestTheSuggestionRowReadsRight:
    """The row's second line has to describe the gate that produced it.

    It said "0.0x swing" for every suggestion after the steadiness measure
    changed: the row read a ``spread`` field that no longer existed and
    fell back to its default. A confidence signal that is always 0.0 is
    worse than none - it looks like a measurement.
    """

    def test_the_row_describes_the_months_that_were_odd(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            budget_suggestion_caption,
        )

        assert budget_suggestion_caption({"months_seen": 6, "unusual_months": 0}) == (
            "6 of 6 months  ·  every month alike"
        )
        assert budget_suggestion_caption({"months_seen": 6, "unusual_months": 1}) == (
            "6 of 6 months  ·  1 month stood out"
        )

    def test_it_does_not_invent_a_reading_from_a_missing_field(self) -> None:
        """The failure that shipped: a default that looks like a
        measurement. An absent count says nothing rather than zero."""
        from app.components.frontend.dashboard.modals.finance_modal import (
            budget_suggestion_caption,
        )

        assert budget_suggestion_caption({"months_seen": 5}) == "5 of 6 months"
