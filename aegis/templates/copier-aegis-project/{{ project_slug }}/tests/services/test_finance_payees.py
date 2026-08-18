"""Tests for managing payees directly, rather than as a side effect.

Until now the ONLY way to set a payee's website was the No payee tab's
group dialog, which also re-filed the transactions it was opened on - so
correcting a logo meant assigning rows you may not have wanted to touch,
and a payee whose backlog was already empty could not be edited at all.
These cover the direct path that replaces it.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_payee_txn as _txn


class TestUpdateMerchant:
    @pytest.mark.asyncio
    async def test_website_can_be_changed_without_touching_transactions(
        self, async_db_session: AsyncSession
    ) -> None:
        """The whole point: fixing a logo is not a filing decision."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txn = await _txn(svc, account.id, "CITIZENS BANK", date(2026, 7, 1), -5_000)
        merchant = await svc.create_merchant("Citizens", owner_user_id=1)
        await svc.assign_merchant([txn.id], merchant.id, owner_user_id=1)

        updated = await svc.update_merchant(
            merchant.id, website_url="citizensbank.com", owner_user_id=1
        )

        assert updated is not None
        assert updated.website_url == "citizensbank.com"
        await async_db_session.refresh(txn)
        assert txn.merchant_id == merchant.id  # unchanged

    @pytest.mark.asyncio
    async def test_a_payee_with_no_backlog_is_still_editable(
        self, async_db_session: AsyncSession
    ) -> None:
        """The dead end being removed - the old path needed unassigned
        transactions to exist before it would let you edit anything."""
        svc = FinanceService(async_db_session)
        merchant = await svc.create_merchant("Citizens", owner_user_id=1)

        updated = await svc.update_merchant(
            merchant.id, website_url="citizensbank.com", owner_user_id=1
        )

        assert updated is not None
        assert updated.website_url == "citizensbank.com"

    @pytest.mark.asyncio
    async def test_renaming_a_payee_keeps_its_transactions(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txn = await _txn(svc, account.id, "SQ *JOES", date(2026, 7, 1), -500)
        merchant = await svc.create_merchant("Joes", owner_user_id=1)
        await svc.assign_merchant([txn.id], merchant.id, owner_user_id=1)

        updated = await svc.update_merchant(
            merchant.id, name="Joe's Coffee", owner_user_id=1
        )

        assert updated is not None and updated.name == "Joe's Coffee"
        await async_db_session.refresh(txn)
        assert txn.merchant_id == merchant.id

    @pytest.mark.asyncio
    async def test_omitted_fields_are_left_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        """A partial edit must not blank the fields it did not mention -
        setting a website should not wipe the default category."""
        svc = FinanceService(async_db_session)
        merchant = await svc.create_merchant(
            "Citizens", owner_user_id=1, website_url="citizens.com"
        )
        merchant.default_category_id = None
        await svc.update_merchant(merchant.id, name="Citizens Bank", owner_user_id=1)

        refreshed = await svc.update_merchant(merchant.id, owner_user_id=1)

        assert refreshed is not None
        assert refreshed.name == "Citizens Bank"
        assert refreshed.website_url == "citizens.com"  # survived the rename

    @pytest.mark.asyncio
    async def test_a_blank_website_clears_it(
        self, async_db_session: AsyncSession
    ) -> None:
        """Distinct from omitting it: an empty string is a deliberate
        "stop guessing from this address"."""
        svc = FinanceService(async_db_session)
        merchant = await svc.create_merchant(
            "Citizens", owner_user_id=1, website_url="wrong.com"
        )

        updated = await svc.update_merchant(
            merchant.id, website_url="", owner_user_id=1
        )

        assert updated is not None
        assert updated.website_url is None

    @pytest.mark.asyncio
    async def test_an_unknown_payee_returns_none(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        assert await svc.update_merchant(9_999, name="Nope", owner_user_id=1) is None


class TestMerchantUsage:
    """The table needs weight, not just names - which payee is worth
    correcting is a function of how much money runs through it."""

    @pytest.mark.asyncio
    async def test_usage_counts_totals_and_last_seen(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        merchant = await svc.create_merchant("Acme", owner_user_id=1)
        txns = [
            await _txn(svc, account.id, "ACME", date(2026, m, 4), -1_000)
            for m in range(1, 4)
        ]
        await svc.assign_merchant([t.id for t in txns], merchant.id, owner_user_id=1)

        usage = await svc.merchant_usage(owner_user_id=1)

        assert usage[merchant.id]["count"] == 3
        assert usage[merchant.id]["total_amount"] == -3_000
        assert usage[merchant.id]["last_date"] == date(2026, 3, 4)

    @pytest.mark.asyncio
    async def test_a_payee_with_no_transactions_is_absent(
        self, async_db_session: AsyncSession
    ) -> None:
        """Absent rather than zero-filled: the caller defaults it, and a
        grouped query has nothing to report for an unused payee."""
        svc = FinanceService(async_db_session)
        merchant = await svc.create_merchant("Unused", owner_user_id=1)

        usage = await svc.merchant_usage(owner_user_id=1)

        assert merchant.id not in usage


class TestPayeeTransactions:
    """The drill-down reads the register's own endpoint rather than
    slicing client-side - a busy payee here is over a thousand rows."""

    @pytest.mark.asyncio
    async def test_transactions_filter_to_one_payee(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        target = await svc.create_merchant("Target", owner_user_id=1)
        mine = [
            await _txn(svc, account.id, "TARGET T-1234", date(2026, m, 4), -1_000)
            for m in range(1, 4)
        ]
        other = await _txn(svc, account.id, "STARBUCKS", date(2026, 5, 1), -600)
        await svc.assign_merchant([t.id for t in mine], target.id, owner_user_id=1)

        rows, total = await svc.list_transactions(
            owner_user_id=1, merchant_id=target.id, page_size=500
        )

        assert total == 3
        assert {r.id for r in rows} == {t.id for t in mine}
        assert other.id not in {r.id for r in rows}


class TestMergeMerchants:
    """Two payees for one merchant is the normal end state of naming things
    by hand - "Shop Rite" and "ShopRite" both exist here, 248 and 219
    transactions. Renaming one to match the other does NOT join them (they
    are still two rows), so merging has to be its own deliberate action.
    """

    @pytest.mark.asyncio
    async def test_transactions_move_to_the_survivor(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        keep = await svc.create_merchant("Shop Rite", owner_user_id=1)
        drop = await svc.create_merchant("ShopRite", owner_user_id=1)
        mine = [
            await _txn(svc, account.id, "SHOPRITE 123", date(2026, m, 4), -1_000)
            for m in range(1, 4)
        ]
        theirs = await _txn(svc, account.id, "SHOP RITE", date(2026, 5, 1), -2_000)
        await svc.assign_merchant([t.id for t in mine], drop.id, owner_user_id=1)
        await svc.assign_merchant([theirs.id], keep.id, owner_user_id=1)

        moved = await svc.merge_merchants([drop.id], keep.id, owner_user_id=1)

        assert moved == 3
        usage = await svc.merchant_usage(owner_user_id=1)
        assert usage[keep.id]["count"] == 4

    @pytest.mark.asyncio
    async def test_the_merged_payee_disappears_from_the_directory(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        keep = await svc.create_merchant("Shop Rite", owner_user_id=1)
        drop = await svc.create_merchant("ShopRite", owner_user_id=1)

        await svc.merge_merchants([drop.id], keep.id, owner_user_id=1)

        names = {m.id for m in await svc.list_merchants(owner_user_id=1)}
        assert keep.id in names
        assert drop.id not in names

    @pytest.mark.asyncio
    async def test_a_website_is_inherited_only_when_the_survivor_lacks_one(
        self, async_db_session: AsyncSession
    ) -> None:
        """Merging should not throw away the one piece of curation the
        loser had - but it must never overwrite the winner's."""
        svc = FinanceService(async_db_session)
        bare = await svc.create_merchant("Shop Rite", owner_user_id=1)
        curated = await svc.create_merchant(
            "ShopRite", owner_user_id=1, website_url="shoprite.com"
        )

        await svc.merge_merchants([curated.id], bare.id, owner_user_id=1)

        survivor = await svc.update_merchant(bare.id, owner_user_id=1)
        assert survivor is not None
        assert survivor.website_url == "shoprite.com"

    @pytest.mark.asyncio
    async def test_the_survivors_own_website_wins(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        keep = await svc.create_merchant(
            "Shop Rite", owner_user_id=1, website_url="right.com"
        )
        drop = await svc.create_merchant(
            "ShopRite", owner_user_id=1, website_url="wrong.com"
        )

        await svc.merge_merchants([drop.id], keep.id, owner_user_id=1)

        survivor = await svc.update_merchant(keep.id, owner_user_id=1)
        assert survivor is not None
        assert survivor.website_url == "right.com"

    @pytest.mark.asyncio
    async def test_recurring_streams_follow_the_survivor(
        self, async_db_session: AsyncSession
    ) -> None:
        """A bill still pointing at a payee that no longer exists would
        lose its name and its icon."""
        from app.services.finance.domains.detection import declare_recurring

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        keep = await svc.create_merchant("Shop Rite", owner_user_id=1)
        drop = await svc.create_merchant("ShopRite", owner_user_id=1)
        txns = [
            await _txn(svc, account.id, "SHOPRITE", date(2026, m, 4), -1_000)
            for m in range(1, 5)
        ]
        await svc.assign_merchant([t.id for t in txns], drop.id, owner_user_id=1)
        await declare_recurring(async_db_session, [txns[0].id], owner_user_id=1)

        await svc.merge_merchants([drop.id], keep.id, owner_user_id=1)

        from sqlmodel import select

        from app.services.finance.models import FinanceRecurringStream

        streams = (
            await async_db_session.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).all()
        assert streams
        assert all(s.merchant_id == keep.id for s in streams)

    @pytest.mark.asyncio
    async def test_merging_a_payee_into_itself_is_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        """Otherwise it would soft-delete the survivor and strand every
        transaction it just moved onto a deleted row."""
        svc = FinanceService(async_db_session)
        keep = await svc.create_merchant("Shop Rite", owner_user_id=1)

        moved = await svc.merge_merchants([keep.id], keep.id, owner_user_id=1)

        assert moved == 0
        assert keep.id in {m.id for m in await svc.list_merchants(owner_user_id=1)}

    @pytest.mark.asyncio
    async def test_an_unknown_survivor_is_a_no_op(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        drop = await svc.create_merchant("ShopRite", owner_user_id=1)

        assert await svc.merge_merchants([drop.id], 9_999, owner_user_id=1) == 0
        assert drop.id in {m.id for m in await svc.list_merchants(owner_user_id=1)}


class TestRenameKeepsTheDedupKey:
    """``normalized_name`` is what duplicate detection matches on, so a
    rename that leaves it stale re-opens the very duplicate this page
    exists to close."""

    @pytest.mark.asyncio
    async def test_a_punctuation_only_fix_is_already_stable(
        self, async_db_session: AsyncSession
    ) -> None:
        """ "Mcdonald S" and "McDonald\'s" normalize to the SAME key, since
        normalize_payee strips the apostrophe either way - so the common
        fix cannot desync anything."""
        svc = FinanceService(async_db_session)
        merchant = await svc.create_merchant("Mcdonald S", owner_user_id=1)

        await svc.update_merchant(merchant.id, name="McDonald's", owner_user_id=1)
        again = await svc.create_merchant("McDonald's", owner_user_id=1)

        assert again.id == merchant.id
        assert len(await svc.list_merchants(owner_user_id=1)) == 1

    @pytest.mark.asyncio
    async def test_a_rename_that_changes_the_key_updates_it(
        self, async_db_session: AsyncSession
    ) -> None:
        """The case that can desync: renaming to something that normalizes
        differently. Leave the key stale and the picker\'s "+ Create" no
        longer finds this payee under its own name, minting a duplicate
        beside it - the exact thing the merge tool exists to clean up."""
        svc = FinanceService(async_db_session)
        merchant = await svc.create_merchant("Joes", owner_user_id=1)

        await svc.update_merchant(merchant.id, name="Joe's Coffee", owner_user_id=1)
        again = await svc.create_merchant("Joe's Coffee", owner_user_id=1)

        assert again.id == merchant.id
        assert len(await svc.list_merchants(owner_user_id=1)) == 1
