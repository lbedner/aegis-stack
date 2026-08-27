"""Setting a bill's account, especially when it has none.

A hand-entered bill or income can be created without one - and then it
cannot reach the forecast at all, because the projection walks forward
from cash accounts and a bill belonging to none has nowhere to land.
Confirmed live: "Betr Health", $5,000 twice a month, invisible to
Projected.

The catch is that a stream's identity is
``(owner, account_id, direction, normalized_payee)`` - the unique key
detection re-finds it by. Moving accounts can collide with a bill already
there, and that has to be a clean refusal rather than an index error.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_stream


async def _accounts(svc: FinanceService):
    first = await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )
    second = await svc.create_manual_account(
        name="Savings",
        account_type="savings",
        classification="asset",
        owner_user_id=1,
    )
    return first, second


async def _bill(svc: FinanceService, name: str, account_id: int | None):
    return await seed_stream(
        svc,
        name=name,
        direction="inflow",
        frequency="semi_monthly",
        expected_amount=500_000,
        next_expected_date=date(2026, 8, 15),
        account_id=account_id,
    )


class TestSetBillAccount:
    @pytest.mark.asyncio
    async def test_an_account_less_bill_can_be_given_one(
        self, svc: FinanceService
    ) -> None:
        checking, _ = await _accounts(svc)
        bill = await _bill(svc, "Betr Health", None)
        assert bill.account_id is None

        updated = await svc.update_recurring(
            bill.id, owner_user_id=1, account_id=checking.id
        )

        assert updated is not None
        assert updated.account_id == checking.id

    @pytest.mark.asyncio
    async def test_it_can_be_moved_between_accounts(self, svc: FinanceService) -> None:
        checking, savings = await _accounts(svc)
        bill = await _bill(svc, "Betr Health", checking.id)

        updated = await svc.update_recurring(
            bill.id, owner_user_id=1, account_id=savings.id
        )

        assert updated is not None
        assert updated.account_id == savings.id

    @pytest.mark.asyncio
    async def test_moving_onto_an_occupied_key_is_refused_cleanly(
        self, svc: FinanceService
    ) -> None:
        """Same owner, account, direction and payee is the unique key. A
        collision must raise something the API can turn into a 409, not a
        database error surfacing as a 500."""
        checking, savings = await _accounts(svc)
        here = await _bill(svc, "Betr Health", checking.id)
        await _bill(svc, "Betr Health", savings.id)

        with pytest.raises(ValueError):
            await svc.update_recurring(here.id, owner_user_id=1, account_id=savings.id)

    @pytest.mark.asyncio
    async def test_leaving_the_account_out_does_not_clear_it(
        self, svc: FinanceService
    ) -> None:
        """Every other field on this endpoint is "omitted means unchanged"
        - the account must not be the one that silently blanks."""
        checking, _ = await _accounts(svc)
        bill = await _bill(svc, "Betr Health", checking.id)

        updated = await svc.update_recurring(bill.id, owner_user_id=1, name="Renamed")

        assert updated is not None
        assert updated.account_id == checking.id


class TestRetiredGhostsDoNotBlockAMove:
    """A soft-deleted stream still occupies the unique key.

    ``uq_finance_recurring_detected`` is
    ``(owner, account, direction, normalized_payee)`` with only a
    ``provider_stream_id IS NULL`` predicate - nothing about
    ``deleted_at``. So a retired row keeps its slot, and a guard that
    filters on ``deleted_at IS NULL`` looks straight past it and lets the
    UPDATE hit the index as a 500.

    Refusing is also wrong: the blocking row is invisible. The user sees
    one bill and is told it already exists somewhere they cannot look.
    """

    @pytest.mark.asyncio
    async def test_a_retired_row_gives_up_its_key(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from datetime import UTC, datetime

        checking, savings = await _accounts(svc)
        ghost = await _bill(svc, "Eleanor", savings.id)
        ghost.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        async_db_session.add(ghost)
        await async_db_session.flush()
        live = await _bill(svc, "Eleanor", checking.id)

        updated = await svc.update_recurring(
            live.id, owner_user_id=1, account_id=savings.id
        )

        assert updated is not None
        assert updated.account_id == savings.id
        # The ghost survives as history; it just no longer holds the key.
        await async_db_session.refresh(ghost)
        assert ghost.deleted_at is not None
        assert ghost.normalized_payee != updated.normalized_payee

    @pytest.mark.asyncio
    async def test_a_live_row_still_refuses(self, svc: FinanceService) -> None:
        checking, savings = await _accounts(svc)
        await _bill(svc, "Eleanor", savings.id)
        live = await _bill(svc, "Eleanor", checking.id)

        with pytest.raises(ValueError):
            await svc.update_recurring(live.id, owner_user_id=1, account_id=savings.id)
