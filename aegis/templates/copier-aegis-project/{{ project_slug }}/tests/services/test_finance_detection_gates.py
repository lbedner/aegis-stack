"""What detection is allowed to call a recurring stream.

The old rule was: 3+ transactions whose MEDIAN gap lands within +/-20% of
a canonical cadence. Both halves are too weak on real data.

Stewart's Shops - a convenience store - was detected as a yearly
subscription at 90% confidence from four visits with gaps of 2044, 430
and 17 days and amounts from $2.69 to $85.32. The median gap (430) fell
inside +/-20% of a year, because 20% of 365 is a 73-day window. Across
325 streams, 55% had a biggest gap at least 5x their smallest: no rhythm
at all.
"""

from datetime import date, timedelta

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import detect_recurring
from app.services.finance.domains.detection.recurring.cadence import (
    _frequency_for,
    _rhythm_ratio,
)
from app.services.finance.models import FinanceRecurringStream
from app.services.finance.service import FinanceService
from tests.services._finance_factories import live_streams as _live_streams
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_spend_series as _spend


class TestCadenceTolerance:
    def test_a_year_no_longer_has_a_five_month_window(self) -> None:
        """+/-20% of 365 is +/-73 days, so anything from 292 to 438 days
        was "yearly". That is what caught Stewart's at a 430-day median."""
        assert _frequency_for(430) is None
        assert _frequency_for(365) == "annually"
        assert _frequency_for(380) == "annually"  # still generous

    def test_short_cadences_keep_their_proportional_slack(self) -> None:
        """The cap only binds where 20% is a large absolute number - a
        weekly bill that drifts a day is still weekly."""
        assert _frequency_for(7) == "weekly"
        assert _frequency_for(8) == "weekly"
        assert _frequency_for(31) == "monthly"
        assert _frequency_for(88) == "quarterly"


class TestRhythmRatio:
    def test_a_steady_cadence_scores_one(self) -> None:
        assert _rhythm_ratio([30, 31, 29], 30) == 1.0

    def test_noise_scores_low(self) -> None:
        """Stewart's actual gaps."""
        assert _rhythm_ratio([2044, 430, 17], 365) < 0.5

    def test_one_skipped_month_still_counts(self) -> None:
        """A real bill that missed a month must not be thrown away."""
        assert _rhythm_ratio([30, 60, 30], 30) >= 0.6

    def test_no_gaps_scores_zero(self) -> None:
        assert _rhythm_ratio([], 30) == 0.0


class TestDetectionEndToEnd:
    @pytest.mark.asyncio
    async def test_a_real_monthly_bill_is_still_found(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])

        result = await detect_recurring(async_db_session, owner_user_id=1)

        assert result.detected == 1

    @pytest.mark.asyncio
    async def test_random_visits_are_not_a_subscription(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The Stewart's shape, rebuilt: four visits, no rhythm."""
        account = await _account(svc)
        start = date(2019, 8, 26)
        days = [
            start,
            start + timedelta(days=2044),
            start + timedelta(days=2474),
            start + timedelta(days=2491),
        ]
        await _spend(svc, account.id, days, name="STEWART'S SHOPS")

        result = await detect_recurring(async_db_session, owner_user_id=1)

        assert result.detected == 0

    @pytest.mark.asyncio
    async def test_a_genuine_yearly_bill_survives(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(
            svc,
            account.id,
            [date(2023, 3, 1), date(2024, 3, 2), date(2025, 3, 1)],
            name="ANNUAL DUES",
        )

        result = await detect_recurring(async_db_session, owner_user_id=1)

        assert result.detected == 1

    @pytest.mark.asyncio
    async def test_confidence_reflects_fit_not_just_count(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Stewart's scored 90 because confidence was 50 + 10 x occurrences
        - more random visits raised it."""

        account = await _account(svc)
        await _spend(svc, account.id, [date(2026, m, 9) for m in range(1, 6)])
        await detect_recurring(async_db_session, owner_user_id=1)
        steady = (await async_db_session.exec(select(FinanceRecurringStream))).one()

        assert steady.confidence is not None and steady.confidence >= 85


class TestStreamsThatNoLongerQualify:
    """Tightening the gates has to remove what they now reject.

    A group that fails a gate is skipped - and skipping leaves its
    members' ``recurring_stream_id`` pointing at the old stream, so the
    stream still has members, never orphans, and ``_prune_orphans`` never
    touches it. The junk survives every future scan with its stale
    cadence and its old confidence.
    """

    @pytest.mark.asyncio
    async def test_a_stream_that_fails_the_new_gates_is_retired(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import (
            FinanceTransaction,
        )

        account = await _account(svc)
        # A clean monthly run, detected the normal way.
        txns = await _spend(
            svc, account.id, [date(2026, m, 9) for m in range(1, 6)], name="ACME"
        )
        assert (await detect_recurring(async_db_session, owner_user_id=1)).detected == 1
        stream = (await async_db_session.exec(select(FinanceRecurringStream))).one()

        # Now the rhythm breaks: the remaining history is noise.
        for txn in txns[1:]:
            txn.deleted_at = None
            txn.date_ = date(2026, 1, 9) + timedelta(days=900 * txns.index(txn))
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
        assert live == [], "a stream that no longer qualifies must not survive"
        orphaned = (
            await async_db_session.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.recurring_stream_id == stream.id
                )
            )
        ).all()
        assert orphaned == [], "members must be unlinked so the stream can orphan"


class TestDeadStreams:
    """A bill that stopped is not a bill.

    These pass every shape test - CAPITAL ONE AUTO CARPAY really was
    monthly, and so were Wix, AES, TJX and Synchrony. They ended in 2019.
    Nothing about their cadence says so, only their silence since.

    The window has to scale with the cadence: 12 months of quiet kills a
    monthly bill, but an annual one is legitimately quiet for 11.
    """

    @pytest.mark.asyncio
    async def test_a_monthly_bill_that_stopped_years_ago_is_dropped(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(
            svc,
            account.id,
            [date(2019, m, 2) for m in (7, 8, 9, 10, 11)],
            name="CAPITAL ONE AUTO CARPAY",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 0

    @pytest.mark.asyncio
    async def test_a_monthly_bill_still_running_survives(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(
            svc, account.id, [date(2026, m, 9) for m in range(3, 8)], name="ACME"
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1

    @pytest.mark.asyncio
    async def test_an_annual_bill_is_allowed_a_long_silence(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """11 months since the last charge is NORMAL for a yearly bill -
        a flat 12-month rule would delete every one of them."""
        account = await _account(svc)
        await _spend(
            svc,
            account.id,
            [date(2023, 9, 1), date(2024, 9, 1), date(2025, 9, 1)],
            name="ANNUAL DUES",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1


class TestChurnSelfHeals:
    """Under rebuild there is nothing to revive - and nothing to protect.

    The old regime needed a watermark so a pass running different rules
    could not resurrect a retired row from its own stale evidence. Rebuild
    makes the whole question moot: even if some pass DOES regenerate a
    stale proposal (a backfill run with an old ``today``, an old code
    version), the very next current-dated pass purges it again, because a
    proposal only exists while a pass justifies it. Convergence is a
    property of the regime, not of per-row bookkeeping.
    """

    @pytest.mark.asyncio
    async def test_a_stale_proposal_resurrected_by_a_backdated_pass_dies_again(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(
            svc,
            account.id,
            [date(2019, m, 2) for m in (7, 8, 9, 10, 11)],
            name="CAPITAL ONE AUTO CARPAY",
        )
        # A pass reading the old rows as if current (old code, a backfill)
        # legitimately proposes the stream.
        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2019, 12, 1)
        )
        # The next real-dated pass removes it - no watermark required.
        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 3)
        )

        rows = (await async_db_session.exec(select(FinanceRecurringStream))).all()
        assert rows == []


class TestTrivialAmounts:
    """A perfect rhythm on trivial money is still noise.

    A savings account paid a $0.31 dividend 54 months running - flawless
    cadence, fixed amount, 100% confidence by every other measure. It is
    not a bill and not income; it is a rounding error with a heartbeat.
    """

    @pytest.mark.asyncio
    async def test_a_rounding_error_is_not_a_stream(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _spend(
            svc,
            account.id,
            [date(2026, m, 28) for m in range(1, 7)],
            cents=-31,
            name="Deposit Dividend 0.020%",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 0

    @pytest.mark.asyncio
    async def test_a_small_but_real_subscription_survives(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The floor has to sit below a real cheap subscription - $5.41
        CVS ExtraCare is a bill somebody chose to pay."""
        account = await _account(svc)
        await _spend(
            svc,
            account.id,
            [date(2026, m, 9) for m in range(1, 7)],
            cents=-541,
            name="CVS EXTRACAREPLUS",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1


class TestInflowsOnLiabilityAccounts:
    """Money arriving on a credit card is a PAYMENT, not income.

    A credit on a liability account reduces what you owe - it came from
    another account of yours. Structurally it can never be household
    income, and that is knowable without finding the matching outflow
    (which, on real data, was not even imported: 81 AMEX credits and 33
    Citi credits with no counterpart anywhere).

    They still belong on the card's own register. What they must not
    become is a recurring INCOME stream the forecast counts.
    """

    @pytest.mark.asyncio
    async def test_card_payments_are_not_income_streams(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        card = await svc.create_manual_account(
            name="AMEX",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
        )
        await _spend(
            svc,
            card.id,
            [date(2026, m, 11) for m in range(1, 7)],
            cents=157_527,
            name="AUTOPAY PAYMENT - THANK YOU",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 0

    @pytest.mark.asyncio
    async def test_a_real_paycheck_on_a_cash_account_still_counts(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await _spend(
            svc,
            checking.id,
            [date(2026, m, 8) for m in range(1, 7)],
            cents=203_100,
            name="SSA TREAS 310 SOC SEC",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1

    @pytest.mark.asyncio
    async def test_spending_on_a_card_is_still_detected(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Only the INFLOW direction is structural - a subscription
        charged to the card is a normal bill."""
        card = await svc.create_manual_account(
            name="AMEX",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
        )
        await _spend(
            svc,
            card.id,
            [date(2026, m, 9) for m in range(1, 7)],
            cents=-1_599,
            name="NETFLIX.COM",
        )

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 2)
        )

        assert result.detected == 1


class TestTwoMonthAndSixMonthRhythms:
    """Cadences the forecast could always step but detection could not name.

    ``FREQUENCY_STEPS`` has handled bimonthly and semiannual from the
    start, and the projection walks a stream by stepping its frequency.
    ``_CADENCES`` did not list either, so a six-month insurance premium
    measured as "irregular" - and an irregular stream cannot be stepped,
    so it never reached the forecast at all. A real bill, correctly
    detected as recurring, simply absent from the balance line.

    Measured against the live ledger before making the change: 67 of the
    68 affected day-gaps move from "no cadence" to a real one, ZERO
    existing streams reclassify, and six real bills start being found.
    """

    @pytest.mark.asyncio
    async def test_a_two_month_rhythm_is_detected(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        # Ending near ``today``: a rhythm that stopped two years ago is
        # correctly retired by the gone-quiet gate, which is a different
        # rule and not what this test is about.
        last = date(2026, 7, 15)
        await _spend(
            svc,
            account.id,
            sorted(last - timedelta(days=60 * i) for i in range(6)),
            name="Royal Carting",
        )

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 8)
        )

        streams = await _live_streams(async_db_session)
        assert [s.frequency for s in streams] == ["bimonthly"]

    @pytest.mark.asyncio
    async def test_a_six_month_rhythm_is_detected(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Geico: February and August, every year."""
        account = await _account(svc)
        days = [
            date(2024, 2, 25),
            date(2024, 8, 25),
            date(2025, 2, 25),
            date(2025, 8, 25),
            date(2026, 2, 25),
        ]
        await _spend(svc, account.id, days, cents=-200_000, name="Geico")

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 8)
        )

        streams = await _live_streams(async_db_session)
        assert [s.frequency for s in streams] == ["semi_annually"]

    @pytest.mark.asyncio
    async def test_a_detected_six_month_bill_reaches_the_forecast(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The point of naming the cadence at all."""
        account = await _account(svc)
        days = [
            date(2024, 2, 25),
            date(2024, 8, 25),
            date(2025, 2, 25),
            date(2025, 8, 25),
            date(2026, 2, 25),
        ]
        await _spend(svc, account.id, days, cents=-200_000, name="Geico")
        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 8)
        )
        stream = (await _live_streams(async_db_session))[0]
        stream.is_user_confirmed = True
        async_db_session.add(stream)
        await async_db_session.flush()

        result = await svc.project_balances(
            owner_user_id=1, days=250, today=date(2026, 8, 8)
        )

        assert any(p.name == "Geico" for p in result.points)


class TestTheNewCadenceBands:
    def test_two_months_and_six_months_now_have_a_name(self) -> None:
        assert _frequency_for(60) == "bimonthly"
        assert _frequency_for(180) == "semi_annually"
        assert _frequency_for(181) == "semi_annually"

    def test_the_existing_cadences_are_untouched(self) -> None:
        """The whole change is additive. Anything that had a name keeps
        it - verified against every stream in the live ledger before
        shipping, but pinned here so it stays true."""
        for gap, expected in (
            (7, "weekly"),
            (14, "biweekly"),
            (15, "biweekly"),
            (18, "semi_monthly"),
            (30, "monthly"),
            (31, "monthly"),
            (90, "quarterly"),
            (365, "annually"),
        ):
            assert _frequency_for(gap) == expected

    def test_semi_monthly_is_all_but_unreachable(self) -> None:
        """A pre-existing quirk, pinned because it is surprising and
        because it is NOT what this change did.

        Biweekly (14) spans 11.2-16.8 and is checked first, so it swallows
        semi-monthly's own 15. Only a 17-18 day median ever lands on
        ``semi_monthly``, which is not what twice-a-month billing looks
        like. Fixing it means re-keying existing biweekly streams, which
        is a different change with real blast radius - unlike adding a
        band where none existed.
        """
        assert _frequency_for(15) == "biweekly"
        assert _frequency_for(18) == "semi_monthly"

    def test_a_gap_between_the_new_bands_is_still_nameless(self) -> None:
        """Adding cadences must not turn the ladder into a catch-all.
        Stewart's 430-day median has to stay unnamed."""
        assert _frequency_for(430) is None
        assert _frequency_for(120) is None
        assert _frequency_for(250) is None

    def test_the_contested_boundary_goes_to_the_closer_cadence(self) -> None:
        """72 days is where bimonthly's upper edge meets quarterly's
        lower one - the single gap in the whole range whose meaning
        changes. It resolves to bimonthly, which is also the arithmetic
        answer: 12 days from 60, 18 from 90.
        """
        assert _frequency_for(72) == "bimonthly"
        assert _frequency_for(73) == "quarterly"


class TestExcludedRowsFeedNoDetection:
    """Excluded rows are bookkeeping, not economic activity.

    Nine issuer-adjustment legs recur near-monthly with a steady
    descriptor - exactly the shape detection hunts for - and once they
    carry an assigned payee they group WITH that payee's real rows.
    Without this gate, labeling an adjustment pair "American Express"
    would feed phantom rows into Amex's stream detection.
    """

    @pytest.mark.asyncio
    async def test_a_rhythmic_excluded_descriptor_is_never_a_bill(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        days = [date(2026, m, 16) for m in range(1, 7)]
        rows = await _spend(
            svc, account.id, days, cents=-3_080, name="DR ADJ REDIST CADV PRIN"
        )
        for row in rows:
            row.excluded_from_reports = True
            async_db_session.add(row)
        await async_db_session.flush()

        await detect_recurring(async_db_session, owner_user_id=1)

        assert await _live_streams(async_db_session) == []

    @pytest.mark.asyncio
    async def test_normal_rows_still_detect(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The gate must remove exactly the excluded rows, nothing else."""
        account = await _account(svc)
        days = [date(2026, m, 16) for m in range(1, 7)]
        await _spend(svc, account.id, days, cents=-3_080, name="NETFLIX")

        await detect_recurring(async_db_session, owner_user_id=1)

        assert len(await _live_streams(async_db_session)) == 1


class TestPaymentLegsAreDetectable:
    """A credit-card payment is a transfer, but it is a PAYMENT first.

    Transfer legs are excluded from detection, so the biggest single cash
    outflow of the month - the card autopay - could never form a stream:
    nothing to confirm, nothing for the cash forecast to walk, and a
    projected runway optimistic by ~$1,800 every month (confirmed live,
    Amex autopay). The outflow leg of a transfer INTO a liability is
    admitted now; ordinary transfer noise stays out.
    """

    async def _liability(self, svc, name="Amex"):
        return await svc.create_manual_account(
            name=name,
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
        )

    async def _payment_pairs(self, svc, checking, card, months, cents=180_111):
        for m in months:
            await svc.create_transaction(
                account_id=checking.id,
                amount=-cents,
                txn_date=date(2026, m, 13),
                owner_user_id=1,
                name="AMERICAN EXPRESS ACH PMT",
            )
            await svc.create_transaction(
                account_id=card.id,
                amount=cents,
                txn_date=date(2026, m, 13),
                owner_user_id=1,
                name="AUTOPAY PAYMENT - THANK YOU",
            )

    @pytest.mark.asyncio
    async def test_a_card_autopay_forms_a_stream_on_the_cash_side(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import detect_transfers

        checking = await _account(svc)
        card = await self._liability(svc)
        await self._payment_pairs(svc, checking, card, range(1, 7))
        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1), lookback_days=0
        )

        await detect_recurring(async_db_session, owner_user_id=1)

        streams = await _live_streams(async_db_session)
        payment = [s for s in streams if s.account_id == checking.id]
        assert len(payment) == 1
        assert payment[0].direction == "outflow"
        # The card-side inflow leg must not form its own mirror stream.
        assert not [s for s in streams if s.account_id == card.id]

    @pytest.mark.asyncio
    async def test_an_asset_to_asset_transfer_still_forms_no_stream(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Moving money to savings every month is not a payment; letting
        it through re-creates the five-figure fiction the transfer
        exclusion exists to prevent."""
        from app.services.finance.domains.detection import detect_transfers

        checking = await _account(svc)
        savings = await svc.create_manual_account(
            name="Savings",
            account_type="savings",
            classification="asset",
            owner_user_id=1,
        )
        for m in range(1, 7):
            await svc.create_transaction(
                account_id=checking.id,
                amount=-50_000,
                txn_date=date(2026, m, 1),
                owner_user_id=1,
                name="TRANSFER TO SAVINGS",
            )
            await svc.create_transaction(
                account_id=savings.id,
                amount=50_000,
                txn_date=date(2026, m, 1),
                owner_user_id=1,
                name="TRANSFER FROM CHECKING",
            )
        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1), lookback_days=0
        )

        await detect_recurring(async_db_session, owner_user_id=1)

        assert await _live_streams(async_db_session) == []


class TestPaymentStreamsReachTheForecast:
    """The whole point of admitting payment legs: the cash walk charges
    the autopay. Confirm stays the one door in - the detector's average
    is poisoned by one-off paydowns (a real $21,250 sat among $1,800s),
    and pinning the expected amount at confirm time is what makes the
    projection honest rather than merely populated.
    """

    async def _payment_stream(self, svc, db):
        from app.services.finance.domains.detection import (
            detect_recurring,
            detect_transfers,
        )

        checking = await _account(svc)
        card = await svc.create_manual_account(
            name="Amex",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
        )
        for m in range(1, 7):
            await svc.create_transaction(
                account_id=checking.id,
                amount=-180_111,
                txn_date=date(2026, m, 13),
                owner_user_id=1,
                name="AMERICAN EXPRESS ACH PMT",
            )
            await svc.create_transaction(
                account_id=card.id,
                amount=180_111,
                txn_date=date(2026, m, 13),
                owner_user_id=1,
                name="AUTOPAY PAYMENT - THANK YOU",
            )
        await detect_transfers(
            db, owner_user_id=1, today=date(2026, 7, 1), lookback_days=0
        )
        await detect_recurring(db, owner_user_id=1)
        streams = await _live_streams(db)
        assert len(streams) == 1
        return streams[0], checking

    @pytest.mark.asyncio
    async def test_the_classifier_knows_a_payment_stream(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        stream, _checking = await self._payment_stream(svc, async_db_session)

        payments = await svc.payment_stream_ids([stream.id])

        assert payments == {stream.id}

    @pytest.mark.asyncio
    async def test_a_confirmed_payment_walks_the_cash_projection(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        stream, _checking = await self._payment_stream(svc, async_db_session)
        await svc.confirm_recurring(stream.id, owner_user_id=1)
        stream.expected_amount = 180_111
        stream.next_expected_date = date(2026, 7, 13)
        async_db_session.add(stream)
        await async_db_session.flush()

        projection = await svc.project_balances(
            owner_user_id=1, today=date(2026, 7, 1), days=30
        )

        names = [point.name for point in projection.points]
        assert any("AMERICAN EXPRESS" in n.upper() for n in names)

    @pytest.mark.asyncio
    async def test_an_unconfirmed_payment_stays_out_of_the_projection(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The $21,250 problem: an unpinned detector average must not
        walk the forecast just because the stream now exists."""
        stream, _checking = await self._payment_stream(svc, async_db_session)
        stream.next_expected_date = date(2026, 7, 13)
        async_db_session.add(stream)
        await async_db_session.flush()

        projection = await svc.project_balances(
            owner_user_id=1, today=date(2026, 7, 1), days=30
        )

        assert projection.points == []

    @pytest.mark.asyncio
    async def test_a_confirmed_payment_never_inflates_the_bills_total(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The other half of "payment first, transfer second": the cash
        walk charges it, but the Bills cell and month verdict must not -
        every dollar of it was already counted at the card swipes, and
        adding the payment double-counts the whole statement."""
        stream, _checking = await self._payment_stream(svc, async_db_session)
        await svc.confirm_recurring(stream.id, owner_user_id=1)
        stream.expected_amount = 180_111
        stream.next_expected_date = date(2026, 7, 13)
        async_db_session.add(stream)
        await async_db_session.flush()

        stats = (await svc.budget_summary(owner_user_id=1)).stats

        assert stats.fixed_total == 0
        assert stats.fixed_count == 0
