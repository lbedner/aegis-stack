"""Tests for the payee-less backlog: how it collapses into groups, and how
a whole brand gets named in one pass.

The motivating case is real. A single DoorDash order writes a descriptor
carrying the restaurant, the city, a transaction id and a phone number, so
one payee arrives as dozens of distinct shapes - 314 transactions across 48
groups in the dataset this was built against. Naming them one at a time is
48 decisions for one fact, so the caller checks the ones a search turned up
and sends the whole set together.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.finance_service import FinanceService

# Verbatim descriptor shapes from a real card export - the point of the test
# is that these five disagree in every way EXCEPT containing "DOORDASH", so
# no prefix or token rule groups them.
_DOORDASH = [
    "DOORDASH*CROWN FRIEDSAN FRANCIS NT_KBVL6WXU +16506819470",
    "DOORDASH*COUNTRY CORSAN FRANCIS NT_KUI9MCQP +16506819470",
    "BT*DD *DOORDASH MCDOSAN FRANCISCO CA XXXX--X3007",
    "VENMO *DOORDASH XXX-XXX-4430 NY 10/07",
    "Doordash",
]


async def _account(svc: FinanceService):
    return await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )


async def _txn(svc: FinanceService, account_id: int, name: str, day: int):
    return await svc.create_transaction(
        account_id=account_id,
        amount=-1_500,
        txn_date=date(2026, 7, day),
        owner_user_id=1,
        name=name,
    )


class TestPayeeGroups:
    @pytest.mark.asyncio
    async def test_one_brand_shatters_into_many_groups(
        self, async_db_session: AsyncSession
    ) -> None:
        """The premise. If these ever collapse on their own the bulk tool
        below is unnecessary - so assert the split explicitly rather than
        assuming it."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for i, descriptor in enumerate(_DOORDASH):
            await _txn(svc, account.id, descriptor, i + 1)

        page, total_groups, total_txns = await svc.payee_groups(owner_user_id=1)

        assert total_txns == 5
        assert total_groups == len(page) == 5  # five descriptors, five groups

    @pytest.mark.asyncio
    async def test_totals_describe_the_backlog_not_the_page(
        self, async_db_session: AsyncSession
    ) -> None:
        """``total`` used to be ``len(items)``, so a limit of 300 reported
        "300 groups" when there were 2,436 - a truncation that read as a
        complete count."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for i, descriptor in enumerate(_DOORDASH):
            await _txn(svc, account.id, descriptor, i + 1)

        page, total_groups, total_txns = await svc.payee_groups(
            owner_user_id=1, limit=2
        )

        assert len(page) == 2  # the page IS capped...
        assert total_groups == 5  # ...and says so honestly
        assert total_txns == 5

    @pytest.mark.asyncio
    async def test_one_sweep_names_every_selected_group(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for i, descriptor in enumerate(_DOORDASH):
            await _txn(svc, account.id, descriptor, i + 1)
        merchant = await svc.create_merchant("DoorDash", owner_user_id=1)

        page, _, _ = await svc.payee_groups(owner_user_id=1)
        updated = await svc.assign_payee_group(
            [g["key"] for g in page], merchant.id, owner_user_id=1
        )

        assert updated == 5
        _, remaining_groups, remaining_txns = await svc.payee_groups(owner_user_id=1)
        assert (remaining_groups, remaining_txns) == (0, 0)

    @pytest.mark.asyncio
    async def test_unselected_groups_are_left_alone(
        self, async_db_session: AsyncSession
    ) -> None:
        """A sweep must touch ONLY the checked keys - the whole reason the
        UI shows what it is about to assign."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for i, descriptor in enumerate(_DOORDASH):
            await _txn(svc, account.id, descriptor, i + 1)
        await _txn(svc, account.id, "STARBUCKS STORE 1234 POUGHKEEPSIE NY", 20)
        merchant = await svc.create_merchant("DoorDash", owner_user_id=1)

        page, _, _ = await svc.payee_groups(owner_user_id=1)
        doordash_keys = [g["key"] for g in page if "DOORDASH" in g["key"].upper()]
        updated = await svc.assign_payee_group(
            doordash_keys, merchant.id, owner_user_id=1
        )

        assert updated == 5
        _, remaining_groups, remaining_txns = await svc.payee_groups(owner_user_id=1)
        assert (remaining_groups, remaining_txns) == (1, 1)  # Starbucks survives

    @pytest.mark.asyncio
    async def test_empty_key_list_is_a_no_op(
        self, async_db_session: AsyncSession
    ) -> None:
        """Guards the bulk path: an empty selection must not fall through
        to "matches everything"."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for i, descriptor in enumerate(_DOORDASH):
            await _txn(svc, account.id, descriptor, i + 1)
        merchant = await svc.create_merchant("DoorDash", owner_user_id=1)

        assert await svc.assign_payee_group([], merchant.id, owner_user_id=1) == 0
        assert await svc.assign_payee_group([""], merchant.id, owner_user_id=1) == 0
        _, _, remaining = await svc.payee_groups(owner_user_id=1)
        assert remaining == 5


class TestGroupDialogSizing:
    """The confirm dialog's table must never grow tall enough to push the
    action row out of the panel.

    ``StyledAlertDialog``'s panel sets ``clip_behavior=HARD_EDGE`` and the
    actions are the LAST child of its column, so an over-tall body does not
    shrink or scroll - it silently clips Cancel and the confirm button off
    the bottom, stranding the user in a dialog with no way to finish.
    Reported live: "I don't even see an accept button or save or anything."
    """

    def test_actions_stay_on_screen_at_every_size(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            _GROUP_DIALOG_CHROME,
            _group_table_height,
        )

        for window in (400, 600, 700, 800, 973, 1200, 1600):
            for group_count in (1, 3, 12, 20, 40, 300):
                table = _group_table_height(group_count, window)
                panel = table + _GROUP_DIALOG_CHROME
                assert panel <= window, (
                    f"{group_count} groups in a {window}px window needs "
                    f"{panel}px - the action row would be clipped"
                )

    def test_a_sweep_that_fits_is_shown_whole(self) -> None:
        """The other half: don't cap a table that had room. A 12-group
        brand sweep on a normal window shows all 12, no inner scrollbar."""
        from app.components.frontend.dashboard.modals.finance_modal import (
            _DENSE_ROW_HEIGHT,
            _group_table_height,
        )

        needed = 12 * _DENSE_ROW_HEIGHT + 56
        assert _group_table_height(12, 973) >= needed

    def test_a_short_window_still_gets_a_usable_table(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            _GROUP_TABLE_MIN_HEIGHT,
            _group_table_height,
        )

        # Roomy enough for the floor: the floor applies.
        assert _group_table_height(1, 800) == _GROUP_TABLE_MIN_HEIGHT
        # Too short even for that: the ceiling still wins, because a
        # cramped table beats a dialog whose buttons are clipped away.
        assert _group_table_height(40, 400) < _GROUP_TABLE_MIN_HEIGHT
