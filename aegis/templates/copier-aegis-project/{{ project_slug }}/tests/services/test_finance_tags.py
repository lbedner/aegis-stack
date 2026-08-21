"""Tags on transactions: the user-defined flag.

The tables (``FinanceTag`` + ``FinanceTransactionTag``) predate this and
were only ever written by the Quicken import. These tests pin the service
surface that makes them a feature: attach and detach by hand, read them
back in batch (no per-row queries), and filter the register by one.

A "flag" is deliberately NOT a dedicated bit - it is whatever tag the
user invents ("Flagged", "Check with Sarah", "Tax 2026"), so one
mechanism covers follow-ups, trips, and audits alike.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService


async def _three_transactions(
    svc: FinanceService,
) -> tuple[int, list[int]]:
    account = await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )
    ids = []
    for day, amount in ((1, -4_200), (2, -1_150), (3, -980)):
        txn = await svc.create_transaction(
            account_id=account.id,
            amount=amount,
            txn_date=date(2026, 8, day),
            owner_user_id=1,
            name=f"Purchase {day}",
        )
        ids.append(txn.id)
    return account.id, ids


class TestAttachDetach:
    @pytest.mark.asyncio
    async def test_tagging_creates_the_tag_and_attaches_it(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        _, ids = await _three_transactions(svc)

        tag = await svc.tag_transactions(ids[:2], "Flagged", owner_user_id=1)

        assert tag.id is not None
        by_txn = await svc.transaction_tags(ids)
        assert [t.name for t in by_txn[ids[0]]] == ["Flagged"]
        assert [t.name for t in by_txn[ids[1]]] == ["Flagged"]
        assert by_txn[ids[2]] == []

    @pytest.mark.asyncio
    async def test_tagging_is_idempotent_and_reuses_by_normalized_name(
        self, async_db_session: AsyncSession
    ) -> None:
        """Re-flagging an already-flagged row must not blow up on the
        composite PK, and "flagged" lands ON "Flagged", not beside it."""
        svc = FinanceService(async_db_session)
        _, ids = await _three_transactions(svc)

        first = await svc.tag_transactions(ids[:1], "Flagged", owner_user_id=1)
        second = await svc.tag_transactions(ids[:2], "flagged", owner_user_id=1)

        assert second.id == first.id
        by_txn = await svc.transaction_tags(ids[:2])
        assert [t.name for t in by_txn[ids[0]]] == ["Flagged"]
        assert [t.name for t in by_txn[ids[1]]] == ["Flagged"]

    @pytest.mark.asyncio
    async def test_untagging_removes_only_the_join_rows(
        self, async_db_session: AsyncSession
    ) -> None:
        """Removing a flag never deletes the tag itself or its other
        attachments - unflagging one transaction must not strip the rest."""
        svc = FinanceService(async_db_session)
        _, ids = await _three_transactions(svc)
        tag = await svc.tag_transactions(ids, "Flagged", owner_user_id=1)

        removed = await svc.untag_transactions(ids[:1], tag.id, owner_user_id=1)

        assert removed == 1
        by_txn = await svc.transaction_tags(ids)
        assert by_txn[ids[0]] == []
        assert [t.name for t in by_txn[ids[1]]] == ["Flagged"]
        tags = await svc.list_tags(owner_user_id=1)
        assert [t.name for t, _count in tags] == ["Flagged"]


class TestDirectory:
    @pytest.mark.asyncio
    async def test_list_tags_carries_usage_counts(
        self, async_db_session: AsyncSession
    ) -> None:
        """The count is what makes the list a directory - which flags are
        live versus leftovers - and it must be batched, not per-tag."""
        svc = FinanceService(async_db_session)
        _, ids = await _three_transactions(svc)
        await svc.tag_transactions(ids, "Flagged", owner_user_id=1)
        await svc.tag_transactions(ids[:1], "Tax 2026", owner_user_id=1)
        unused = await svc.get_or_create_tag("Vacation", owner_user_id=1)

        tags = await svc.list_tags(owner_user_id=1)

        by_name = {t.name: count for t, count in tags}
        assert by_name == {"Flagged": 3, "Tax 2026": 1, "Vacation": 0}
        assert unused.id is not None


class TestRegisterFilter:
    @pytest.mark.asyncio
    async def test_list_transactions_filters_by_tag(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        _, ids = await _three_transactions(svc)
        tag = await svc.tag_transactions(ids[1:], "Flagged", owner_user_id=1)

        rows, total = await svc.list_transactions(owner_user_id=1, tag_id=tag.id)

        assert total == 2
        assert {r.id for r in rows} == set(ids[1:])

    @pytest.mark.asyncio
    async def test_no_tag_filter_means_no_filter(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        _, ids = await _three_transactions(svc)
        await svc.tag_transactions(ids[:1], "Flagged", owner_user_id=1)

        _rows, total = await svc.list_transactions(owner_user_id=1)

        assert total == 3
