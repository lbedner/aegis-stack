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

from app.services.finance.models import FinanceCategory
from app.services.finance.service import FinanceService


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
        owner_user_id=1,
        name="Food & Dining:Groceries",
        slug="groceries",
        classification="expense",
    )
    db.add(groceries)
    await db.flush()
    payee = await svc.create_merchant("Stop & Shop", owner_user_id=1)

    plain = await svc.create_transaction(
        account_id=checking.id,
        amount=-4_235,
        txn_date=date(2026, 7, 13),
        owner_user_id=1,
        name="SHOPRITE 123",
    )
    tagged = await svc.create_transaction(
        account_id=amex.id,
        amount=-1_000,
        txn_date=date(2026, 7, 14),
        owner_user_id=1,
        name="SQ *UNRELATED",
    )
    await svc.assign_merchant([tagged.id], payee.id, owner_user_id=1)
    await svc.categorize_transaction(tagged.id, groceries.id, owner_user_id=1)
    return {"plain": plain, "tagged": tagged}


class TestTransactionSearch:
    @pytest.mark.asyncio
    async def test_the_descriptor_still_matches(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="shoprite")
        assert {r.id for r in found} == {rows["plain"].id}

    @pytest.mark.asyncio
    async def test_the_payee_column_matches(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The register shows the assigned payee, not the descriptor - so
        searching what is on screen has to find it."""
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="stop &")
        assert {r.id for r in found} == {rows["tagged"].id}

    @pytest.mark.asyncio
    async def test_the_category_column_matches(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="groceries")
        assert {r.id for r in found} == {rows["tagged"].id}

    @pytest.mark.asyncio
    async def test_the_account_column_matches(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """All Accounts shows an Account column; searching "amex" there
        should narrow to it."""
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="amex")
        assert {r.id for r in found} == {rows["tagged"].id}

    @pytest.mark.asyncio
    async def test_it_is_case_insensitive(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        rows = await _fixture(svc, async_db_session)
        found, _ = await svc.list_transactions(owner_user_id=1, query="ShOpRiTe")
        assert {r.id for r in found} == {rows["plain"].id}

    @pytest.mark.asyncio
    async def test_no_match_is_empty_not_everything(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A broken OR that collapses to TRUE returns the whole ledger,
        which reads as "search is ignored" rather than as a bug."""
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
        self, svc: FinanceService
    ) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        amex = await svc.create_manual_account(
            name="Amex",
            account_type="credit_card",
            classification="liability",
            owner_user_id=1,
        )
        ira = await svc.create_manual_account(
            name="IRA",
            account_type="brokerage",
            classification="asset",
            owner_user_id=1,
        )
        for account, name in ((checking, "Coffee"), (amex, "Adj"), (ira, "Fund")):
            await svc.create_transaction(
                account_id=account.id,
                amount=-1_000,
                txn_date=date(2026, 7, 17),
                owner_user_id=1,
                name=name,
            )

        items, total = await svc.list_transactions(
            owner_user_id=1, account_ids=[checking.id, amex.id]
        )

        assert total == 2
        assert {t.name for t in items} == {"Coffee", "Adj"}

    @pytest.mark.asyncio
    async def test_no_scope_still_means_everything(self, svc: FinanceService) -> None:
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        await svc.create_transaction(
            account_id=checking.id,
            amount=-1_000,
            txn_date=date(2026, 7, 17),
            owner_user_id=1,
            name="Coffee",
        )

        _items, total = await svc.list_transactions(owner_user_id=1, account_ids=None)

        assert total == 1

    @pytest.mark.asyncio
    async def test_trades_narrow_the_same_way(self, svc: FinanceService) -> None:
        ira = await svc.create_manual_account(
            name="IRA",
            account_type="brokerage",
            classification="asset",
            owner_user_id=1,
        )
        roth = await svc.create_manual_account(
            name="Roth",
            account_type="brokerage",
            classification="asset",
            owner_user_id=1,
        )
        for account in (ira, roth):
            await svc.upsert_trade(
                account_id=account.id,
                owner_user_id=1,
                trade_type="buy",
                trade_date=date(2026, 7, 10),
                amount=-8_687,
                name="PERIODIC INVESTMENT",
            )

        trades = await svc.list_trades(owner_user_id=1, account_ids=[ira.id])

        assert len(trades) == 1
        assert trades[0].account_id == ira.id


class TestAmountSearch:
    """Typing a number should find the money, not just descriptors that
    happen to contain the digits. Exact-amount match only: substring
    would find "50" inside $1,502.00, which is why amount was left out
    of search entirely until now."""

    @staticmethod
    async def _spend(svc: FinanceService, account_id: int, cents: int, name: str):
        return await svc.create_transaction(
            account_id=account_id,
            amount=cents,
            txn_date=date(2026, 7, 20),
            owner_user_id=1,
            name=name,
        )

    @pytest.mark.asyncio
    async def test_a_whole_dollar_query_matches_the_amount(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        rows = await _fixture(svc, async_db_session)
        target = await self._spend(svc, rows["plain"].account_id, -50_000, "WIRE OUT")

        found, _ = await svc.list_transactions(owner_user_id=1, query="500")

        assert {r.id for r in found} == {target.id}

    @pytest.mark.asyncio
    async def test_cents_and_currency_formatting_both_parse(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        rows = await _fixture(svc, async_db_session)
        target = await self._spend(
            svc, rows["plain"].account_id, -150_200, "BIG CHARGE"
        )

        for query in ("1502", "1502.00", "$1,502.00"):
            found, _ = await svc.list_transactions(owner_user_id=1, query=query)
            assert {r.id for r in found} == {target.id}, query

    @pytest.mark.asyncio
    async def test_an_amount_query_never_substring_matches(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """ "50" must not find $1,502.00 or $50.12 - only $50.00 (and any
        text column that really contains "50")."""
        rows = await _fixture(svc, async_db_session)
        await self._spend(svc, rows["plain"].account_id, -150_200, "BIG CHARGE")
        await self._spend(svc, rows["plain"].account_id, -5_012, "NEAR MISS")
        exact = await self._spend(svc, rows["plain"].account_id, -5_000, "ON THE NOSE")

        found, _ = await svc.list_transactions(owner_user_id=1, query="50")

        assert {r.id for r in found} == {exact.id}

    @pytest.mark.asyncio
    async def test_the_sign_does_not_matter(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        rows = await _fixture(svc, async_db_session)
        refund = await self._spend(svc, rows["plain"].account_id, 50_000, "WIRE BACK")

        found, _ = await svc.list_transactions(owner_user_id=1, query="500")

        assert {r.id for r in found} == {refund.id}

    @pytest.mark.asyncio
    async def test_a_money_query_still_searches_text_too(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A number is not ONLY money: "500" is also the payee "CLUB 500"."""
        rows = await _fixture(svc, async_db_session)
        club = await self._spend(svc, rows["plain"].account_id, -999, "CLUB 500")
        wire = await self._spend(svc, rows["plain"].account_id, -50_000, "WIRE OUT")

        found, _ = await svc.list_transactions(owner_user_id=1, query="500")

        assert {r.id for r in found} == {club.id, wire.id}
