"""The projection honours the dialog-wide account filter.

The forecast walks today's cash balance forward through scheduled bills.
Narrowing the view to one card and leaving the forecast global gives a
balance line for accounts you are not looking at - the number moves for
reasons that are off screen.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import detect_recurring, detect_transfers
from app.services.finance.service import FinanceService
from tests.services._finance_factories import declare_bill, seed_stream, seed_txn


async def _bill(svc, db, account_id, name, cents):
    await declare_bill(
        svc, db, account_id, name, [date(2026, m, 5) for m in range(1, 8)], cents=cents
    )


class TestProjectionAccountFilter:
    @pytest.mark.asyncio
    async def test_it_only_walks_the_accounts_you_are_viewing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        savings = await svc.create_manual_account(
            name="Savings",
            account_type="savings",
            classification="asset",
            owner_user_id=1,
        )
        await _bill(svc, async_db_session, checking.id, "RENT", -180_000)
        await _bill(svc, async_db_session, savings.id, "STORAGE", -9_000)

        everything = await svc.project_balances(owner_user_id=1, days=120)
        just_checking = await svc.project_balances(
            owner_user_id=1, days=120, account_ids=[checking.id]
        )

        names = {p.name for p in everything.points}
        narrowed = {p.name for p in just_checking.points}
        assert "RENT" in names and "STORAGE" in names
        assert "RENT" in narrowed
        assert "STORAGE" not in narrowed

    @pytest.mark.asyncio
    async def test_no_filter_still_means_everything(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await _bill(svc, async_db_session, checking.id, "RENT", -180_000)

        result = await svc.project_balances(owner_user_id=1, days=120)

        assert result.points


class TestAccountLessBills:
    """A bill with no account still belongs in the forecast.

    Hand-entered bills can be created without an account, and the filter
    I added asked ``stream.account_id not in allowed`` - which is always
    True for None. So narrowing to any account silently dropped every
    hand-entered bill from Projected. Confirmed live: "Betr Health",
    $5,000 twice a month, missing from the forecast.
    """

    @pytest.mark.asyncio
    async def test_it_projects_with_no_filter(self, svc: FinanceService) -> None:
        await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await seed_stream(
            svc,
            name="Betr Health",
            direction="inflow",
            frequency="semi_monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=None,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=120, today=date(2026, 8, 2)
        )

        assert "Betr Health" in {p.name for p in result.points}

    @pytest.mark.asyncio
    async def test_narrowing_to_an_account_does_not_drop_it(
        self, svc: FinanceService
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await seed_stream(
            svc,
            name="Betr Health",
            direction="inflow",
            frequency="semi_monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=None,
        )

        result = await svc.project_balances(
            owner_user_id=1,
            days=120,
            today=date(2026, 8, 2),
            account_ids=[checking.id],
        )

        assert "Betr Health" in {p.name for p in result.points}


class TestOnlyCashMoves:
    """A card purchase does not move cash on the day it happens.

    The walk starts from the balance of CASH accounts, so a bill sitting
    on a credit card has no business drawing that balance down: the money
    leaves when the card is paid, and the card payment is itself a stream
    in the same walk. Counting both charges the same dollars twice, which
    is how a household that breaks even on paper projects into the red.
    """

    @pytest.mark.asyncio
    async def test_a_card_subscription_does_not_draw_down_cash(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        card = await svc.create_manual_account(
            name="Amex",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
        )
        await seed_stream(
            svc,
            name="Netflix",
            expected_amount=1_549,
            next_expected_date=date(2026, 8, 6),
            account_id=card.id,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=60, today=date(2026, 8, 2)
        )

        charged = [p for p in result.points if p.name == "Netflix"]
        assert not charged, "a card charge was taken out of the cash balance"
        assert checking.id is not None

    @pytest.mark.asyncio
    async def test_the_card_payment_still_does(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The cash side of the same money, and the only side that counts."""
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await seed_stream(
            svc,
            name="Amex Autopay",
            expected_amount=205_000,
            next_expected_date=date(2026, 8, 25),
            account_id=checking.id,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=60, today=date(2026, 8, 2)
        )

        assert [p for p in result.points if p.name == "Amex Autopay"], (
            "the payment that actually moves cash is missing"
        )

    @pytest.mark.asyncio
    async def test_a_hand_entered_bill_still_counts(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """No account means no statement about which account it hits, and
        the same rule the account filter follows: it stays in."""
        await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await seed_stream(
            svc,
            name="Property Tax",
            expected_amount=155_000,
            next_expected_date=date(2026, 8, 18),
            account_id=None,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=60, today=date(2026, 8, 2)
        )

        assert [p for p in result.points if p.name == "Property Tax"], (
            "a bill belonging to no account was dropped"
        )


class TestTheCardPaymentCoversWhatWasSpentOnIt:
    """A budget envelope and a card payment can be the same money.

    Everyday spending goes on the card, so the plan for it (the envelope)
    and the cash that settles it (the payment) describe one outflow. The
    walk already suppresses an envelope a recurring BILL covers, but a
    card payment carries no category, so it suppressed nothing: a
    household whose spending is all on one card had its groceries
    charged twice and projected steadily into the red.
    """

    async def _household(self, svc: FinanceService, db: AsyncSession):
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        card = await svc.create_manual_account(
            name="Amex",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
        )
        # A real payment: both legs, paired, so the walk sees the card
        # actually being settled from cash rather than a lookalike bill.
        for month in (5, 6, 7):
            await seed_txn(
                svc,
                checking.id,
                -120_000,
                date(2026, month, 25),
                name="Amex Autopay Payment",
            )
            await seed_txn(
                svc,
                card.id,
                120_000,
                date(2026, month, 26),
                name="Payment Received",
            )
        await detect_transfers(db, owner_user_id=1, today=date(2026, 8, 1))
        await detect_recurring(db, owner_user_id=1)
        for stream in await svc.list_recurring(owner_user_id=1):
            await svc.confirm_recurring(stream.id, owner_user_id=1)
        return checking, card

    @pytest.mark.asyncio
    async def test_an_envelope_for_what_the_card_paid_is_not_charged_again(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        _checking, card = await self._household(svc, async_db_session)
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")
        for month in (6, 7):
            await seed_txn(
                svc,
                card.id,
                -22_000,
                date(2026, month, 12),
                name="Whole Foods Market",
                category_id=groceries.id,
            )
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=202608,
            category_id=groceries.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=40_000,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=60, today=date(2026, 8, 2)
        )

        drawn = [p for p in result.points if p.category == "Food:Groceries"]
        assert not drawn, "the card paid for it and the envelope charged it again"

    @pytest.mark.asyncio
    async def test_only_a_card_settles_spending(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Every non-cash account is not a card. A brokerage or a loan has
        no card payment settling its rows, so spending recorded there must
        not silence an envelope."""
        _checking, _card = await self._household(svc, async_db_session)
        brokerage = await svc.create_manual_account(
            name="Brokerage",
            account_type="brokerage",
            classification="asset",
            owner_user_id=1,
        )
        fees = await svc.get_or_create_category_from_hint("Fees:Advisory")
        await seed_txn(
            svc,
            brokerage.id,
            -9_900,
            date(2026, 7, 12),
            name="Advisor",
            category_id=fees.id,
        )
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=202608,
            category_id=fees.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=10_000,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=60, today=date(2026, 8, 2)
        )

        assert [p for p in result.points if p.category == "Fees:Advisory"], (
            "a brokerage row silenced an envelope as if a card paid it"
        )

    @pytest.mark.asyncio
    async def test_a_second_card_nobody_pays_keeps_its_envelope(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Two cards, one autopay. The paid card's spending is settled by
        the projected payment; the other card's is not, and suppressing
        its envelope would understate the cash the month still needs."""
        _checking, _paid_card = await self._household(svc, async_db_session)
        other = await svc.create_manual_account(
            name="Visa",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
        )
        fuel = await svc.get_or_create_category_from_hint("Auto:Fuel")
        for month in (6, 7):
            await seed_txn(
                svc,
                other.id,
                -6_000,
                date(2026, month, 9),
                name="Shell",
                category_id=fuel.id,
            )
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=202608,
            category_id=fuel.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=12_000,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=60, today=date(2026, 8, 2)
        )

        assert [p for p in result.points if p.category == "Auto:Fuel"], (
            "an unpaid card's spending was treated as settled"
        )

    @pytest.mark.asyncio
    async def test_an_envelope_the_card_never_pays_still_draws(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The suppression is about overlap, not about having a card."""
        _checking, _card = await self._household(svc, async_db_session)
        childcare = await svc.get_or_create_category_from_hint("Family:Childcare")
        await svc.upsert_budget_line(
            owner_user_id=1,
            period_month=202608,
            category_id=childcare.id,
            payee_key=None,
            payee_label=None,
            allocated_amount=60_000,
        )

        result = await svc.project_balances(
            owner_user_id=1, days=60, today=date(2026, 8, 2)
        )

        assert [p for p in result.points if p.category == "Family:Childcare"], (
            "an envelope nothing else covers was dropped"
        )
