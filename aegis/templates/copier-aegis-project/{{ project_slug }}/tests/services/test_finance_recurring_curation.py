"""Tests for recurring-stream curation: manual bills/income + confirm/mute."""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService

OWNER = 1


class TestManualStreams:
    @pytest.mark.asyncio
    async def test_create_a_manual_bill(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        stream = await svc.create_recurring_stream(
            owner_user_id=OWNER,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=185_000,
            next_expected_date=date(2026, 8, 1),
        )

        assert stream.source == "user"
        assert stream.is_user_confirmed is True
        assert stream.status == "mature"
        assert stream.is_active is True
        assert stream.amount_is_variable is False
        assert stream.average_amount == 185_000

    @pytest.mark.asyncio
    async def test_create_income_and_list_soonest_first(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await svc.create_recurring_stream(
            owner_user_id=OWNER,
            name="Paycheck",
            direction="inflow",
            frequency="biweekly",
            expected_amount=250_000,
            next_expected_date=date(2026, 8, 8),
        )
        await svc.create_recurring_stream(
            owner_user_id=OWNER,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=185_000,
            next_expected_date=date(2026, 8, 1),
        )

        streams = await svc.list_recurring(owner_user_id=OWNER)
        assert [s.name for s in streams] == ["Rent", "Paycheck"]

    @pytest.mark.asyncio
    async def test_standalone_owner_stores_under_the_sentinel(
        self, async_db_session: AsyncSession
    ) -> None:
        """NULL-owner installs store streams under 0, like insights do."""
        svc = FinanceService(async_db_session)
        stream = await svc.create_recurring_stream(
            owner_user_id=None,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=185_000,
            next_expected_date=date(2026, 8, 1),
        )
        assert stream.owner_user_id == 0

    @pytest.mark.asyncio
    async def test_invalid_direction_is_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        with pytest.raises(ValueError):
            await svc.create_recurring_stream(
                owner_user_id=OWNER,
                name="Rent",
                direction="sideways",
                frequency="monthly",
                expected_amount=185_000,
                next_expected_date=date(2026, 8, 1),
            )


class TestConfirmAndMute:
    @pytest.mark.asyncio
    async def test_confirm_marks_a_detected_stream(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        created = await svc.create_recurring_stream(
            owner_user_id=OWNER,
            name="Spotify",
            direction="outflow",
            frequency="monthly",
            expected_amount=1_199,
            next_expected_date=date(2026, 8, 16),
        )
        created.is_user_confirmed = False  # simulate a detected row
        async_db_session.add(created)
        await async_db_session.flush()

        confirmed = await svc.confirm_recurring(created.id, owner_user_id=OWNER)
        assert confirmed is not None and confirmed.is_user_confirmed is True

    @pytest.mark.asyncio
    async def test_unmute_reverses_mute(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        created = await svc.create_recurring_stream(
            owner_user_id=OWNER,
            name="Spotify",
            direction="outflow",
            frequency="monthly",
            expected_amount=1_199,
            next_expected_date=date(2026, 8, 16),
        )
        await svc.mute_recurring(created.id, owner_user_id=OWNER)
        unmuted = await svc.unmute_recurring(created.id, owner_user_id=OWNER)
        assert unmuted is not None and unmuted.is_muted is False


class TestTransferStreamsAreNotBills:
    @pytest.mark.asyncio
    async def test_listing_and_rollup_exclude_transfer_rhythms(
        self, async_db_session: AsyncSession
    ) -> None:
        """A monthly card-payment stream is an internal transfer, not a bill:
        it must not appear in Bills & Income nor inflate the monthly cost."""
        from app.services.finance.models import FinanceRecurringStream

        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            owner_user_id=OWNER,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        real_bill = await svc.create_recurring_stream(
            owner_user_id=OWNER,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=185_000,
            next_expected_date=date(2026, 8, 1),
        )
        card_payment = FinanceRecurringStream(
            owner_user_id=OWNER,
            account_id=account.id,
            name="AUTOPAY PAYMENT THANK YOU",
            normalized_payee="AUTOPAY PAYMENT THANK YOU",
            direction="outflow",
            frequency="monthly",
            average_amount=1_121_259,
            currency="usd",
            status="mature",
            source="derived",
        )
        async_db_session.add(card_payment)
        await async_db_session.flush()
        leg = await svc.create_transaction(
            owner_user_id=OWNER,
            account_id=account.id,
            amount=-1_121_259,
            txn_date=date(2026, 7, 1),
            name="AUTOPAY PAYMENT THANK YOU",
        )
        leg.is_transfer = True
        leg.recurring_stream_id = card_payment.id
        async_db_session.add(leg)
        await async_db_session.flush()

        streams = await svc.list_recurring(owner_user_id=OWNER)
        transfer_ids = await svc.transfer_stream_ids([s.id for s in streams])

        kept = [s for s in streams if s.id not in transfer_ids]
        assert [s.id for s in kept] == [real_bill.id]


class TestStreamCategories:
    @pytest.mark.asyncio
    async def test_category_comes_from_the_dominant_member_transaction(
        self, async_db_session: AsyncSession
    ) -> None:
        """A stream's own ``category_id`` is a provider field the local
        detector never fills, so the category is read off its member
        transactions - the most common one wins."""
        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            owner_user_id=OWNER,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        stream = await svc.create_recurring_stream(
            owner_user_id=OWNER,
            name="ComEd",
            direction="outflow",
            frequency="monthly",
            expected_amount=10_000,
            next_expected_date=date(2026, 8, 1),
        )
        utilities = await svc.get_or_create_category_from_hint(
            "Bills & Utilities:Power"
        )
        stray = await svc.get_or_create_category_from_hint("Shopping:Misc")
        for day, category in ((1, utilities), (2, utilities), (3, stray)):
            txn = await svc.create_transaction(
                owner_user_id=OWNER,
                account_id=account.id,
                amount=-10_000,
                txn_date=date(2026, 7, day),
                name="ComEd",
            )
            txn.recurring_stream_id = stream.id
            txn.category_id = category.id
            async_db_session.add(txn)
        await async_db_session.flush()

        names = await svc.stream_category_names([stream.id])
        assert names[stream.id] == utilities.name
        assert await svc.stream_category_names([]) == {}
