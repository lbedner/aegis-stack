"""Tests for manual + rule-based transaction categorization.

Covers ``categorize_transaction`` (manual pick, 404/wrong-owner miss) and
``suggest_categories`` (payee-precedent matching, no-history skip,
tied-precedent skip - and that it never writes, since it's a preview).
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account


class TestCategorizeTransaction:
    @pytest.mark.asyncio
    async def test_manual_categorize_sets_source_and_flags(
        self, svc: FinanceService
    ) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")
        txn = await svc.create_transaction(
            account_id=checking.id,
            amount=-1200,
            txn_date=date(2026, 7, 1),
            owner_user_id=1,
            name="Trader Joes",
        )

        result = await svc.categorize_transaction(
            txn.id, groceries.id, owner_user_id=1, source="user"
        )
        assert result is not None
        assert result.category_id == groceries.id
        assert result.category_source == "user"
        assert result.is_user_categorized is True
        assert result.is_reviewed is True

    @pytest.mark.asyncio
    async def test_missing_transaction_returns_none(self, svc: FinanceService) -> None:
        result = await svc.categorize_transaction(999999, 1, owner_user_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_owner_cannot_categorize(self, svc: FinanceService) -> None:
        checking = await _account(svc, "Checking", "checking", "asset", owner_user_id=1)
        category = await svc.get_or_create_category_from_hint("Food:Groceries")
        txn = await svc.create_transaction(
            account_id=checking.id,
            amount=-1200,
            txn_date=date(2026, 7, 1),
            owner_user_id=1,
            name="Trader Joes",
        )

        result = await svc.categorize_transaction(txn.id, category.id, owner_user_id=2)
        assert result is None


class TestSuggestCategories:
    """``suggest_categories`` is a preview: it must never write. Applying an
    accepted suggestion is the caller's job, through the ordinary
    ``categorize_transaction`` (see TestCategorizeTransaction above)."""

    @pytest.mark.asyncio
    async def test_suggests_dominant_prior_category_by_payee_without_writing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")

        # Two prior corrections agree on the payee's category...
        for i in range(2):
            past = await svc.create_transaction(
                account_id=checking.id,
                amount=-1000,
                txn_date=date(2026, 6, i + 1),
                owner_user_id=1,
                name="Trader Joes",
            )
            await svc.categorize_transaction(
                past.id, groceries.id, owner_user_id=1, source="user"
            )
        # ...then a fresh, still-uncategorized transaction from the same payee.
        fresh = await svc.create_transaction(
            account_id=checking.id,
            amount=-1500,
            txn_date=date(2026, 7, 1),
            owner_user_id=1,
            name="Trader Joes",
        )

        result = await svc.suggest_categories(owner_user_id=1)
        assert result.skipped == 0
        assert len(result.items) == 1
        suggestion = result.items[0]
        assert suggestion.transaction_id == fresh.id
        assert suggestion.category_id == groceries.id
        assert suggestion.category_name == groceries.name

        # A preview - the transaction itself must be untouched.
        await async_db_session.refresh(fresh)
        assert fresh.category_id is None
        assert fresh.category_source == "unset"

    @pytest.mark.asyncio
    async def test_no_history_is_skipped(self, svc: FinanceService) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        await svc.create_transaction(
            account_id=checking.id,
            amount=-1500,
            txn_date=date(2026, 7, 1),
            owner_user_id=1,
            name="Brand New Payee",
        )

        result = await svc.suggest_categories(owner_user_id=1)
        assert result.items == []
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_tied_precedent_is_skipped_not_guessed(
        self, svc: FinanceService
    ) -> None:
        checking = await _account(svc, "Checking", "checking", "asset")
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")
        other = await svc.get_or_create_category_from_hint("Shopping:General")

        one = await svc.create_transaction(
            account_id=checking.id,
            amount=-1000,
            txn_date=date(2026, 6, 1),
            owner_user_id=1,
            name="Amazon",
        )
        await svc.categorize_transaction(
            one.id, groceries.id, owner_user_id=1, source="user"
        )
        two = await svc.create_transaction(
            account_id=checking.id,
            amount=-1000,
            txn_date=date(2026, 6, 2),
            owner_user_id=1,
            name="Amazon",
        )
        await svc.categorize_transaction(
            two.id, other.id, owner_user_id=1, source="user"
        )
        await svc.create_transaction(
            account_id=checking.id,
            amount=-1500,
            txn_date=date(2026, 7, 1),
            owner_user_id=1,
            name="Amazon",
        )

        result = await svc.suggest_categories(owner_user_id=1)
        assert result.items == []
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_transaction_ids_scopes_the_sweep(self, svc: FinanceService) -> None:
        """A checkbox selection: candidates are narrowed to the given ids,
        but the precedent tally still draws on the owner's full history -
        a narrower selection isn't weaker evidence for the payees in it."""
        checking = await _account(svc, "Checking", "checking", "asset")
        groceries = await svc.get_or_create_category_from_hint("Food:Groceries")
        coffee = await svc.get_or_create_category_from_hint("Food:Coffee")

        for i in range(2):
            past = await svc.create_transaction(
                account_id=checking.id,
                amount=-1000,
                txn_date=date(2026, 6, i + 1),
                owner_user_id=1,
                name="Trader Joes",
            )
            await svc.categorize_transaction(
                past.id, groceries.id, owner_user_id=1, source="user"
            )
        for i in range(2):
            past = await svc.create_transaction(
                account_id=checking.id,
                amount=-500,
                txn_date=date(2026, 6, i + 1),
                owner_user_id=1,
                name="Starbucks",
            )
            await svc.categorize_transaction(
                past.id, coffee.id, owner_user_id=1, source="user"
            )
        joes_fresh = await svc.create_transaction(
            account_id=checking.id,
            amount=-1500,
            txn_date=date(2026, 7, 1),
            owner_user_id=1,
            name="Trader Joes",
        )
        starbucks_fresh = await svc.create_transaction(
            account_id=checking.id,
            amount=-600,
            txn_date=date(2026, 7, 2),
            owner_user_id=1,
            name="Starbucks",
        )

        result = await svc.suggest_categories(
            owner_user_id=1, transaction_ids=[joes_fresh.id]
        )
        assert [s.transaction_id for s in result.items] == [joes_fresh.id]
        assert result.skipped == 0

        result_both = await svc.suggest_categories(
            owner_user_id=1,
            transaction_ids=[joes_fresh.id, starbucks_fresh.id],
        )
        assert {s.transaction_id for s in result_both.items} == {
            joes_fresh.id,
            starbucks_fresh.id,
        }


class TestExcludedRowsStayOutOfTheQueue:
    """The Uncategorized queue is a work queue: rows waiting for a
    category that will change some figure. A row flagged out of reports
    can never change any figure, so putting it in the queue asks the user
    to do work that cannot matter - nine issuer-adjustment legs sat there
    nagging (confirmed live), and every future adjustment pair would
    rejoin the queue on arrival.
    """

    @pytest.mark.asyncio
    async def test_an_excluded_row_is_not_asked_about(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        card = await _account(svc, "Amex", "credit_card", "liability")
        excluded = await svc.create_transaction(
            account_id=card.id,
            amount=23_171,
            txn_date=date(2026, 7, 17),
            owner_user_id=1,
            name="Adj Redist Bal",
        )
        excluded.excluded_from_reports = True
        async_db_session.add(excluded)
        await svc.create_transaction(
            account_id=card.id,
            amount=-1_500,
            txn_date=date(2026, 7, 18),
            owner_user_id=1,
            name="Coffee Cart",
        )
        await async_db_session.flush()

        items, total = await svc.uncategorized_transactions(owner_user_id=1, limit=None)

        names = [t.name for t in items]
        assert "Coffee Cart" in names
        assert "Adj Redist Bal" not in names
        assert total == 1

    @pytest.mark.asyncio
    async def test_transfer_legs_are_not_asked_about_either(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Same reasoning: a paired card-payment leg is excluded from
        every figure, so categorizing it is busywork."""
        checking = await _account(svc, "Checking", "checking", "asset")
        leg = await svc.create_transaction(
            account_id=checking.id,
            amount=-190_000,
            txn_date=date(2026, 7, 17),
            owner_user_id=1,
            name="AMEX EPAYMENT",
        )
        leg.is_transfer = True
        leg.excluded_from_reports = True
        async_db_session.add(leg)
        await async_db_session.flush()

        _items, total = await svc.uncategorized_transactions(
            owner_user_id=1, limit=None
        )

        assert total == 0
