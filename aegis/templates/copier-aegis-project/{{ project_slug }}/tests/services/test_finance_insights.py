"""Tests for recurring-stream detection + "wasting money" insights (FIN-27).

Covers the ticket's acceptance scenarios: a Netflix-style subscription with a
price bump → stream detected + a single price_hike (idempotent, mutable); a
bank fee → fee insight; a 2x category month → overspend insight; too little
history → no insight, no crash; dismissal survives a re-run.
"""

from datetime import date, timedelta

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import (
    detect_recurring,
    generate_insights,
    stream_staleness,
)
from app.services.finance.models import (
    FinanceCategory,
    FinanceInsight,
    FinanceRecurringStream,
)
from app.services.finance.seeds import demo_seed
from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_txn

_MONTH_STARTS = [date(2026, m, 15) for m in range(1, 8)]  # Jan..Jul 15th
_TODAY = date(2026, 7, 20)


async def _txn(svc, account_id, amount, day, name, category_id=None):
    return await seed_txn(
        svc, account_id, amount, day, name=name, category_id=category_id
    )


async def _stream(
    session: AsyncSession,
    *,
    account_id: int,
    last_date: date,
    next_expected_date: date,
    name: str = "ACME UTILITIES",
    direction: str = "outflow",
    frequency: str = "monthly",
    amount: int = 5_000,
    is_muted: bool = False,
    is_user_confirmed: bool = False,
) -> FinanceRecurringStream:
    """A mature detected stream, written directly so cadence is under test
    control (detection's own date math is covered by its own tests).

    Tests that model a REAL household bill pass ``is_user_confirmed`` -
    under the record/proposal split, an unconfirmed stream counts for
    nothing (no missed-payment nag, no runway math, no forecast)."""
    stream = FinanceRecurringStream(
        owner_user_id=1,
        account_id=account_id,
        direction=direction,
        normalized_payee=name.lower(),
        name=name,
        frequency=frequency,
        average_amount=amount,
        last_amount=amount,
        expected_amount=amount,
        currency="usd",
        first_date=last_date,
        last_date=last_date,
        next_expected_date=next_expected_date,
        occurrence_count=6,
        status="mature",
        source="derived",
        is_user_confirmed=is_user_confirmed,
        is_muted=is_muted,
    )
    session.add(stream)
    await session.flush()
    return stream


async def _insights_of(
    session: AsyncSession, insight_type: str
) -> list[FinanceInsight]:
    return list(
        (
            await session.exec(
                select(FinanceInsight).where(
                    FinanceInsight.insight_type == insight_type
                )
            )
        ).all()
    )


class TestRecurringDetectionByPayee:
    """An assigned payee (FinanceMerchant) is the grouping key, so a bank
    descriptor that drifts no longer splits one bill into several."""

    @pytest.mark.asyncio
    async def test_drifting_descriptors_with_one_payee_are_one_stream(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        merchant = await svc.create_merchant("Google", owner_user_id=1)
        # The real shapes this failed on: a moved space, a changed card
        # ref, and an embedded statement date that made every month unique.
        descriptors = [
            "YOUTUBEPREMIG.CO/HELPPAY# CA XXXX--X3007",
            "YOUTUBEPREMI G.CO/HELPPAY# CA XXXX3007",
            "YouTubePremi g.co/helppay# CA 05/19",
            "YouTubePremi g.co/helppay# CA 06/19",
        ]
        for day, desc in zip(_MONTH_STARTS[:4], descriptors):
            txn = await _txn(svc, account.id, -2299, day, desc)
            txn.merchant_id = merchant.id
            async_db_session.add(txn)
        await async_db_session.flush()

        detected = await detect_recurring(async_db_session, owner_user_id=1)

        assert detected.detected == 1
        stream = (await async_db_session.exec(select(FinanceRecurringStream))).one()
        assert stream.merchant_id == merchant.id
        # Named for the payee, not whichever descriptor happened to be last.
        assert stream.name == "Google"
        assert stream.occurrence_count == 4
        assert stream.frequency == "monthly"

    @pytest.mark.asyncio
    async def test_rekeying_retires_the_stream_it_left_behind(
        self, async_db_session: AsyncSession
    ) -> None:
        """The old descriptor-keyed row must not linger: it would show as a
        permanent duplicate in Bills & Income and double-count in the
        monthly rollup."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, -2299, day, "ACME SUBSCRIPTION")
            for day in _MONTH_STARTS[:4]
        ]
        await detect_recurring(async_db_session, owner_user_id=1)
        original = (await async_db_session.exec(select(FinanceRecurringStream))).one()

        # Now name a payee for them - exactly what the register's picker does.
        merchant = await svc.create_merchant("Acme", owner_user_id=1)
        for txn in txns:
            txn.merchant_id = merchant.id
            async_db_session.add(txn)
        await async_db_session.flush()
        result = await detect_recurring(async_db_session, owner_user_id=1)

        assert result.pruned == 1
        live = (
            await async_db_session.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).all()
        assert [s.name for s in live] == ["Acme"]
        # HARD-deleted, not soft: a proposal row is never load-bearing,
        # and the soft-deleted ghost this used to assert is exactly what
        # kept unique keys occupied and enabled resurrection.
        assert (await async_db_session.get(FinanceRecurringStream, original.id)) is None

    @pytest.mark.asyncio
    async def test_rekeying_keeps_the_curation_the_user_gave_it(
        self, async_db_session: AsyncSession
    ) -> None:
        """A CONFIRMED bill is off limits to detection entirely.

        This used to assert the opposite - that naming a payee re-keys and
        renames the bill - and that was the right call while detection was
        allowed to maintain curated rows. It is not any more: a re-scan
        must not be able to touch a bill the user settled, because "it
        only ever improves things" is not a promise worth betting a
        forecast on. Renaming a real bill is now an explicit act (the
        bill's own edit dialog).

        An UNCONFIRMED stream is still re-keyed and renamed freely - see
        test_rekeying_retires_the_stream_it_left_behind just above.
        """
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, -2299, day, "ACME SUBSCRIPTION")
            for day in _MONTH_STARTS[:4]
        ]
        await detect_recurring(async_db_session, owner_user_id=1)
        original = (await async_db_session.exec(select(FinanceRecurringStream))).one()
        original.is_user_confirmed = True
        original.is_muted = True
        async_db_session.add(original)
        await async_db_session.flush()

        merchant = await svc.create_merchant("Acme", owner_user_id=1)
        for txn in txns:
            txn.merchant_id = merchant.id
            async_db_session.add(txn)
        await async_db_session.flush()
        await detect_recurring(async_db_session, owner_user_id=1)

        live = (
            await async_db_session.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).all()
        assert len(live) == 1
        assert live[0].id == original.id  # the same row, untouched
        assert live[0].name == "ACME SUBSCRIPTION"  # not renamed to "Acme"
        assert live[0].is_user_confirmed is True
        assert live[0].is_muted is True

    @pytest.mark.asyncio
    async def test_pruning_spares_a_hand_entered_bill(
        self, async_db_session: AsyncSession
    ) -> None:
        """A bill the user typed in has no matched transactions yet by
        design - retiring it would throw away something only they could
        recreate."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        manual = await svc.create_recurring_stream(
            owner_user_id=1,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=185000,
            next_expected_date=date(2026, 8, 1),
            account_id=account.id,
        )

        result = await detect_recurring(async_db_session, owner_user_id=1)

        assert result.pruned == 0
        kept = await async_db_session.get(FinanceRecurringStream, manual.id)
        assert kept.deleted_at is None

    @pytest.mark.asyncio
    async def test_same_descriptors_without_a_payee_still_split(
        self, async_db_session: AsyncSession
    ) -> None:
        """The descriptor fallback is unchanged - this is the behavior the
        payee assignment exists to fix, and it must still be what happens
        for anything nobody has named a payee for."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for day in _MONTH_STARTS[:4]:
            await _txn(svc, account.id, -2299, day, f"YouTubePremi CA {day:%m/%d}")

        detected = await detect_recurring(async_db_session, owner_user_id=1)

        # Every descriptor unique -> no group reaches MIN_OCCURRENCES.
        assert detected.detected == 0


class TestRecurringDetection:
    @pytest.mark.asyncio
    async def test_netflix_subscription_detected_with_price_hike(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for day in _MONTH_STARTS[:6]:
            await _txn(svc, account.id, -1549, day, "NETFLIX")
        await _txn(svc, account.id, -1799, _MONTH_STARTS[6], "NETFLIX")

        detected = await detect_recurring(async_db_session, owner_user_id=1)
        assert detected.detected == 1
        stream = (await async_db_session.exec(select(FinanceRecurringStream))).one()
        assert stream.frequency == "monthly"
        assert stream.is_subscription is True
        assert stream.average_amount == 1549
        assert stream.last_amount == 1799

        first = await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        assert first.created == 1
        hike = (
            await async_db_session.exec(
                select(FinanceInsight).where(
                    FinanceInsight.insight_type == "price_hike"
                )
            )
        ).one()
        assert hike.detected_amount == 1799

        # Idempotent: the same price does not re-alert.
        again = await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        assert again.created == 0

    @pytest.mark.asyncio
    async def test_muting_suppresses_price_hike(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for day in _MONTH_STARTS[:6]:
            await _txn(svc, account.id, -1549, day, "NETFLIX")
        await _txn(svc, account.id, -1799, _MONTH_STARTS[6], "NETFLIX")
        await detect_recurring(async_db_session, owner_user_id=1)
        stream = (await async_db_session.exec(select(FinanceRecurringStream))).one()

        await svc.mute_recurring(stream.id, owner_user_id=1)
        result = await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        assert result.created == 0  # muted -> no hike

    @pytest.mark.asyncio
    async def test_irregular_payee_not_a_stream(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        # Three charges, but wildly irregular gaps -> no stable cadence.
        for day, amt in [
            (date(2026, 1, 1), -500),
            (date(2026, 1, 3), -500),
            (date(2026, 5, 20), -500),
        ]:
            await _txn(svc, account.id, amt, day, "RANDOM SHOP")
        result = await detect_recurring(async_db_session, owner_user_id=1)
        assert result.detected == 0


class TestInsights:
    @pytest.mark.asyncio
    async def test_fee_insight(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _txn(svc, account.id, -3500, date(2026, 7, 3), "MONTHLY SERVICE FEE")
        result = await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        assert result.created == 1
        fee = (
            await async_db_session.exec(
                select(FinanceInsight).where(
                    FinanceInsight.insight_type == "fee_charged"
                )
            )
        ).one()
        assert fee.detected_amount == -3500

    @pytest.mark.asyncio
    async def test_an_old_fee_outside_the_lookback_stays_silent(
        self, async_db_session: AsyncSession
    ) -> None:
        """A historical import carries years of old fees; alerting on all of
        them buries the real, recent ones."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _txn(svc, account.id, -3500, date(2026, 1, 5), "MONTHLY SERVICE FEE")

        result = await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        assert result.created == 0

        # 0 disables the window and processes full history.
        result = await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20), lookback_days=0
        )
        assert result.created == 1

    @pytest.mark.asyncio
    async def test_overspend_insight(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        category = FinanceCategory(
            owner_user_id=1, name="Dining", slug="dining", classification="expense"
        )
        async_db_session.add(category)
        await async_db_session.flush()
        # 3 prior full months at ~$100, current month at $250 (> 1.5x).
        for month in (4, 5, 6):
            await _txn(
                svc,
                account.id,
                -10000,
                date(2026, month, 10),
                "DINING",
                category_id=category.id,
            )
        await _txn(
            svc,
            account.id,
            -25000,
            date(2026, 7, 10),
            "DINING",
            category_id=category.id,
        )
        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        overspend = (
            await async_db_session.exec(
                select(FinanceInsight).where(
                    FinanceInsight.insight_type == "overspend_category"
                )
            )
        ).all()
        assert len(overspend) == 1
        assert overspend[0].detected_amount == 25000

    @pytest.mark.asyncio
    async def test_insufficient_history_no_overspend(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        category = FinanceCategory(
            owner_user_id=1, name="Dining", slug="dining", classification="expense"
        )
        async_db_session.add(category)
        await async_db_session.flush()
        # Only 1 prior month + current -> not enough history, no crash.
        await _txn(
            svc,
            account.id,
            -10000,
            date(2026, 6, 10),
            "DINING",
            category_id=category.id,
        )
        await _txn(
            svc,
            account.id,
            -25000,
            date(2026, 7, 10),
            "DINING",
            category_id=category.id,
        )
        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        overspend = (
            await async_db_session.exec(
                select(FinanceInsight).where(
                    FinanceInsight.insight_type == "overspend_category"
                )
            )
        ).all()
        assert overspend == []

    @pytest.mark.asyncio
    async def test_dismiss_survives_rerun(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _txn(svc, account.id, -3500, date(2026, 7, 3), "SERVICE FEE")
        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        fee = (
            await async_db_session.exec(
                select(FinanceInsight).where(
                    FinanceInsight.insight_type == "fee_charged"
                )
            )
        ).one()
        dismissed = await svc.dismiss_insight(fee.id, owner_user_id=1)
        assert dismissed is not None and dismissed.status == "dismissed"

        # Re-running must not resurrect the dismissed insight.
        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        rows = (
            await async_db_session.exec(
                select(FinanceInsight).where(
                    FinanceInsight.insight_type == "fee_charged"
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "dismissed"


class TestLargeTransaction:
    """A single outflow far outside the account's own recent norm."""

    async def _with_baseline(self, svc, count: int = 12) -> int:
        """An account carrying ``count`` ordinary $50 outflows, all older than
        the candidate window so they only ever act as the baseline."""
        account = await _account(svc)
        for index in range(count):
            await _txn(
                svc,
                account.id,
                -5_000,
                _TODAY - timedelta(days=40 + index * 4),
                f"CORNER STORE {index}",
            )
        return account.id

    @pytest.mark.asyncio
    async def test_outlier_against_a_solid_baseline_is_flagged(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account_id = await self._with_baseline(svc)
        await _txn(
            svc, account_id, -40_000, _TODAY - timedelta(days=5), "APPLIANCE WORLD"
        )

        await generate_insights(async_db_session, owner_user_id=1, today=_TODAY)

        rows = await _insights_of(async_db_session, "large_transaction")
        assert len(rows) == 1
        assert rows[0].severity == "warning"
        assert rows[0].detected_amount == -40_000
        assert rows[0].related_account_id == account_id

    @pytest.mark.asyncio
    async def test_extreme_outlier_is_critical(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account_id = await self._with_baseline(svc)
        await _txn(
            svc, account_id, -60_000, _TODAY - timedelta(days=5), "APPLIANCE WORLD"
        )

        await generate_insights(async_db_session, owner_user_id=1, today=_TODAY)

        rows = await _insights_of(async_db_session, "large_transaction")
        assert len(rows) == 1
        assert rows[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_ordinary_spend_stays_silent(
        self, async_db_session: AsyncSession
    ) -> None:
        """Above the account's median but under the absolute floor: a $150
        charge is not news, however quiet the account usually is."""
        svc = FinanceService(async_db_session)
        account_id = await self._with_baseline(svc)
        await _txn(
            svc, account_id, -15_000, _TODAY - timedelta(days=5), "APPLIANCE WORLD"
        )

        await generate_insights(async_db_session, owner_user_id=1, today=_TODAY)

        assert await _insights_of(async_db_session, "large_transaction") == []

    @pytest.mark.asyncio
    async def test_thin_history_falls_back_to_the_absolute_floor(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account_id = await self._with_baseline(svc, count=3)
        # Four times the median, but too little history to trust that median.
        await _txn(svc, account_id, -30_000, _TODAY - timedelta(days=5), "FURNITURE")

        await generate_insights(async_db_session, owner_user_id=1, today=_TODAY)
        assert await _insights_of(async_db_session, "large_transaction") == []

        await _txn(svc, account_id, -60_000, _TODAY - timedelta(days=4), "FURNITURE")
        await generate_insights(async_db_session, owner_user_id=1, today=_TODAY)

        rows = await _insights_of(async_db_session, "large_transaction")
        assert len(rows) == 1
        assert rows[0].detected_amount == -60_000

    @pytest.mark.asyncio
    async def test_recurring_members_are_never_outliers(
        self, async_db_session: AsyncSession
    ) -> None:
        """A mortgage payment is large every month; price_hike owns streams."""
        svc = FinanceService(async_db_session)
        account_id = await self._with_baseline(svc)
        big = await _txn(
            svc, account_id, -218_400, _TODAY - timedelta(days=5), "MORTGAGE"
        )
        stream = await _stream(
            async_db_session,
            account_id=account_id,
            name="MORTGAGE",
            last_date=_TODAY - timedelta(days=5),
            next_expected_date=_TODAY + timedelta(days=25),
            amount=218_400,
        )
        big.recurring_stream_id = stream.id
        async_db_session.add(big)
        await async_db_session.flush()

        await generate_insights(async_db_session, owner_user_id=1, today=_TODAY)

        assert await _insights_of(async_db_session, "large_transaction") == []

    @pytest.mark.asyncio
    async def test_rerun_does_not_duplicate(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account_id = await self._with_baseline(svc)
        await _txn(
            svc, account_id, -40_000, _TODAY - timedelta(days=5), "APPLIANCE WORLD"
        )

        first = await generate_insights(async_db_session, owner_user_id=1, today=_TODAY)
        again = await generate_insights(async_db_session, owner_user_id=1, today=_TODAY)

        assert first.created == 1
        assert again.created == 0
        assert len(await _insights_of(async_db_session, "large_transaction")) == 1


class TestMissedRecurring:
    """A mature stream whose expected charge never showed up."""

    @pytest.mark.asyncio
    async def test_overdue_outflow_fires_after_the_grace_window(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _stream(
            async_db_session,
            is_user_confirmed=True,
            account_id=account.id,
            last_date=date(2026, 6, 1),
            next_expected_date=date(2026, 7, 1),
        )

        # 2026-07-10 is nine days past due; monthly grace is five.
        result = await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 10)
        )

        rows = await _insights_of(async_db_session, "missed_recurring")
        assert result.created == 1
        assert len(rows) == 1
        assert rows[0].severity == "warning"
        assert rows[0].related_stream_id == stream.id
        assert rows[0].detected_amount == 5_000

    @pytest.mark.asyncio
    async def test_inside_the_grace_window_stays_silent(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _stream(
            async_db_session,
            account_id=account.id,
            last_date=date(2026, 6, 1),
            next_expected_date=date(2026, 7, 1),
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 4)
        )

        assert await _insights_of(async_db_session, "missed_recurring") == []

    @pytest.mark.asyncio
    async def test_weekly_streams_get_a_tighter_grace(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _stream(
            async_db_session,
            account_id=account.id,
            name="WEEKLY PAYOUT",
            direction="inflow",
            frequency="weekly",
            last_date=date(2026, 6, 24),
            next_expected_date=date(2026, 7, 1),
        )

        # Four days late: past the weekly grace of three, inside the monthly five.
        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 5)
        )

        assert len(await _insights_of(async_db_session, "missed_recurring")) == 1

    @pytest.mark.asyncio
    async def test_a_stream_dead_since_before_the_lookback_is_not_chased(
        self, async_db_session: AsyncSession
    ) -> None:
        """Imported history leaves zombie streams whose expected date passed
        years ago. Those are cancelled subscriptions, not missed bills."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _stream(
            async_db_session,
            account_id=account.id,
            last_date=date(2021, 2, 15),
            next_expected_date=date(2021, 3, 18),
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "missed_recurring") == []

    @pytest.mark.asyncio
    async def test_a_weekly_spending_habit_is_not_a_missed_bill(
        self, async_db_session: AsyncSession
    ) -> None:
        """Detection finds a weekly cadence in a coffee habit. "You have not
        been to Starbucks" is not an alert, however overdue it looks."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _stream(
            async_db_session,
            account_id=account.id,
            name="STARBUCKS",
            frequency="weekly",
            last_date=date(2026, 6, 1),
            next_expected_date=date(2026, 6, 8),
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "missed_recurring") == []

    @pytest.mark.asyncio
    async def test_missing_income_is_critical(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _stream(
            async_db_session,
            account_id=account.id,
            name="PAYROLL DIRECT DEPOSIT",
            direction="inflow",
            last_date=date(2026, 6, 1),
            next_expected_date=date(2026, 7, 1),
            amount=419_500,
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 10)
        )

        rows = await _insights_of(async_db_session, "missed_recurring")
        assert len(rows) == 1
        assert rows[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_a_stream_paid_on_time_never_fires(
        self, async_db_session: AsyncSession
    ) -> None:
        """Detection advances ``next_expected_date`` when a charge lands; a
        stream whose last charge is at or after the due date is current."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _stream(
            async_db_session,
            account_id=account.id,
            last_date=date(2026, 7, 2),
            next_expected_date=date(2026, 7, 1),
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "missed_recurring") == []

    @pytest.mark.asyncio
    async def test_muted_streams_are_skipped(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _stream(
            async_db_session,
            account_id=account.id,
            last_date=date(2026, 6, 1),
            next_expected_date=date(2026, 7, 1),
            is_muted=True,
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 10)
        )

        assert await _insights_of(async_db_session, "missed_recurring") == []

    @pytest.mark.asyncio
    async def test_rerun_does_not_duplicate(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await _stream(
            async_db_session,
            is_user_confirmed=True,
            account_id=account.id,
            last_date=date(2026, 6, 1),
            next_expected_date=date(2026, 7, 1),
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 10)
        )
        again = await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 11)
        )

        assert again.created == 0
        assert len(await _insights_of(async_db_session, "missed_recurring")) == 1


class TestStreamStaleness:
    """Pure function, no DB - a FinanceRecurringStream built in memory is
    enough. Same recency logic TestMissedRecurring exercises indirectly
    through generate_insights; these pin the "fresh"/"overdue"/"stale"
    boundary the Bills & Income tab's dot now reads directly."""

    def _stream(
        self,
        *,
        next_expected_date: date | None,
        last_date: date | None,
        frequency: str = "monthly",
    ) -> FinanceRecurringStream:
        return FinanceRecurringStream(
            owner_user_id=1,
            account_id=1,
            direction="outflow",
            normalized_payee="acme",
            name="ACME UTILITIES",
            frequency=frequency,
            average_amount=5_000,
            last_amount=5_000,
            expected_amount=5_000,
            currency="usd",
            first_date=last_date,
            last_date=last_date,
            next_expected_date=next_expected_date,
            occurrence_count=6,
            status="mature",
            source="derived",
        )

    def test_no_next_expected_date_is_fresh(self) -> None:
        """early_detection streams have no resolved cadence yet - nothing
        to be overdue against."""
        stream = self._stream(next_expected_date=None, last_date=None)
        assert stream_staleness(stream, date(2026, 7, 20), None) == "fresh"

    def test_within_grace_window_is_fresh(self) -> None:
        stream = self._stream(
            next_expected_date=date(2026, 7, 1), last_date=date(2026, 6, 1)
        )
        assert stream_staleness(stream, date(2026, 7, 4), None) == "fresh"

    def test_arrived_late_is_still_fresh(self) -> None:
        stream = self._stream(
            next_expected_date=date(2026, 7, 1), last_date=date(2026, 7, 8)
        )
        assert stream_staleness(stream, date(2026, 7, 10), None) == "fresh"

    def test_past_grace_with_no_match_is_overdue(self) -> None:
        stream = self._stream(
            next_expected_date=date(2026, 7, 1), last_date=date(2026, 6, 1)
        )
        assert stream_staleness(stream, date(2026, 7, 10), None) == "overdue"

    def test_past_the_lookback_floor_is_stale(self) -> None:
        stream = self._stream(
            next_expected_date=date(2021, 3, 18), last_date=date(2021, 2, 15)
        )
        floor = date(2026, 7, 20) - timedelta(days=90)
        assert stream_staleness(stream, date(2026, 7, 20), floor) == "stale"

    def test_no_floor_never_reads_stale(self) -> None:
        """lookback disabled (floor=None) - even a years-dead stream reads
        overdue, not stale, matching _missed_recurring's own floor=None
        behavior (no zombie skip at all)."""
        stream = self._stream(
            next_expected_date=date(2021, 3, 18), last_date=date(2021, 2, 15)
        )
        assert stream_staleness(stream, date(2026, 7, 20), None) == "overdue"


class TestAgainstTheDemoDataset:
    """Every rule has to stay quiet on healthy data.

    The demo dataset is months of deliberately ordinary activity: jittered
    groceries, coffee, subscriptions paid on time. A rule that fires on any of
    that is a rule that will bury a real finding, so this pins the silence
    rather than any particular alert.
    """

    @pytest.mark.asyncio
    async def test_ordinary_activity_does_not_produce_an_alert_storm(
        self, async_db_session: AsyncSession
    ) -> None:
        await demo_seed.seed_demo(async_db_session, owner_user_id=1)
        await async_db_session.commit()

        first = await generate_insights(async_db_session, owner_user_id=1)
        second = await generate_insights(async_db_session, owner_user_id=1)
        await async_db_session.commit()

        rows = (await async_db_session.exec(select(FinanceInsight))).all()
        # Seeding runs the rules on its way through the import lane, so both
        # passes here are already repeats and must add nothing.
        assert first.created == 0
        assert second.created == 0
        assert len(rows) <= 5, (
            f"rules are firing on ordinary activity: {[r.title for r in rows]}"
        )
        # Jittered groceries and coffee are never outliers.
        assert await _insights_of(async_db_session, "large_transaction") == []
        # Every seeded stream is paid up to date.
        assert await _insights_of(async_db_session, "missed_recurring") == []


class TestMissedRecurringCommitmentGate:
    """Only commitments are chased. A shopping habit that happens to tick at
    a bill-like cadence (Dollar General, twice a month) is not a bill; the
    stream's own signals (variable amount, not a subscription, never
    confirmed) say so."""

    @pytest.mark.asyncio
    async def test_a_variable_amount_merchant_habit_is_not_chased(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _stream(
            async_db_session,
            account_id=account.id,
            name="DOLLAR GENERAL",
            frequency="semi_monthly",
            last_date=date(2026, 6, 29),
            next_expected_date=date(2026, 7, 16),
        )
        stream.amount_is_variable = True
        stream.expected_amount = None
        async_db_session.add(stream)
        await async_db_session.flush()

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 26)
        )

        assert await _insights_of(async_db_session, "missed_recurring") == []

    @pytest.mark.asyncio
    async def test_a_confirmed_variable_stream_is_chased_again(
        self, async_db_session: AsyncSession
    ) -> None:
        """User confirmation outranks the variable-amount heuristic."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _stream(
            async_db_session,
            account_id=account.id,
            name="CLEANING SERVICE",
            frequency="semi_monthly",
            last_date=date(2026, 6, 29),
            next_expected_date=date(2026, 7, 16),
        )
        stream.amount_is_variable = True
        stream.is_user_confirmed = True
        async_db_session.add(stream)
        await async_db_session.flush()

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 26)
        )

        assert len(await _insights_of(async_db_session, "missed_recurring")) == 1

    @pytest.mark.asyncio
    async def test_a_user_created_bill_is_chased_at_any_cadence(
        self, async_db_session: AsyncSession
    ) -> None:
        """A hand-entered weekly bill must not be dismissed as a habit."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _stream(
            async_db_session,
            account_id=account.id,
            name="LAWN CARE",
            frequency="weekly",
            last_date=date(2026, 7, 10),
            next_expected_date=date(2026, 7, 17),
        )
        stream.source = "user"
        stream.is_user_confirmed = True
        async_db_session.add(stream)
        await async_db_session.flush()

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 26)
        )

        assert len(await _insights_of(async_db_session, "missed_recurring")) == 1

    @pytest.mark.asyncio
    async def test_an_internal_transfer_rhythm_is_never_a_missed_bill(
        self, async_db_session: AsyncSession
    ) -> None:
        """A monthly checking->savings sweep is money moved, not money owed."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        stream = await _stream(
            async_db_session,
            account_id=account.id,
            name="Transfer to Savings",
            last_date=date(2026, 6, 20),
            next_expected_date=date(2026, 7, 21),
        )
        leg = await _txn(
            svc, account.id, -75_000, date(2026, 6, 20), "Transfer to Savings"
        )
        leg.is_transfer = True
        leg.recurring_stream_id = stream.id
        async_db_session.add(leg)
        await async_db_session.flush()

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 28)
        )

        assert await _insights_of(async_db_session, "missed_recurring") == []


class TestCreditCardRules:
    """The predefined credit checks: past due, minimum vs cash, APR, limit.

    The point of these rules is that "your credit card is in trouble" is
    something the system is told to look for, never something a model has to
    happen to notice.
    """

    async def _cash(self, svc, *, available: int):
        account = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
            current_balance=available,
        )
        return account

    async def _card(
        self,
        session: AsyncSession,
        svc,
        *,
        balance: int = 4_429_651,
        credit_limit: int | None = None,
        minimum: int | None = None,
        due: date | None = None,
        aprs: list | None = None,
        is_overdue: bool | None = None,
        last_statement: int | None = None,
        last_payment: int | None = None,
    ):
        from app.services.finance.models import FinanceLiabilityDetail

        card = await svc.create_manual_account(
            name="Amex Gold",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
            current_balance=balance,
        )
        if credit_limit is not None:
            card.credit_limit = credit_limit
            session.add(card)
        session.add(
            FinanceLiabilityDetail(
                owner_user_id=1,
                account_id=card.id,
                liability_type="credit",
                minimum_payment_amount=minimum,
                next_payment_due_date=due,
                aprs=aprs or [],
                is_overdue=is_overdue,
                last_statement_balance=last_statement,
                last_payment_amount=last_payment,
            )
        )
        await session.flush()
        return card

    @pytest.mark.asyncio
    async def test_minimum_payment_beyond_cash_is_critical(
        self, async_db_session: AsyncSession
    ) -> None:
        """The AmEx scenario: $1,801.11 due against $1,203.96 of cash."""
        svc = FinanceService(async_db_session)
        await self._cash(svc, available=120_396)
        await self._card(
            async_db_session,
            svc,
            minimum=180_111,
            due=date(2026, 7, 25),
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        rows = await _insights_of(async_db_session, "min_payment_gap")
        assert len(rows) == 1
        assert rows[0].severity == "critical"
        assert "short $597.15" in rows[0].body

    @pytest.mark.asyncio
    async def test_a_covered_minimum_stays_silent(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._cash(svc, available=500_000)
        await self._card(async_db_session, svc, minimum=180_111, due=date(2026, 7, 25))

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "min_payment_gap") == []

    @pytest.mark.asyncio
    async def test_a_far_off_due_date_is_not_yet_a_gap(
        self, async_db_session: AsyncSession
    ) -> None:
        """A payday can land before a due date a month out; alerting now
        would be noise."""
        svc = FinanceService(async_db_session)
        await self._cash(svc, available=100)
        await self._card(async_db_session, svc, minimum=180_111, due=date(2026, 9, 20))

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "min_payment_gap") == []

    @pytest.mark.asyncio
    async def test_an_expensive_carried_balance_is_flagged(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._card(
            async_db_session,
            svc,
            aprs=[
                {
                    "apr_type": "purchase_apr",
                    "apr_percentage_bps": 2_999,
                    "balance_subject_to_apr": 4_341_575,
                }
            ],
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        rows = await _insights_of(async_db_session, "high_apr_carry")
        assert len(rows) == 1
        assert "29.99%" in rows[0].title

    @pytest.mark.asyncio
    async def test_a_card_paid_in_full_is_never_flagged_for_apr(
        self, async_db_session: AsyncSession
    ) -> None:
        """A 30% APR on a card that never carries a balance costs nothing."""
        svc = FinanceService(async_db_session)
        await self._card(
            async_db_session,
            svc,
            aprs=[{"apr_type": "purchase_apr", "apr_percentage_bps": 2_999}],
            last_statement=250_000,
            last_payment=250_000,
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "high_apr_carry") == []

    @pytest.mark.asyncio
    async def test_an_unpaid_statement_is_proof_of_carrying(
        self, async_db_session: AsyncSession
    ) -> None:
        """AMEX-style institutions omit balance_subject_to_apr; a statement
        not paid in full is the fallback proof."""
        svc = FinanceService(async_db_session)
        await self._card(
            async_db_session,
            svc,
            aprs=[{"apr_type": "purchase_apr", "apr_percentage_bps": 2_999}],
            last_statement=4_341_575,
            last_payment=180_111,
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert len(await _insights_of(async_db_session, "high_apr_carry")) == 1

    @pytest.mark.asyncio
    async def test_a_cheap_rate_stays_silent(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._card(
            async_db_session,
            svc,
            aprs=[
                {
                    "apr_type": "purchase_apr",
                    "apr_percentage_bps": 799,
                    "balance_subject_to_apr": 4_341_575,
                }
            ],
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "high_apr_carry") == []

    @pytest.mark.asyncio
    async def test_a_nearly_maxed_card_warns_then_goes_critical(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._card(async_db_session, svc, balance=85_000, credit_limit=100_000)

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        rows = await _insights_of(async_db_session, "credit_utilization")
        assert [r.severity for r in rows] == ["warning"]
        assert "85%" in rows[0].title

        card = await svc.create_manual_account(
            name="Visa",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
            current_balance=96_000,
        )
        card.credit_limit = 100_000
        async_db_session.add(card)
        await async_db_session.flush()

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        rows = await _insights_of(async_db_session, "credit_utilization")
        assert sorted(r.severity for r in rows) == ["critical", "warning"]

    @pytest.mark.asyncio
    async def test_a_lightly_used_card_stays_silent(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._card(async_db_session, svc, balance=20_000, credit_limit=100_000)

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "credit_utilization") == []

    @pytest.mark.asyncio
    async def test_a_past_due_card_is_critical(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._card(
            async_db_session,
            svc,
            minimum=180_111,
            due=date(2026, 7, 11),
            is_overdue=True,
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        rows = await _insights_of(async_db_session, "card_overdue")
        assert len(rows) == 1
        assert rows[0].severity == "critical"
        assert "$1,801.11" in rows[0].body

    @pytest.mark.asyncio
    async def test_rerun_does_not_duplicate(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        await self._cash(svc, available=100)
        await self._card(
            async_db_session,
            svc,
            credit_limit=5_000_000,
            minimum=180_111,
            due=date(2026, 7, 25),
            is_overdue=True,
            aprs=[
                {
                    "apr_type": "purchase_apr",
                    "apr_percentage_bps": 2_999,
                    "balance_subject_to_apr": 4_341_575,
                }
            ],
        )

        for _ in range(2):
            await generate_insights(
                async_db_session, owner_user_id=1, today=date(2026, 7, 20)
            )

        for kind in (
            "min_payment_gap",
            "high_apr_carry",
            "credit_utilization",
            "card_overdue",
        ):
            assert len(await _insights_of(async_db_session, kind)) == 1, kind


class TestCashRunway:
    @pytest.mark.asyncio
    async def test_bills_outrunning_cash_is_critical(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
            current_balance=100_000,
        )
        await _stream(
            async_db_session,
            is_user_confirmed=True,
            account_id=account.id,
            name="RENT",
            amount=200_000,
            last_date=date(2026, 6, 30),
            next_expected_date=date(2026, 7, 30),
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        rows = await _insights_of(async_db_session, "cash_runway")
        assert len(rows) == 1
        assert rows[0].severity == "critical"
        assert "2026-07-30" in rows[0].title

    @pytest.mark.asyncio
    async def test_covered_bills_stay_silent(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
            current_balance=1_000_000,
        )
        await _stream(
            async_db_session,
            account_id=account.id,
            name="RENT",
            amount=200_000,
            last_date=date(2026, 6, 30),
            next_expected_date=date(2026, 7, 30),
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "cash_runway") == []

    @pytest.mark.asyncio
    async def test_one_alert_per_month(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
            current_balance=100_000,
        )
        await _stream(
            async_db_session,
            is_user_confirmed=True,
            account_id=account.id,
            name="RENT",
            amount=200_000,
            last_date=date(2026, 6, 30),
            next_expected_date=date(2026, 7, 30),
        )

        for day in (date(2026, 7, 20), date(2026, 7, 21)):
            await generate_insights(async_db_session, owner_user_id=1, today=day)

        assert len(await _insights_of(async_db_session, "cash_runway")) == 1


class TestSubscriptionCreep:
    async def _subscribed_months(
        self,
        session: AsyncSession,
        svc,
        account_id: int,
        *,
        name: str,
        amount: int,
        months: list[date],
    ):
        stream = await _stream(
            session,
            is_user_confirmed=True,
            account_id=account_id,
            name=name,
            amount=amount,
            last_date=months[-1],
            next_expected_date=months[-1] + timedelta(days=30),
        )
        stream.is_subscription = True
        session.add(stream)
        for day in months:
            txn = await _txn(svc, account_id, -amount, day, name)
            txn.recurring_stream_id = stream.id
            session.add(txn)
        await session.flush()
        return stream

    @pytest.mark.asyncio
    async def test_a_new_service_on_top_of_the_pile_is_flagged(
        self, async_db_session: AsyncSession
    ) -> None:
        """No single price hike, but the total drifted: a second streaming
        service appeared in July."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await self._subscribed_months(
            async_db_session,
            svc,
            account.id,
            name="NETFLIX",
            amount=1_549,
            months=[date(2026, m, 6) for m in (4, 5, 6, 7)],
        )
        await self._subscribed_months(
            async_db_session,
            svc,
            account.id,
            name="HBO MAX",
            amount=1_849,
            months=[date(2026, 7, 10)],
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        rows = await _insights_of(async_db_session, "subscription_creep")
        assert len(rows) == 1
        assert "$33.98" in rows[0].title
        assert "typical $15.49" in rows[0].body

    @pytest.mark.asyncio
    async def test_a_steady_pile_stays_silent(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await self._subscribed_months(
            async_db_session,
            svc,
            account.id,
            name="NETFLIX",
            amount=1_549,
            months=[date(2026, m, 6) for m in (4, 5, 6, 7)],
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "subscription_creep") == []

    @pytest.mark.asyncio
    async def test_partial_history_never_trips_the_rule(
        self, async_db_session: AsyncSession
    ) -> None:
        """A brand-new subscriber has no norm to drift from."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        await self._subscribed_months(
            async_db_session,
            svc,
            account.id,
            name="NETFLIX",
            amount=1_549,
            months=[date(2026, 6, 6), date(2026, 7, 6)],
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await _insights_of(async_db_session, "subscription_creep") == []


class TestOverspendOnPace:
    """ "More than usual" has to mean "more than usual BY NOW".

    The rule compared a part-finished month against whole prior months, so
    it could barely fire until the month was nearly over - by which point
    the money is spent and the warning is a post-mortem. Prior months are
    now measured to the same day of the month.
    """

    async def _dining(self, db):
        category = FinanceCategory(
            owner_user_id=1, name="Dining", slug="dining", classification="expense"
        )
        db.add(category)
        await db.flush()
        return category

    async def _overspend_rows(self, db):
        return (
            await db.exec(
                select(FinanceInsight).where(
                    FinanceInsight.insight_type == "overspend_category"
                )
            )
        ).all()

    @pytest.mark.asyncio
    async def test_it_catches_a_month_going_wrong_while_it_can_still_matter(
        self, async_db_session: AsyncSession
    ) -> None:
        """$100 by the 20th in a normal month, $250 this time. Against whole
        prior months ($300) this never crossed 1.5x and the reader heard
        nothing."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        category = await self._dining(async_db_session)
        for month in (4, 5, 6):
            await _txn(
                svc,
                account.id,
                -10000,
                date(2026, month, 5),
                "DINING",
                category_id=category.id,
            )
            await _txn(
                svc,
                account.id,
                -20000,
                date(2026, month, 25),
                "DINING",
                category_id=category.id,
            )
        await _txn(
            svc,
            account.id,
            -25000,
            date(2026, 7, 5),
            "DINING",
            category_id=category.id,
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert len(await self._overspend_rows(async_db_session)) == 1

    @pytest.mark.asyncio
    async def test_the_first_days_of_a_month_are_not_judged(
        self, async_db_session: AsyncSession
    ) -> None:
        """A baseline measured over three days is mostly noise, and one
        early grocery run would read as a spending emergency."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        category = await self._dining(async_db_session)
        for month in (4, 5, 6):
            await _txn(
                svc,
                account.id,
                -10000,
                date(2026, month, 2),
                "DINING",
                category_id=category.id,
            )
        await _txn(
            svc,
            account.id,
            -90000,
            date(2026, 7, 1),
            "DINING",
            category_id=category.id,
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 3)
        )

        assert await self._overspend_rows(async_db_session) == []

    @pytest.mark.asyncio
    async def test_a_baseline_too_small_to_multiply_is_ignored(
        self, async_db_session: AsyncSession
    ) -> None:
        """Ratios against a few dollars are arithmetic, not information."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        category = await self._dining(async_db_session)
        for month in (4, 5, 6):
            await _txn(
                svc,
                account.id,
                -300,
                date(2026, month, 5),
                "DINING",
                category_id=category.id,
            )
        await _txn(
            svc,
            account.id,
            -4000,
            date(2026, 7, 5),
            "DINING",
            category_id=category.id,
        )

        await generate_insights(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert await self._overspend_rows(async_db_session) == []
