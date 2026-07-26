"""Tests for internal-transfer detection + pairing (FIN-26).

Covers the ticket's acceptance scenarios: a credit-card payment auto-pairs and
drops out of spend; a near-miss is only *suggested* (never silently hidden) and
confirm/reject behave; same-account and one-sided cases never pair.
"""

from datetime import date

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.categorize import detect_transfers
from app.services.finance.finance_service import FinanceService
from app.services.finance.models import FinanceCategory, FinanceTransfer


async def _account(svc, name, account_type, classification):
    return await svc.create_manual_account(
        name=name,
        account_type=account_type,
        classification=classification,
        owner_user_id=1,
    )


class TestTransferDetection:
    @pytest.mark.asyncio
    async def test_credit_card_payment_auto_pairs_and_excludes_spend(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        assert result.suggested == 0

        assert out.is_transfer and out.excluded_from_reports
        assert inflow.is_transfer and inflow.excluded_from_reports

        transfer = (await async_db_session.exec(select(FinanceTransfer))).one()
        assert transfer.status == "confirmed"
        assert transfer.is_credit_card_payment is True

        # The $1,900 must not show up as spend for the month.
        summary = await svc.spending_summary(owner_user_id=1, month="2026-06")
        assert all(name != "Credit Card Payment" for name, _ in summary)

    @pytest.mark.asyncio
    async def test_near_miss_is_suggested_not_hidden_then_confirm(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        assert result.suggested == 1
        assert result.auto_paired == 0
        # NEVER hidden below the auto threshold.
        assert out.is_transfer is False
        assert inflow.is_transfer is False

        transfer = (await async_db_session.exec(select(FinanceTransfer))).one()
        assert transfer.status == "suggested"

        confirmed = await svc.confirm_transfer(transfer.id, owner_user_id=1)
        assert confirmed is not None and confirmed.status == "confirmed"
        assert out.is_transfer and inflow.is_transfer

    @pytest.mark.asyncio
    async def test_reject_leaves_legs_and_never_resuggests(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await _account(svc, "Checking", "checking", "asset")
        savings = await _account(svc, "Savings", "savings", "asset")
        out = await svc.create_transaction(
            account_id=checking.id,
            amount=-190000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="ONLINE TRANSFER",
        )
        await svc.create_transaction(
            account_id=savings.id,
            amount=185000,
            txn_date=date(2026, 6, 5),
            owner_user_id=1,
            name="ONLINE TRANSFER",
        )
        await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 10)
        )
        transfer = (await async_db_session.exec(select(FinanceTransfer))).one()

        rejected = await svc.reject_transfer(transfer.id, owner_user_id=1)
        assert rejected is not None and rejected.status == "rejected"
        assert out.is_transfer is False and out.excluded_from_reports is False

        # Re-running must NOT re-suggest the rejected pair.
        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 6, 10)
        )
        assert result.suggested == 0
        transfers = (await async_db_session.exec(select(FinanceTransfer))).all()
        assert len(transfers) == 1  # still just the rejected row

    @pytest.mark.asyncio
    async def test_same_account_opposite_signs_not_paired(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        assert result.suggested == 0

    @pytest.mark.asyncio
    async def test_old_history_outside_the_lookback_is_left_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        """A decade-deep import must not bury Review under ancient pairs;
        only activity inside the configured lookback window is considered."""
        svc = FinanceService(async_db_session)
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
            txn_date=date(2020, 3, 2),
            owner_user_id=1,
            name="ONLINE TRANSFER",
        )

        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 27)
        )
        assert result.auto_paired == 0
        assert result.suggested == 0

        # The escape hatch: 0 disables the window and processes full history.
        result = await detect_transfers(
            async_db_session, owner_user_id=1, today=date(2026, 7, 27), lookback_days=0
        )
        assert result.suggested == 1

    @pytest.mark.asyncio
    async def test_one_sided_stays_visible(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        assert result.suggested == 0
        assert out.is_transfer is False
