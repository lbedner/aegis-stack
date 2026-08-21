"""Search spans every column you can see, not just the payee.

There were two implementations of "matches the query" - a SQL ``ilike``
on ``FinanceTransaction.name`` (written twice, at both list call sites)
and an ``in`` against a dict's name in the frontend tabs. Both looked at
one column while the tables showed five or six, so searching for a
category or an account name returned nothing and read as "no such data".
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from app.services.finance.models import FinanceCategory


async def _fixture(svc: FinanceService, db: AsyncSession):
    checking = await svc.create_manual_account(
        name="Total Checking (Chase)",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )
    amex = await svc.create_manual_account(
        name="AMEX Platinum",
        account_type="credit_card",
        classification="liability",
        owner_user_id=1,
    )
    groceries = FinanceCategory(
        owner_user_id=1, name="Food & Dining:Groceries",
        slug="groceries", classification="expense",
    )
    db.add(groceries)
    await db.flush()
    payee = await svc.create_merchant("Stop & Shop", owner_user_id=1)

    plain = await svc.create_transaction(
        account_id=checking.id, amount=-4_235, txn_date=date(2026, 7, 13),
        owner_user_id=1, name="SHOPRITE 123",
    )
    tagged = await svc.create_transaction(
        account_id=amex.id, amount=-1_000, txn_date=date(2026, 7, 14),
        owner_user_id=1, name="SQ *UNRELATED",
    )
    await svc.assign_merchant([tagged.id], payee.id, owner_user_id=1)
    await svc.categorize_transaction(tagged.id, groceries.id, owner_user_id=1)
    return {"plain": plain, "tagged": tagged}


class TestTransactionSearch:
    @pytest.mark.asyncio
    async def test_the_descriptor_still_matches(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="shoprite")
        assert {r.id for r in found} == {rows["plain"].id}

    @pytest.mark.asyncio
    async def test_the_payee_column_matches(
        self, async_db_session: AsyncSession
    ) -> None:
        """The register shows the assigned payee, not the descriptor - so
        searching what is on screen has to find it."""
        svc = FinanceService(async_db_session)
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="stop &")
        assert {r.id for r in found} == {rows["tagged"].id}

    @pytest.mark.asyncio
    async def test_the_category_column_matches(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="groceries")
        assert {r.id for r in found} == {rows["tagged"].id}

    @pytest.mark.asyncio
    async def test_the_account_column_matches(
        self, async_db_session: AsyncSession
    ) -> None:
        """All Accounts shows an Account column; searching "amex" there
        should narrow to it."""
        svc = FinanceService(async_db_session)
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="amex")
        assert {r.id for r in found} == {rows["tagged"].id}

    @pytest.mark.asyncio
    async def test_it_is_case_insensitive(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="ShOpRiTe")
        assert {r.id for r in found} == {rows["plain"].id}

    @pytest.mark.asyncio
    async def test_no_match_is_empty_not_everything(
        self, async_db_session: AsyncSession
    ) -> None:
        """A broken OR that collapses to TRUE returns the whole ledger,
        which reads as "search is ignored" rather than as a bug."""
        svc = FinanceService(async_db_session)
        await _fixture(svc, async_db_session)
        found, total = await svc.list_transactions(owner_user_id=1, query="zzzz")
        assert found == [] and total == 0


class TestRegisterAccountScope:
    """The All Accounts register honors the account picker.

    It never did: the fetch passed no account scope at all, so "2 of 15
    accounts" changed nothing - the register showed the newest rows of
    EVERY account, and unchecked IRA trades rode in through a trades
    fetch that could not be scoped either (confirmed live: AMEX checked,
    its rows absent past the page edge; IRA trades present unchecked).
    """

    @pytest.mark.asyncio
    async def test_transactions_narrow_to_the_selected_accounts(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await svc.create_manual_account(
            name="Checking", account_type="checking",
            classification="asset", owner_user_id=1,
        )
        amex = await svc.create_manual_account(
            name="Amex", account_type="credit_card",
            classification="liability", owner_user_id=1,
        )
        ira = await svc.create_manual_account(
            name="IRA", account_type="brokerage",
            classification="asset", owner_user_id=1,
        )
        for account, name in ((checking, "Coffee"), (amex, "Adj"), (ira, "Fund")):
            await svc.create_transaction(
                account_id=account.id, amount=-1_000,
                txn_date=date(2026, 7, 17), owner_user_id=1, name=name,
            )

        items, total = await svc.list_transactions(
            owner_user_id=1, account_ids=[checking.id, amex.id]
        )

        assert total == 2
        assert {t.name for t in items} == {"Coffee", "Adj"}

    @pytest.mark.asyncio
    async def test_no_scope_still_means_everything(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        checking = await svc.create_manual_account(
            name="Checking", account_type="checking",
            classification="asset", owner_user_id=1,
        )
        await svc.create_transaction(
            account_id=checking.id, amount=-1_000,
            txn_date=date(2026, 7, 17), owner_user_id=1, name="Coffee",
        )

        _items, total = await svc.list_transactions(owner_user_id=1, account_ids=None)

        assert total == 1

    @pytest.mark.asyncio
    async def test_trades_narrow_the_same_way(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        ira = await svc.create_manual_account(
            name="IRA", account_type="brokerage",
            classification="asset", owner_user_id=1,
        )
        roth = await svc.create_manual_account(
            name="Roth", account_type="brokerage",
            classification="asset", owner_user_id=1,
        )
        for account in (ira, roth):
            await svc.upsert_trade(
                account_id=account.id, owner_user_id=1,
                trade_type="buy", trade_date=date(2026, 7, 10),
                amount=-8_687, name="PERIODIC INVESTMENT",
            )

        trades = await svc.list_trades(owner_user_id=1, account_ids=[ira.id])

        assert len(trades) == 1
        assert trades[0].account_id == ira.id
