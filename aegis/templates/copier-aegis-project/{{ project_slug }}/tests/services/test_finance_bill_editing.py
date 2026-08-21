"""Editing a bill's category and account.

The category shown on Bills & Income is DERIVED - ``stream_category_names``
reads the most common category across the stream's member transactions,
because ``finance_recurring_stream.category_id`` is a provider field the
local detector never fills. So storing a category is only half the job: if
the display keeps deriving, the edit silently does nothing.

Setting it must NOT touch the member transactions (chosen deliberately -
a bulk rewrite would overwrite per-transaction corrections made by hand).
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import declare_recurring
from app.services.finance.service import FinanceService
from tests.services._finance_factories import declare_bill
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_category as _category


async def _bill(svc: FinanceService, db: AsyncSession, account_id: int, name: str):
    return await declare_bill(
        svc, db, account_id, name, [date(2026, m, 4) for m in range(1, 5)]
    )


class TestBillCategory:
    @pytest.mark.asyncio
    async def test_a_stored_category_is_what_gets_shown(
        self, async_db_session: AsyncSession
    ) -> None:
        """Otherwise the edit saves and the table keeps showing the
        category derived from the transactions - a silent no-op."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        stream, txns = await _bill(svc, async_db_session, account.id, "ACME MART")
        for txn in txns:
            await svc.categorize_transaction(
                txn.id, groceries.id, owner_user_id=1, source="user"
            )
        household = await _category(async_db_session, "Home:Household")

        await svc.update_recurring(stream.id, owner_user_id=1, category_id=household.id)

        names = await svc.stream_category_names([stream.id])
        assert names[stream.id] == "Home:Household"

    @pytest.mark.asyncio
    async def test_the_derived_category_still_shows_when_none_is_stored(
        self, async_db_session: AsyncSession
    ) -> None:
        """The existing behaviour has to survive - most bills have no
        stored category and the derived one is all there is."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        stream, txns = await _bill(svc, async_db_session, account.id, "ACME MART")
        for txn in txns:
            await svc.categorize_transaction(
                txn.id, groceries.id, owner_user_id=1, source="user"
            )

        names = await svc.stream_category_names([stream.id])
        assert names[stream.id] == "Food & Dining:Groceries"

    @pytest.mark.asyncio
    async def test_the_member_transactions_are_left_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        stream, txns = await _bill(svc, async_db_session, account.id, "ACME MART")
        for txn in txns:
            await svc.categorize_transaction(
                txn.id, groceries.id, owner_user_id=1, source="user"
            )
        household = await _category(async_db_session, "Home:Household")

        await svc.update_recurring(stream.id, owner_user_id=1, category_id=household.id)

        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.category_id == groceries.id


class TestCategoryAtDeclareTime:
    @pytest.mark.asyncio
    async def test_make_recurring_can_set_the_category(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import plan_recurring

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        household = await _category(async_db_session, "Home:Household")
        txns = [
            await svc.create_transaction(
                account_id=account.id,
                amount=-1_000,
                txn_date=date(2026, m, 4),
                owner_user_id=1,
                name="ACME MART",
            )
            for m in range(1, 5)
        ]
        ids = [t.id for t in txns]
        plan = await plan_recurring(async_db_session, ids, owner_user_id=1)

        await declare_recurring(
            async_db_session,
            ids,
            owner_user_id=1,
            categories={plan[0].key: household.id},
        )

        from sqlmodel import select

        from app.services.finance.models import FinanceRecurringStream

        stream = (
            await async_db_session.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).first()
        assert stream is not None
        assert stream.category_id == household.id
        names = await svc.stream_category_names([stream.id])
        assert names[stream.id] == "Home:Household"

    @pytest.mark.asyncio
    async def test_declaring_with_a_category_leaves_transactions_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import plan_recurring

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        household = await _category(async_db_session, "Home:Household")
        txns = [
            await svc.create_transaction(
                account_id=account.id,
                amount=-1_000,
                txn_date=date(2026, m, 4),
                owner_user_id=1,
                name="ACME MART",
            )
            for m in range(1, 5)
        ]
        ids = [t.id for t in txns]
        plan = await plan_recurring(async_db_session, ids, owner_user_id=1)

        await declare_recurring(
            async_db_session,
            ids,
            owner_user_id=1,
            categories={plan[0].key: household.id},
        )

        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.category_id is None


class TestEditingTheCadence:
    """A bill whose cadence could not be measured has to be fixable, and
    fixing it has to be enough.

    MVP, a real health-insurance bill: one transaction so far, so no gap
    to measure, so ``frequency='unknown'`` and no next due date. It sits
    in Bills reading "Active" and contributes NOTHING to the forecast,
    with nothing on screen saying so. Setting the cadence is the repair,
    and it only works if the next due date follows - an unknown cadence
    and a null date are two halves of the same hole.
    """

    async def _bill_with_no_cadence(self, svc, db):
        account = await _account(svc)
        txn = await svc.create_transaction(
            account_id=account.id,
            amount=-97_044,
            txn_date=date(2026, 7, 5),
            owner_user_id=1,
            name="MVP",
        )
        await declare_recurring(db, [txn.id], owner_user_id=1)
        stream = (await svc.list_recurring(owner_user_id=1))[0]
        assert stream.frequency == "unknown"
        assert stream.next_expected_date is None
        return stream

    @pytest.mark.asyncio
    async def test_every_offered_cadence_can_actually_be_saved(
        self, async_db_session: AsyncSession
    ) -> None:
        """The menu and the validator are two different lists. Offering a
        cadence the validator rejects turns a dropdown into a 422."""
        svc = FinanceService(async_db_session)
        stream = await self._bill_with_no_cadence(svc, async_db_session)

        from app.components.frontend.dashboard.modals.finance_modal import (
            _FREQUENCY_LABELS,
        )

        for cadence in _FREQUENCY_LABELS:
            updated = await svc.update_recurring(
                stream.id, owner_user_id=1, frequency=cadence
            )
            assert updated is not None and updated.frequency == cadence

    @pytest.mark.asyncio
    async def test_setting_a_cadence_fills_in_the_missing_due_date(
        self, async_db_session: AsyncSession
    ) -> None:
        """Otherwise the bill is exactly as invisible as before, and the
        user has no way to know the edit did not take."""
        svc = FinanceService(async_db_session)
        stream = await self._bill_with_no_cadence(svc, async_db_session)

        updated = await svc.update_recurring(
            stream.id, owner_user_id=1, frequency="monthly"
        )

        assert updated is not None
        # Stepped from the last transaction, not left null.
        assert updated.next_expected_date == date(2026, 8, 5)

    @pytest.mark.asyncio
    async def test_an_explicit_due_date_still_wins(
        self, async_db_session: AsyncSession
    ) -> None:
        """Deriving is the fallback, never an override."""
        svc = FinanceService(async_db_session)
        stream = await self._bill_with_no_cadence(svc, async_db_session)

        updated = await svc.update_recurring(
            stream.id,
            owner_user_id=1,
            frequency="monthly",
            next_expected_date=date(2026, 9, 20),
        )

        assert updated is not None
        assert updated.next_expected_date == date(2026, 9, 20)

    @pytest.mark.asyncio
    async def test_a_bill_that_already_has_a_due_date_is_left_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        """Changing the cadence on a healthy bill must not silently move
        the date it is due."""
        svc = FinanceService(async_db_session)
        account = await _account(svc, "Other")
        stream = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Netflix",
            direction="outflow",
            frequency="monthly",
            expected_amount=1_599,
            next_expected_date=date(2026, 9, 6),
            account_id=account.id,
        )

        updated = await svc.update_recurring(
            stream.id, owner_user_id=1, frequency="quarterly"
        )

        assert updated is not None
        assert updated.next_expected_date == date(2026, 9, 6)

    @pytest.mark.asyncio
    async def test_the_repaired_bill_reaches_the_forecast(
        self, async_db_session: AsyncSession
    ) -> None:
        """The point of the whole exercise."""
        svc = FinanceService(async_db_session)
        stream = await self._bill_with_no_cadence(svc, async_db_session)
        await svc.update_recurring(
            stream.id, owner_user_id=1, frequency="monthly", expected_amount=97_044
        )

        result = await svc.project_balances(
            owner_user_id=1, days=120, today=date(2026, 8, 8)
        )

        assert any(p.name == "MVP" for p in result.points)


class TestTheCadenceListsAllAgree:
    """Four lists describe the same set of cadences. They drifted, and the
    gaps were invisible until a real bill fell through one:

        _CADENCES            what detection can measure
        FREQUENCY_STEPS     what the forecast can step
        _FREQUENCY_LABELS    what the menus offer
        _STREAM_FREQUENCIES  what create/update will accept

    A cadence in the menu but not the validator is a dropdown that 422s.
    One the forecast can step but nothing offers is a bill nobody can
    declare. Pinned as one set so the next addition cannot land in three
    places out of four.
    """

    def test_menu_validator_and_forecast_are_the_same_set(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            _FREQUENCY_LABELS,
        )
        from app.services.finance.service import FinanceService
        from app.services.finance.utils import FREQUENCY_STEPS

        assert set(_FREQUENCY_LABELS) == set(FREQUENCY_STEPS)
        # The validator also accepts "once" - a dated one-off debt is
        # storable and forecastable (single occurrence) but has no step.
        from app.services.finance.constants import ONE_TIME_FREQUENCY

        assert set(FinanceService._STREAM_FREQUENCIES) == (
            set(FREQUENCY_STEPS) | {ONE_TIME_FREQUENCY}
        )

    def test_everything_detection_measures_can_be_stepped(self) -> None:
        """Detection may know FEWER cadences than the forecast can step -
        that is fine, the user states those by hand. The reverse is not:
        measuring a cadence nothing can step is how a detected bill goes
        missing from the projection."""
        from app.services.finance.domains.detection.recurring.cadence import _CADENCES
        from app.services.finance.utils import FREQUENCY_STEPS

        assert {label for _days, label in _CADENCES} <= set(FREQUENCY_STEPS)
