"""Tests for internal-transfer detection + pairing (FIN-26).

Covers the ticket's acceptance scenarios: a credit-card payment auto-pairs and
drops out of spend; a near-miss is never silently hidden and
confirm/reject behave; same-account and one-sided cases never pair.
"""

from datetime import date

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import detect_transfers
from app.services.finance.models import FinanceCategory, FinanceTransfer
from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account


class TestTransferDetection:
    @pytest.mark.asyncio
    async def test_credit_card_payment_auto_pairs_and_excludes_spend(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        card = await _account(svc, "Card", "credit_card", "liability")
        category = FinanceCategory(
            owner_user_id=1,
            name="Credit Card Payment",
            slug="ccp-test",
            classification="expense",
        )
        async_db_session.add(category)
        await async_db_session.flush()

        out = await svc.create_transaction(
            account_id=checking.id,
            amount=-190000,  # $1,900 out of checking
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="AMEX EPAYMENT",
            category_id=category.id,
        )
        inflow = await svc.create_transaction(
            account_id=card.id,
            amount=190000,  # $1,900 onto the card (a payment)
            txn_date=date(2026, 6, 2),
            owner_user_id=1,
            name="PAYMENT RECEIVED",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 10)
        )
        assert result.auto_paired == 1

        assert out.is_transfer and out.excluded_from_reports
        assert inflow.is_transfer and inflow.excluded_from_reports

        transfer = (await async_db_session.exec(select(FinanceTransfer))).one()
        assert transfer.status == "confirmed"
        assert transfer.is_credit_card_payment is True

        # The $1,900 must not show up as spend for the month.
        summary = await svc.spending_summary(owner_user_id=1, month="2026-06")
        assert all(name != "Credit Card Payment" for name, _ in summary)

    @pytest.mark.asyncio
    async def test_a_near_miss_is_never_hidden(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Below the auto threshold nothing pairs and nothing hides: a
        fuzzy lookalike (a Venmo to a friend) is real spending until an
        exact match proves otherwise."""
        checking = await _account(svc, "Checking", "checking", "asset")
        savings = await _account(svc, "Savings", "savings", "asset")
        out = await svc.create_transaction(
            account_id=checking.id,
            amount=-190000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="ONLINE TRANSFER",
        )
        inflow = await svc.create_transaction(
            account_id=savings.id,
            amount=185000,  # $50 off, 4 days later -> inexact
            txn_date=date(2026, 6, 5),
            owner_user_id=1,
            name="ONLINE TRANSFER",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 10)
        )

        assert result.auto_paired == 0
        assert out.is_transfer is False
        assert inflow.is_transfer is False
        assert (await async_db_session.exec(select(FinanceTransfer))).all() == []

    @pytest.mark.asyncio
    async def test_same_account_opposite_signs_not_paired(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        await svc.create_transaction(
            account_id=checking.id,
            amount=-500,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="COFFEE",
        )
        await svc.create_transaction(
            account_id=checking.id,
            amount=500,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="COFFEE REFUND",
        )
        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 10)
        )
        assert result.auto_paired == 0

    @pytest.mark.asyncio
    async def test_old_history_outside_the_lookback_is_left_alone(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A decade-deep import must not churn through ancient history;
        only activity inside the configured lookback window is considered."""
        checking = await _account(svc, "Checking", "checking", "asset")
        savings = await _account(svc, "Savings", "savings", "asset")
        await svc.create_transaction(
            account_id=checking.id,
            amount=-50000,
            txn_date=date(2020, 3, 1),
            owner_user_id=1,
            name="ONLINE TRANSFER",
        )
        await svc.create_transaction(
            account_id=savings.id,
            amount=50000,
            txn_date=date(2020, 3, 1),  # exact same-day pair: auto grade
            owner_user_id=1,
            name="ONLINE TRANSFER",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 27)
        )
        assert result.auto_paired == 0

        # The escape hatch: 0 disables the window and processes full
        # history - the same pair now pairs, proving the gate (not the
        # scorer) is what held it back above.
        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 27), lookback_days=0
        )
        assert result.auto_paired == 1

    @pytest.mark.asyncio
    async def test_one_sided_stays_visible(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        out = await svc.create_transaction(
            account_id=checking.id,
            amount=-190000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="AMEX EPAYMENT",
        )
        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 10)
        )
        assert result.auto_paired == 0
        assert out.is_transfer is False


async def _transfer_category(db, name="Transfer:Credit Card Payment"):
    row = FinanceCategory(
        owner_user_id=None,
        name=name,
        slug=name.lower().replace(" ", "-").replace(":", "-"),
        classification="transfer",
    )
    db.add(row)
    await db.flush()
    return row


class TestCategoryClassifiedTransfers:
    """A transaction CATEGORIZED as a transfer is one, even unpaired.

    Pairing needs both legs, and the other leg often is not imported at
    all - a card payment where only the checking side syncs, a "Transfer
    Out" to an account the app has never seen. Measured live: $6,700 a
    month of rows the user's own categories call transfers, sitting in
    every spending figure because no counterpart ever arrived.

    The category classification is the user's own curation (Quicken paths
    fold into categories at import), so it outranks the absence of a
    pair. These flags carry NO ``transfer_group_id`` - that column keeps
    meaning "paired", which is what lets a recategorize undo a category
    flag without ever touching a real pairing.
    """

    @pytest.mark.asyncio
    async def test_a_transfer_categorized_row_is_flagged_without_a_pair(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        category = await _transfer_category(async_db_session)
        txn = await svc.create_transaction(
            account_id=checking.id,
            amount=-333_200,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="CITI CARD ONLINE PAYMENT",
            category_id=category.id,
        )

        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 5)
        )

        assert txn.is_transfer is True
        assert txn.excluded_from_reports is True
        assert txn.transfer_group_id is None  # flagged, not paired

    @pytest.mark.asyncio
    async def test_the_inflow_side_is_flagged_too(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """ "Transfer In" from an unseen account inflates income the same
        way the outflow side inflates spending."""
        checking = await _account(svc, "Checking", "checking", "asset")
        category = await _transfer_category(async_db_session, "Transfer In")
        txn = await svc.create_transaction(
            account_id=checking.id,
            amount=217_200,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="HUD VLY ONLINE",
            category_id=category.id,
        )

        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 5)
        )

        assert txn.is_transfer is True

    @pytest.mark.asyncio
    async def test_an_expense_categorized_row_is_untouched(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        groceries = FinanceCategory(
            owner_user_id=None,
            name="Groceries",
            slug="groceries-t",
            classification="expense",
        )
        async_db_session.add(groceries)
        await async_db_session.flush()
        txn = await svc.create_transaction(
            account_id=checking.id,
            amount=-8_000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="SHOPRITE",
            category_id=groceries.id,
        )

        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 5)
        )

        assert txn.is_transfer is False
        assert txn.excluded_from_reports is False

    @pytest.mark.asyncio
    async def test_pairing_still_wins_when_both_legs_exist(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The category flag is the fallback, not a replacement: two legs
        that CAN pair still get the full pairing (cross-link, transfer
        row, credit-card detection), not two disconnected flags."""
        checking = await _account(svc, "Checking", "checking", "asset")
        card = await _account(svc, "Card", "credit_card", "liability")
        category = await _transfer_category(async_db_session)
        out = await svc.create_transaction(
            account_id=checking.id,
            amount=-190_000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="AMEX EPAYMENT",
            category_id=category.id,
        )
        inflow = await svc.create_transaction(
            account_id=card.id,
            amount=190_000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="PAYMENT RECEIVED",
            category_id=category.id,
        )

        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 5)
        )

        assert out.transfer_group_id is not None  # paired, not just flagged
        assert inflow.transfer_group_id == out.transfer_group_id
        assert out.transfer_pair_transaction_id == inflow.id

    @pytest.mark.asyncio
    async def test_old_rows_are_flagged_despite_the_pairing_lookback(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Pairing has a lookback because deep history accumulates
        COINCIDENTAL amount matches. A category classification is not a
        coincidence - it is what the row says it is, at any age. The live
        rows this exists for span years, and the 6-month spending figures
        they inflate need all of them cleared, not the last 90 days."""
        checking = await _account(svc, "Checking", "checking", "asset")
        category = await _transfer_category(async_db_session)
        txn = await svc.create_transaction(
            account_id=checking.id,
            amount=-100_000,
            txn_date=date(2023, 1, 15),
            owner_user_id=1,
            name="TRANSFER OUT",
            category_id=category.id,
        )

        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 5), lookback_days=90
        )

        assert txn.is_transfer is True


class TestRecategorizeSyncsTheFlag:
    @pytest.mark.asyncio
    async def test_categorizing_as_a_transfer_flags_immediately(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Fixing a miscategorized card payment by hand must fix the
        numbers in the same gesture, not on the next import."""
        checking = await _account(svc, "Checking", "checking", "asset")
        category = await _transfer_category(async_db_session)
        txn = await svc.create_transaction(
            account_id=checking.id,
            amount=-50_000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="CARD PAYMENT",
        )

        await svc.categorize_transaction(txn.id, category.id, owner_user_id=1)

        assert txn.is_transfer is True
        assert txn.excluded_from_reports is True

    @pytest.mark.asyncio
    async def test_recategorizing_away_unflags_a_category_flag(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """ "Actually that was real spending" has to bring the money back."""
        checking = await _account(svc, "Checking", "checking", "asset")
        category = await _transfer_category(async_db_session)
        groceries = FinanceCategory(
            owner_user_id=None,
            name="Groceries",
            slug="groceries-r",
            classification="expense",
        )
        async_db_session.add(groceries)
        await async_db_session.flush()
        txn = await svc.create_transaction(
            account_id=checking.id,
            amount=-50_000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="VENMO",
            category_id=category.id,
        )
        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 5)
        )
        assert txn.is_transfer is True

        await svc.categorize_transaction(txn.id, groceries.id, owner_user_id=1)

        assert txn.is_transfer is False
        assert txn.excluded_from_reports is False

    @pytest.mark.asyncio
    async def test_recategorizing_a_paired_leg_keeps_the_pairing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A pairing is evidence from both sides of the money; a category
        edit on one leg must not dissolve it. Un-pairing is Review's
        reject, which restores both legs together."""
        checking = await _account(svc, "Checking", "checking", "asset")
        card = await _account(svc, "Card", "credit_card", "liability")
        groceries = FinanceCategory(
            owner_user_id=None,
            name="Groceries",
            slug="groceries-p",
            classification="expense",
        )
        async_db_session.add(groceries)
        await async_db_session.flush()
        out = await svc.create_transaction(
            account_id=checking.id,
            amount=-190_000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="AMEX EPAYMENT",
        )
        await svc.create_transaction(
            account_id=card.id,
            amount=190_000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="PAYMENT RECEIVED",
        )
        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 5)
        )
        assert out.transfer_group_id is not None

        await svc.categorize_transaction(out.id, groceries.id, owner_user_id=1)

        assert out.is_transfer is True  # the pairing holds
        assert out.transfer_group_id is not None


class TestAdjustmentPairs:
    """Same-account offsetting pairs of ledger adjustments.

    Amex reshuffles balance between its own buckets as a same-day pair -
    "DR ADJ REDIST CADV PRIN" out, "Adj Redist Bal" back, netting zero.
    Nine such pairs sat in real books inflating spend AND income, one of
    them ($231.71) wearing a critical large-charge finding. Not transfers
    (no money moved between accounts), so they take excluded_from_reports
    only and stay out of the Transfers review queue.
    """

    async def _pair(self, svc, account, day, cents, *, debit_name, credit_name):
        debit = await svc.create_transaction(
            account_id=account.id,
            amount=-cents,
            txn_date=day,
            owner_user_id=1,
            name=debit_name,
        )
        credit = await svc.create_transaction(
            account_id=account.id,
            amount=cents,
            txn_date=day,
            owner_user_id=1,
            name=credit_name,
        )
        return debit, credit

    @pytest.mark.asyncio
    async def test_an_adjustment_pair_drops_out_of_reports(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        card = await _account(svc, "Amex", "credit_card", "liability")
        debit, credit = await self._pair(
            svc,
            card,
            date(2026, 7, 17),
            23_171,
            debit_name="DR ADJ REDIST CADV PRIN XXXX3007",
            credit_name="Adj Redist Bal",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert result.adjustment_flagged == 2
        for leg in (debit, credit):
            await async_db_session.refresh(leg)
            assert leg.excluded_from_reports is True
            # NOT a transfer: money never moved between accounts, and the
            # Transfers review tab must not fill with issuer bookkeeping.
            assert leg.is_transfer is False

    @pytest.mark.asyncio
    async def test_a_same_day_purchase_and_refund_is_left_alone(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The token gate is the safety: equal-and-opposite alone must not
        vanish a real purchase refunded the same day."""
        card = await _account(svc, "Amex", "credit_card", "liability")
        buy, refund = await self._pair(
            svc,
            card,
            date(2026, 7, 17),
            5_000,
            debit_name="MERRITT BOOKSTORE",
            credit_name="MERRITT BOOKSTORE REFUND",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert result.adjustment_flagged == 0
        for leg in (buy, refund):
            await async_db_session.refresh(leg)
            assert leg.excluded_from_reports is False

    @pytest.mark.asyncio
    async def test_unbalanced_amounts_never_flag(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        card = await _account(svc, "Amex", "credit_card", "liability")
        await svc.create_transaction(
            account_id=card.id,
            amount=-23_171,
            txn_date=date(2026, 7, 17),
            owner_user_id=1,
            name="DR ADJ REDIST CADV PRIN XXXX3007",
        )
        await svc.create_transaction(
            account_id=card.id,
            amount=23_100,
            txn_date=date(2026, 7, 17),
            owner_user_id=1,
            name="Adj Redist Bal",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert result.adjustment_flagged == 0

    @pytest.mark.asyncio
    async def test_different_days_never_flag(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A reversal that lands the NEXT day is plausible but ambiguous;
        the rule stays strict and leaves it for a human."""
        card = await _account(svc, "Amex", "credit_card", "liability")
        await svc.create_transaction(
            account_id=card.id,
            amount=-23_171,
            txn_date=date(2026, 7, 17),
            owner_user_id=1,
            name="DR ADJ REDIST CADV PRIN XXXX3007",
        )
        await svc.create_transaction(
            account_id=card.id,
            amount=23_171,
            txn_date=date(2026, 7, 18),
            owner_user_id=1,
            name="Adj Redist Bal",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert result.adjustment_flagged == 0

    @pytest.mark.asyncio
    async def test_a_rerun_is_idempotent(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        card = await _account(svc, "Amex", "credit_card", "liability")
        await self._pair(
            svc,
            card,
            date(2026, 7, 17),
            23_171,
            debit_name="DR ADJ REDIST CADV PRIN XXXX3007",
            credit_name="Adj Redist Bal",
        )

        first = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )
        second = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert first.adjustment_flagged == 2
        assert second.adjustment_flagged == 0

    @pytest.mark.asyncio
    async def test_two_same_amount_pairs_flag_one_to_one(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Three debits against two credits of one amount: exactly two
        pairs form; the odd debit stays in reports."""
        card = await _account(svc, "Amex", "credit_card", "liability")
        day = date(2026, 7, 17)
        for _ in range(3):
            await svc.create_transaction(
                account_id=card.id,
                amount=-1_000,
                txn_date=day,
                owner_user_id=1,
                name="DR ADJ REDIST CADV PRIN XXXX3007",
            )
        for _ in range(2):
            await svc.create_transaction(
                account_id=card.id,
                amount=1_000,
                txn_date=day,
                owner_user_id=1,
                name="Adj Redist Bal",
            )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert result.adjustment_flagged == 4

    @pytest.mark.asyncio
    async def test_old_pairs_are_caught_without_a_lookback(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Same reasoning as the category phase: an offsetting adjustment
        pair is not a coincidence at any age, and a 2024 pair inflates
        every historical figure until it is neutralized."""
        card = await _account(svc, "Amex", "credit_card", "liability")
        debit, credit = await self._pair(
            svc,
            card,
            date(2024, 9, 16),
            309,
            debit_name="DR ADJ REDIST CADV PRIN XXXX--X3007",
            credit_name="Adj Redist Bal",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 20)
        )

        assert result.adjustment_flagged == 2


class TestPaymentHistoryPairing:
    """Years of card payments pair up regardless of the pairing lookback.

    The lookback window protects ordinary pairing from coincidental
    matches in deep history - but it left an entire Amex payment history
    unpaired (one pair out of three years, confirmed live), and the
    category phase's flag made it worse: flagged rows are excluded from
    pairing candidates entirely, so history could NEVER pair. A
    liability-destination pair with an exact amount and a tight date
    window is not a coincidence at any age.
    """

    async def _accounts(self, svc):
        checking = await _account(svc, "Checking", "checking", "asset")
        card = await _account(svc, "Amex", "credit_card", "liability")
        return checking, card

    async def _flagged_pair(self, svc, db, checking, card, day, cents):
        """A historical payment pair the category phase already flagged
        (is_transfer, excluded, no group) - the live shape."""
        legs = []
        for account, amount, name in (
            (checking, -cents, "American Express"),
            (card, cents, "AUTOPAY PAYMENT - THANK YOU"),
        ):
            txn = await svc.create_transaction(
                account_id=account.id,
                amount=amount,
                txn_date=day,
                owner_user_id=1,
                name=name,
            )
            txn.is_transfer = True
            txn.excluded_from_reports = True
            db.add(txn)
            legs.append(txn)
        await db.flush()
        return legs

    @pytest.mark.asyncio
    async def test_old_flagged_payments_pair_confirmed(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking, card = await self._accounts(svc)
        out_leg, in_leg = await self._flagged_pair(
            svc, async_db_session, checking, card, date(2025, 6, 10), 170_490
        )

        result = await detect_transfers(
            async_db_session,
            owner_user_id=1,
            today=date(2026, 8, 9),
            lookback_days=90,
        )

        assert result.payment_paired == 1
        await async_db_session.refresh(out_leg)
        await async_db_session.refresh(in_leg)
        assert out_leg.transfer_group_id is not None
        assert out_leg.transfer_group_id == in_leg.transfer_group_id
        row = (
            await async_db_session.exec(
                select(FinanceTransfer).where(
                    FinanceTransfer.id == out_leg.transfer_group_id
                )
            )
        ).one()
        assert row.status == "confirmed"
        assert row.is_credit_card_payment is True

    @pytest.mark.asyncio
    async def test_old_asset_to_asset_history_is_left_alone(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The precision comes FROM the liability destination; without it
        this is exactly the coincidental-match noise the lookback exists
        to prevent."""
        checking = await _account(svc, "Checking", "checking", "asset")
        savings = await _account(svc, "Savings", "savings", "asset")
        for account, amount in ((checking, -50_000), (savings, 50_000)):
            await svc.create_transaction(
                account_id=account.id,
                amount=amount,
                txn_date=date(2025, 6, 10),
                owner_user_id=1,
                name="TRANSFER",
            )

        result = await detect_transfers(
            async_db_session,
            owner_user_id=1,
            today=date(2026, 8, 9),
            lookback_days=90,
        )

        assert result.payment_paired == 0

    @pytest.mark.asyncio
    async def test_amounts_must_match_exactly(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking, card = await self._accounts(svc)
        for account, amount, name in (
            (checking, -170_490, "American Express"),
            (card, 170_400, "AUTOPAY PAYMENT"),
        ):
            await svc.create_transaction(
                account_id=account.id,
                amount=amount,
                txn_date=date(2025, 6, 10),
                owner_user_id=1,
                name=name,
            )

        result = await detect_transfers(
            async_db_session,
            owner_user_id=1,
            today=date(2026, 8, 9),
            lookback_days=90,
        )

        assert result.payment_paired == 0

    @pytest.mark.asyncio
    async def test_a_rerun_pairs_nothing_twice(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking, card = await self._accounts(svc)
        await self._flagged_pair(
            svc, async_db_session, checking, card, date(2025, 6, 10), 170_490
        )

        first = await detect_transfers(
            async_db_session,
            owner_user_id=1,
            today=date(2026, 8, 9),
            lookback_days=90,
        )
        second = await detect_transfers(
            async_db_session,
            owner_user_id=1,
            today=date(2026, 8, 9),
            lookback_days=90,
        )

        assert first.payment_paired == 1
        assert second.payment_paired == 0
