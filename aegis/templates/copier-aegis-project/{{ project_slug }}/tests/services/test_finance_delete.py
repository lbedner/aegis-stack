"""Deleting a transaction: the one ledger object that had no delete verb.

Soft delete (``deleted_at``), matching accounts and bills - every read
path already filters it, so a deleted row vanishes from the register,
budgets, and projections without any recompute step. The rules pinned
here are the linked-row ones: a transfer survivor is unpaired (the money
movement on the other account still happened), and a split parent takes
its split lines with it.
"""

from datetime import date

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinanceTransactionSplit
from app.services.finance.service import FinanceService


async def _account(svc: FinanceService, name: str = "Checking") -> int:
    account = await svc.create_manual_account(
        name=name,
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )
    return account.id


class TestSoftDelete:
    @pytest.mark.asyncio
    async def test_deleted_rows_leave_the_register(self, svc: FinanceService) -> None:
        account_id = await _account(svc)
        keep = await svc.create_transaction(
            account_id=account_id,
            amount=-1_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="Keep",
        )
        drop = await svc.create_transaction(
            account_id=account_id,
            amount=-2_000,
            txn_date=date(2026, 8, 2),
            owner_user_id=1,
            name="Drop",
        )

        deleted = await svc.soft_delete_transactions([drop.id], owner_user_id=1)

        assert deleted == 1
        rows, total = await svc.list_transactions(owner_user_id=1)
        assert total == 1
        assert [r.id for r in rows] == [keep.id]

    @pytest.mark.asyncio
    async def test_deleting_is_scoped_to_the_owner(self, svc: FinanceService) -> None:
        account_id = await _account(svc)
        txn = await svc.create_transaction(
            account_id=account_id,
            amount=-1_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="Mine",
        )

        deleted = await svc.soft_delete_transactions([txn.id], owner_user_id=2)

        assert deleted == 0
        _rows, total = await svc.list_transactions(owner_user_id=1)
        assert total == 1

    @pytest.mark.asyncio
    async def test_deleting_twice_is_a_no_op(self, svc: FinanceService) -> None:
        account_id = await _account(svc)
        txn = await svc.create_transaction(
            account_id=account_id,
            amount=-1_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="Once",
        )

        assert await svc.soft_delete_transactions([txn.id], owner_user_id=1) == 1
        assert await svc.soft_delete_transactions([txn.id], owner_user_id=1) == 0


class TestLinkedRows:
    @pytest.mark.asyncio
    async def test_deleting_one_transfer_leg_unpairs_the_survivor(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The other account's money movement still happened - it comes
        back into view as a normal row instead of staying hidden as half
        of a pair that no longer exists."""
        checking = await _account(svc, "Checking")
        card = await _account(svc, "Card")
        out_leg = await svc.create_transaction(
            account_id=checking,
            amount=-50_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="Payment out",
        )
        in_leg = await svc.create_transaction(
            account_id=card,
            amount=50_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="Payment in",
        )
        out_leg.is_transfer = True
        in_leg.is_transfer = True
        out_leg.transfer_pair_transaction_id = in_leg.id
        in_leg.transfer_pair_transaction_id = out_leg.id
        await async_db_session.flush()

        await svc.soft_delete_transactions([out_leg.id], owner_user_id=1)

        rows, total = await svc.list_transactions(owner_user_id=1)
        assert total == 1
        survivor = rows[0]
        assert survivor.id == in_leg.id
        assert survivor.is_transfer is False
        assert survivor.transfer_pair_transaction_id is None

    @pytest.mark.asyncio
    async def test_deleting_both_legs_together_unpairs_nothing_back(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc, "Checking")
        card = await _account(svc, "Card")
        out_leg = await svc.create_transaction(
            account_id=checking,
            amount=-50_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="Payment out",
        )
        in_leg = await svc.create_transaction(
            account_id=card,
            amount=50_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="Payment in",
        )
        out_leg.is_transfer = in_leg.is_transfer = True
        out_leg.transfer_pair_transaction_id = in_leg.id
        in_leg.transfer_pair_transaction_id = out_leg.id
        await async_db_session.flush()

        deleted = await svc.soft_delete_transactions(
            [out_leg.id, in_leg.id], owner_user_id=1
        )

        assert deleted == 2
        _rows, total = await svc.list_transactions(
            owner_user_id=1, include_transfers=True
        )
        assert total == 0

    @pytest.mark.asyncio
    async def test_a_split_parent_takes_its_lines_with_it(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account_id = await _account(svc)
        parent = await svc.create_transaction(
            account_id=account_id,
            amount=-10_000,
            txn_date=date(2026, 8, 1),
            owner_user_id=1,
            name="Split parent",
            is_split=True,
        )
        async_db_session.add(
            FinanceTransactionSplit(
                parent_transaction_id=parent.id,
                owner_user_id=1,
                amount=-10_000,
                sort_order=0,
            )
        )
        await async_db_session.flush()

        await svc.soft_delete_transactions([parent.id], owner_user_id=1)

        splits = (
            await async_db_session.exec(
                select(FinanceTransactionSplit).where(
                    FinanceTransactionSplit.parent_transaction_id == parent.id
                )
            )
        ).all()
        assert splits == []
