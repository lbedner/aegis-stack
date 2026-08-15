"""Account reconciliation (FIN-37).

The whole design is one invariant: reconciliation lives in BALANCE-space,
never spend-space. The delta lands as a transfer-flagged adjustment (or a
valuation when there is no register), so charts, detection, insights, and
budget math never see a fake expense - these tests pin each of those
invisibility claims, plus idempotency and the import-pipeline guard.
"""

from datetime import date

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.finance_service import RECONCILE_MARKER, FinanceService
from app.services.finance.models import FinanceTransaction, FinanceValuation

STATEMENT_DAY = date(2026, 8, 1)


async def _checking(svc: FinanceService):
    return await svc.create_manual_account(
        owner_user_id=1,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
    )


async def _seed_register(svc: FinanceService, account_id: int) -> int:
    """A tiny register: +$1,000 pay, -$300 rent. Returns its sum (cents)."""
    await svc.create_transaction(
        account_id=account_id,
        amount=100_000,
        txn_date=date(2026, 7, 20),
        owner_user_id=1,
        name="Payroll",
    )
    await svc.create_transaction(
        account_id=account_id,
        amount=-30_000,
        txn_date=date(2026, 7, 25),
        owner_user_id=1,
        name="Rent",
    )
    return 70_000


class TestReconcileAdjustment:
    @pytest.mark.asyncio
    async def test_adjustment_fixes_register_and_stays_out_of_spend(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _checking(svc)
        register = await _seed_register(svc, account.id)
        statement = register - 12_345  # the bank says we have less

        before_spend = dict(
            await svc.spending_summary(owner_user_id=1, month="2026-08")
        )
        result = await svc.reconcile_account(
            account.id,
            owner_user_id=1,
            statement_date=STATEMENT_DAY,
            statement_balance=statement,
        )
        assert result is not None and result["applied"]
        assert result["delta"] == -12_345

        # The register now agrees with the statement...
        assert await svc._register_balance_as_of(account.id, STATEMENT_DAY) == statement
        adjustment = await async_db_session.get(
            FinanceTransaction, result["adjustment_transaction_id"]
        )
        assert adjustment is not None
        assert adjustment.is_transfer is True
        assert adjustment.external_id_source == RECONCILE_MARKER
        # ...and spending never saw the correction (transfers excluded).
        after_spend = dict(await svc.spending_summary(owner_user_id=1, month="2026-08"))
        assert after_spend == before_spend
        # Headline balance + waterline follow the statement.
        assert account.current_balance == statement
        assert account.metadata_["reconciled_through"] == STATEMENT_DAY.isoformat()

    @pytest.mark.asyncio
    async def test_reconcile_is_idempotent_per_date(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _checking(svc)
        register = await _seed_register(svc, account.id)

        first = await svc.reconcile_account(
            account.id,
            owner_user_id=1,
            statement_date=STATEMENT_DAY,
            statement_balance=register - 5_000,
        )
        second = await svc.reconcile_account(
            account.id,
            owner_user_id=1,
            statement_date=STATEMENT_DAY,
            statement_balance=register - 9_000,
        )
        # Same date -> the same adjustment row, re-measured; never stacked.
        assert second["adjustment_transaction_id"] == first["adjustment_transaction_id"]
        assert second["delta"] == -9_000
        adjustments = (
            await async_db_session.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.external_id_source == RECONCILE_MARKER,
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
        assert len(adjustments) == 1

        # A statement that exactly matches removes the adjustment outright.
        third = await svc.reconcile_account(
            account.id,
            owner_user_id=1,
            statement_date=STATEMENT_DAY,
            statement_balance=register,
        )
        assert third["delta"] == 0
        assert third["adjustment_transaction_id"] is None
        remaining = (
            await async_db_session.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.external_id_source == RECONCILE_MARKER,
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
        assert remaining == []

    @pytest.mark.asyncio
    async def test_import_inserts_beside_adjustment_never_edits_it(
        self, async_db_session: AsyncSession
    ) -> None:
        """LANE-3 edit matching must not claim an adjustment: an import row
        landing on its (date, amount) is new money, not a rename of the
        correction."""
        from app.services.finance.import_service import plan_transactions
        from app.services.finance.importers.base import ParsedTransaction

        svc = FinanceService(async_db_session)
        account = await _checking(svc)
        register = await _seed_register(svc, account.id)
        result = await svc.reconcile_account(
            account.id,
            owner_user_id=1,
            statement_date=STATEMENT_DAY,
            statement_balance=register - 12_345,
        )
        plan = await plan_transactions(
            async_db_session,
            owner_user_id=1,
            parsed=[
                ParsedTransaction(
                    date=STATEMENT_DAY,
                    amount=result["delta"],
                    name="Some Real Merchant",
                    source="qif",
                )
            ],
            default_account_id=account.id,
        )
        assert [row.status for row in plan.rows] == ["inserted"]

    @pytest.mark.asyncio
    async def test_transfer_pairing_never_claims_an_adjustment(
        self, async_db_session: AsyncSession
    ) -> None:
        """detect_transfers filters ``is_transfer`` rows out of its
        candidates, so an adjustment can never be paired as a transfer leg
        - pin it in case that filter ever loosens."""
        from app.services.finance.categorize import detect_transfers

        svc = FinanceService(async_db_session)
        account = await _checking(svc)
        register = await _seed_register(svc, account.id)
        other = await svc.create_manual_account(
            owner_user_id=1,
            name="Chase Savings",
            account_type="savings",
            classification="asset",
        )
        result = await svc.reconcile_account(
            account.id,
            owner_user_id=1,
            statement_date=STATEMENT_DAY,
            statement_balance=register - 12_345,
        )
        # A same-day opposite leg that WOULD pair with the adjustment.
        await svc.create_transaction(
            account_id=other.id,
            amount=12_345,
            txn_date=STATEMENT_DAY,
            owner_user_id=1,
            name="Transfer in",
        )
        await detect_transfers(async_db_session, owner_user_id=1)
        adjustment = await async_db_session.get(
            FinanceTransaction, result["adjustment_transaction_id"]
        )
        assert adjustment.transfer_group_id is None


class TestReconcileValuationRoute:
    @pytest.mark.asyncio
    async def test_no_register_routes_to_valuation(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            owner_user_id=1,
            name="House Bedner",
            account_type="property",
            classification="asset",
        )
        result = await svc.reconcile_account(
            account.id,
            owner_user_id=1,
            statement_date=STATEMENT_DAY,
            statement_balance=565_000_00,
        )
        assert result["route"] == "valuation"
        assert result["adjustment_transaction_id"] is None
        valuations = (
            await async_db_session.exec(
                select(FinanceValuation).where(
                    FinanceValuation.account_id == account.id
                )
            )
        ).all()
        assert [v.value for v in valuations] == [565_000_00]
        # No transaction was minted - the register stays empty.
        txns = (
            await async_db_session.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.account_id == account.id,
                    FinanceTransaction.deleted_at.is_(None),
                )
            )
        ).all()
        assert txns == []
        assert account.current_balance == 565_000_00
        assert account.metadata_["reconciled_through"] == STATEMENT_DAY.isoformat()


class TestReconcilePreview:
    @pytest.mark.asyncio
    async def test_preview_writes_nothing(self, async_db_session: AsyncSession) -> None:
        svc = FinanceService(async_db_session)
        account = await _checking(svc)
        register = await _seed_register(svc, account.id)
        preview = await svc.reconcile_preview(
            account.id,
            owner_user_id=1,
            statement_date=STATEMENT_DAY,
            statement_balance=register - 12_345,
        )
        assert preview["delta"] == -12_345
        assert preview["applied"] is False
        adjustments = (
            await async_db_session.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.external_id_source == RECONCILE_MARKER
                )
            )
        ).all()
        assert adjustments == []
        assert "reconciled_through" not in (account.metadata_ or {})
