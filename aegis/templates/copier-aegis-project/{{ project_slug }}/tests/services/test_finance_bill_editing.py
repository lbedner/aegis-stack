"""Editing a bill's category and account.

The category shown on Bills & Income is DERIVED - ``stream_category_names``
reads the most common category across the stream's member transactions,
because ``finance_recurring_stream.category_id`` is a provider field the
local detector never fills. So storing a category is only half the job: if
the display keeps deriving, the edit silently does nothing.

Setting it must NOT touch the member transactions (chosen deliberately -
a bulk rewrite would overwrite per-transaction corrections made by hand).
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.categorize import declare_recurring
from app.services.finance.finance_service import FinanceService


async def _account(svc: FinanceService, name: str = "Checking"):
    return await svc.create_manual_account(
        name=name,
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )


async def _category(db: AsyncSession, name: str):
    from app.services.finance.models import FinanceCategory

    row = FinanceCategory(
        owner_user_id=1,
        name=name,
        slug=name.lower().replace(" ", "-").replace(":", "-").replace("&", "and"),
        classification="expense",
    )
    db.add(row)
    await db.flush()
    return row


async def _bill(svc: FinanceService, db: AsyncSession, account_id: int, name: str):
    txns = [
        await svc.create_transaction(
            account_id=account_id,
            amount=-1_000,
            txn_date=date(2026, m, 4),
            owner_user_id=1,
            name=name,
        )
        for m in range(1, 5)
    ]
    await declare_recurring(db, [t.id for t in txns], owner_user_id=1)
    from sqlmodel import select

    from app.services.finance.models import FinanceRecurringStream

    stream = (
        await db.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.deleted_at.is_(None),
                FinanceRecurringStream.name == name,
            )
        )
    ).first()
    return stream, txns


class TestBillCategory:
    @pytest.mark.asyncio
    async def test_a_stored_category_is_what_gets_shown(
        self, async_db_session: AsyncSession
    ) -> None:
        """Otherwise the edit saves and the table keeps showing the
        category derived from the transactions - a silent no-op."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        stream, txns = await _bill(svc, async_db_session, account.id, "ACME MART")
        for txn in txns:
            await svc.categorize_transaction(
                txn.id, groceries.id, owner_user_id=1, source="user"
            )
        household = await _category(async_db_session, "Home:Household")

        await svc.update_recurring(
            stream.id, owner_user_id=1, category_id=household.id
        )

        names = await svc.stream_category_names([stream.id])
        assert names[stream.id] == "Home:Household"

    @pytest.mark.asyncio
    async def test_the_derived_category_still_shows_when_none_is_stored(
        self, async_db_session: AsyncSession
    ) -> None:
        """The existing behaviour has to survive - most bills have no
        stored category and the derived one is all there is."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        stream, txns = await _bill(svc, async_db_session, account.id, "ACME MART")
        for txn in txns:
            await svc.categorize_transaction(
                txn.id, groceries.id, owner_user_id=1, source="user"
            )

        names = await svc.stream_category_names([stream.id])
        assert names[stream.id] == "Food & Dining:Groceries"

    @pytest.mark.asyncio
    async def test_the_member_transactions_are_left_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        stream, txns = await _bill(svc, async_db_session, account.id, "ACME MART")
        for txn in txns:
            await svc.categorize_transaction(
                txn.id, groceries.id, owner_user_id=1, source="user"
            )
        household = await _category(async_db_session, "Home:Household")

        await svc.update_recurring(
            stream.id, owner_user_id=1, category_id=household.id
        )

        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.category_id == groceries.id


class TestCategoryAtDeclareTime:
    @pytest.mark.asyncio
    async def test_make_recurring_can_set_the_category(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        household = await _category(async_db_session, "Home:Household")
        txns = [
            await svc.create_transaction(
                account_id=account.id,
                amount=-1_000,
                txn_date=date(2026, m, 4),
                owner_user_id=1,
                name="ACME MART",
            )
            for m in range(1, 5)
        ]
        ids = [t.id for t in txns]
        plan = await plan_recurring(async_db_session, ids, owner_user_id=1)

        await declare_recurring(
            async_db_session,
            ids,
            owner_user_id=1,
            categories={plan[0].key: household.id},
        )

        from sqlmodel import select

        from app.services.finance.models import FinanceRecurringStream

        stream = (
            await async_db_session.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).first()
        assert stream is not None
        assert stream.category_id == household.id
        names = await svc.stream_category_names([stream.id])
        assert names[stream.id] == "Home:Household"

    @pytest.mark.asyncio
    async def test_declaring_with_a_category_leaves_transactions_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        household = await _category(async_db_session, "Home:Household")
        txns = [
            await svc.create_transaction(
                account_id=account.id,
                amount=-1_000,
                txn_date=date(2026, m, 4),
                owner_user_id=1,
                name="ACME MART",
            )
            for m in range(1, 5)
        ]
        ids = [t.id for t in txns]
        plan = await plan_recurring(async_db_session, ids, owner_user_id=1)

        await declare_recurring(
            async_db_session,
            ids,
            owner_user_id=1,
            categories={plan[0].key: household.id},
        )

        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.category_id is None
