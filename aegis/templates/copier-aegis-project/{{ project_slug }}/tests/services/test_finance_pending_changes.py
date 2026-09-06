"""The propose/approve queue: AI writes land as pending changes.

FW-05. Confirmation is structural, not prompt discipline: the sandbox's
only write tool is ``propose``, execution happens exclusively through
``approve``, and the model cannot skip the confirmation because no
direct-write tool exists.
"""

from datetime import date

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinancePendingChange
from app.services.finance.service import FinanceService
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_category as _category
from tests.services._finance_factories import seed_stream as _stream
from tests.services._finance_factories import seed_txn as _txn


class TestPendingChangeRow:
    @pytest.mark.asyncio
    async def test_a_proposal_row_round_trips(
        self, async_db_session: AsyncSession
    ) -> None:
        row = FinancePendingChange(
            owner_user_id=1,
            change_type="transaction.categorize",
            payload={"transaction_id": 7, "category_id": 3},
            proposed_by_agent="finance-assistant",
            conversation_id="conv-123",
        )
        async_db_session.add(row)
        await async_db_session.flush()

        assert row.id is not None
        assert row.status == "pending"
        assert row.resolved_at is None
        assert row.payload == {"transaction_id": 7, "category_id": 3}

    @pytest.mark.asyncio
    async def test_an_unknown_status_is_refused_by_the_table(
        self, async_db_session: AsyncSession
    ) -> None:
        """The status vocabulary is the audit trail's spine; a typo'd
        status would silently fall out of every pending/resolved read."""
        from sqlalchemy.exc import IntegrityError

        row = FinancePendingChange(
            owner_user_id=1,
            change_type="transaction.categorize",
            payload={},
            status="maybe",
        )
        async_db_session.add(row)
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestProposeApproveReject:
    """The queue's whole contract: propose moves nothing, approve executes
    the real mutation transactionally, reject leaves the ledger alone,
    and every resolution keeps its audit row."""

    @staticmethod
    async def _fixture(svc: FinanceService, session: AsyncSession):
        account = await _account(svc)
        groceries = await _category(session, "Food & Dining:Groceries")
        txn = await _txn(svc, account.id, -897, date(2026, 6, 10), name="Shelly's Deli")
        return groceries, txn

    @pytest.mark.asyncio
    async def test_propose_creates_a_pending_row_and_moves_nothing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        groceries, txn = await self._fixture(svc, async_db_session)

        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
            proposed_by_agent="finance-assistant",
            conversation_id="conv-1",
        )

        assert row.status == "pending"
        await async_db_session.refresh(txn)
        assert txn.category_id is None  # nothing in the ledger moved

    @pytest.mark.asyncio
    async def test_approve_executes_the_real_mutation(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        groceries, txn = await self._fixture(svc, async_db_session)
        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )

        resolved = await svc.approve_change(row.id, owner_user_id=1)

        await async_db_session.refresh(txn)
        assert txn.category_id == groceries.id
        assert resolved.status == "approved"
        assert resolved.resolved_at is not None

    @pytest.mark.asyncio
    async def test_reject_leaves_the_ledger_and_keeps_the_row(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        groceries, txn = await self._fixture(svc, async_db_session)
        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )

        resolved = await svc.reject_change(row.id, owner_user_id=1)

        await async_db_session.refresh(txn)
        assert txn.category_id is None
        assert resolved.status == "rejected"
        assert resolved.resolved_at is not None

    @pytest.mark.asyncio
    async def test_an_unknown_change_type_is_refused_at_propose(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        with pytest.raises(ValueError):
            await svc.propose_change("ledger.set_on_fire", {}, owner_user_id=1)

    @pytest.mark.asyncio
    async def test_a_malformed_payload_is_refused_at_propose(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Fail at propose, not at approve: a card the user cannot safely
        approve should never exist."""
        with pytest.raises(ValueError):
            await svc.propose_change(
                "transaction.categorize", {"transaction_id": 1}, owner_user_id=1
            )
        with pytest.raises(ValueError):
            await svc.propose_change(
                "transaction.categorize",
                {"transaction_id": 1, "category_id": 2, "amount": -999999},
                owner_user_id=1,
            )

    @pytest.mark.asyncio
    async def test_a_resolved_row_cannot_be_resolved_again(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        groceries, txn = await self._fixture(svc, async_db_session)
        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )
        await svc.reject_change(row.id, owner_user_id=1)

        with pytest.raises(ValueError):
            await svc.approve_change(row.id, owner_user_id=1)

    @pytest.mark.asyncio
    async def test_a_failing_execution_stays_pending_with_the_error_recorded(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Approval of a proposal whose target vanished must not half-land:
        the row stays pending, the error is in the audit, the user can
        reject it with full information."""
        groceries, txn = await self._fixture(svc, async_db_session)
        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": 999_999, "category_id": groceries.id},
            owner_user_id=1,
        )

        with pytest.raises(Exception):
            await svc.approve_change(row.id, owner_user_id=1)

        await async_db_session.refresh(row)
        assert row.status == "pending"
        assert row.result.get("error")

    @pytest.mark.asyncio
    async def test_pending_changes_list_newest_first(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        groceries, txn = await self._fixture(svc, async_db_session)
        first = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )
        second = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )
        await svc.reject_change(first.id, owner_user_id=1)

        pending = await svc.list_pending_changes(owner_user_id=1)

        assert [row.id for row in pending] == [second.id]


class TestCategorizeCardCopy:
    @pytest.mark.asyncio
    async def test_the_card_shows_before_and_after(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A recategorization is a MOVE: the card must say what it is
        moving FROM, or approving is a leap of faith."""
        account = await _account(svc)
        shopping = await _category(async_db_session, "Shopping")
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        txn = await _txn(svc, account.id, -1_296, date(2026, 8, 21), name="Target")
        await svc.categorize_transaction(txn.id, shopping.id, owner_user_id=1)

        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}

        assert display["Category"] == "Shopping \u2192 Food & Dining:Groceries"

    @pytest.mark.asyncio
    async def test_an_uncategorized_transaction_says_so(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        txn = await _txn(svc, account.id, -897, date(2026, 6, 10), name="Deli")

        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}

        assert display["Category"] == "Uncategorized \u2192 Food & Dining:Groceries"


class TestResolutionFreezesTheRecord:
    @pytest.mark.asyncio
    async def test_an_approved_card_keeps_its_before_state(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Read-time resolution is honest while pending; after approval
        the mutation has happened, and re-resolving showed
        "Groceries -> Groceries". Resolution snapshots the display into
        the audit row, and the card reads history from there."""
        account = await _account(svc)
        shopping = await _category(async_db_session, "Shopping")
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        txn = await _txn(svc, account.id, -1_296, date(2026, 8, 21), name="Target")
        await svc.categorize_transaction(txn.id, shopping.id, owner_user_id=1)
        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )

        resolved = await svc.approve_change(row.id, owner_user_id=1)
        display = {
            d.label: d.value for d in await svc.describe_pending_change(resolved)
        }

        assert display["Category"] == "Shopping \u2192 Food & Dining:Groceries"

    @pytest.mark.asyncio
    async def test_a_rejected_card_keeps_its_moment_too(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        shopping = await _category(async_db_session, "Shopping")
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        txn = await _txn(svc, account.id, -1_296, date(2026, 8, 21), name="Target")
        await svc.categorize_transaction(txn.id, shopping.id, owner_user_id=1)
        row = await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
        )

        resolved = await svc.reject_change(row.id, owner_user_id=1)
        # the world moves after rejection - the card must not follow it
        await svc.categorize_transaction(txn.id, groceries.id, owner_user_id=1)
        display = {
            d.label: d.value for d in await svc.describe_pending_change(resolved)
        }

        assert display["Category"] == "Shopping \u2192 Food & Dining:Groceries"


class TestBatches:
    """ "Approve them all" is one decision over many auditable rows: a
    batch is a grouping, not a different kind of change - every row
    still resolves individually and keeps its own audit trail."""

    @staticmethod
    async def _many(svc: FinanceService, session: AsyncSession, n: int = 3):
        account = await _account(svc)
        groceries = await _category(session, "Food & Dining:Groceries")
        txns = [
            await _txn(
                svc, account.id, -1_000 - i, date(2026, 8, 1 + i), name=f"Store {i}"
            )
            for i in range(n)
        ]
        rows = await svc.propose_many_changes(
            "transaction.categorize",
            [{"transaction_id": t.id, "category_id": groceries.id} for t in txns],
            owner_user_id=1,
            proposed_by_agent="finance-assistant",
        )
        return txns, groceries, rows

    @pytest.mark.asyncio
    async def test_a_batch_shares_one_id_and_moves_nothing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        txns, _groceries, rows = await self._many(svc, async_db_session)

        assert len(rows) == 3
        assert len({r.batch_id for r in rows}) == 1
        assert rows[0].batch_id is not None
        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.category_id is None

    @pytest.mark.asyncio
    async def test_approve_batch_executes_all_but_the_vetoed(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        txns, groceries, rows = await self._many(svc, async_db_session)
        vetoed = rows[1]

        summary = await svc.approve_batch(
            rows[0].batch_id, owner_user_id=1, exclude_ids=[vetoed.id]
        )

        assert summary["approved"] == 2
        assert summary["rejected"] == 1
        await async_db_session.refresh(txns[0])
        await async_db_session.refresh(txns[1])
        assert txns[0].category_id == groceries.id
        assert txns[1].category_id is None  # the veto held
        await async_db_session.refresh(vetoed)
        assert vetoed.status == "rejected"

    @pytest.mark.asyncio
    async def test_reject_batch_leaves_the_ledger_untouched(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        txns, _groceries, rows = await self._many(svc, async_db_session)

        summary = await svc.reject_batch(rows[0].batch_id, owner_user_id=1)

        assert summary["rejected"] == 3
        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.category_id is None

    @pytest.mark.asyncio
    async def test_a_bad_row_fails_alone_not_the_batch(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """One vanished target must not hold the other eleven hostage:
        the failed row stays pending with its error, the rest land."""
        txns, groceries, rows = await self._many(svc, async_db_session)
        doomed = rows[2]
        doomed_payload = dict(doomed.payload)
        doomed_payload["transaction_id"] = 999_999
        doomed.payload = doomed_payload
        async_db_session.add(doomed)
        await async_db_session.flush()

        summary = await svc.approve_batch(rows[0].batch_id, owner_user_id=1)

        assert summary["approved"] == 2
        assert summary["failed"] == 1
        await async_db_session.refresh(doomed)
        assert doomed.status == "pending"
        assert doomed.result.get("error")

    @pytest.mark.asyncio
    async def test_an_empty_or_oversized_batch_is_refused(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        with pytest.raises(ValueError):
            await svc.propose_many_changes(
                "transaction.categorize", [], owner_user_id=1
            )
        with pytest.raises(ValueError):
            await svc.propose_many_changes(
                "transaction.categorize",
                [{"transaction_id": i, "category_id": 1} for i in range(101)],
                owner_user_id=1,
            )


class TestMatchExecutor:
    """recurring.match: the manual which-payment-paid-this-bill attach,
    behind the queue. The executor rides the same domain verb the Bills
    tab's picker calls - approve here and a click there are one code
    path."""

    @staticmethod
    async def _fixture(svc: FinanceService, session: AsyncSession):
        account = await _account(svc)
        stream = await _stream(
            svc,
            name="Eleanor Nursing Care",
            expected_amount=100_000,
            next_expected_date=date(2026, 7, 31),
        )
        txn = await _txn(
            svc,
            account.id,
            -100_000,
            date(2026, 7, 31),
            name="Recurring Withdrawal CK *Eleanor Nursing Ca",
        )
        return stream, txn

    @pytest.mark.asyncio
    async def test_approve_attaches_the_payment_and_advances_the_bill(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        stream, txn = await self._fixture(svc, async_db_session)

        row = await svc.propose_change(
            "recurring.match",
            {"transaction_id": txn.id, "stream_id": stream.id},
            owner_user_id=1,
        )
        await async_db_session.refresh(txn)
        assert txn.recurring_stream_id is None  # proposing moved nothing

        resolved = await svc.approve_change(row.id, owner_user_id=1)

        assert resolved.status == "approved"
        await async_db_session.refresh(txn)
        await async_db_session.refresh(stream)
        assert txn.recurring_stream_id == stream.id
        assert stream.next_expected_date == date(2026, 8, 31)

    @pytest.mark.asyncio
    async def test_the_card_names_both_sides(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The card must say WHICH payment and WHICH bill, payee-first,
        with the bill as the arrow's target - approving a match the card
        only half-describes is a leap of faith."""
        stream, txn = await self._fixture(svc, async_db_session)

        row = await svc.propose_change(
            "recurring.match",
            {"transaction_id": txn.id, "stream_id": stream.id},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}

        assert "$1,000.00" in display["Payment"]
        assert "Jul 31, 2026" in display["Payment"]
        assert display["Bill"] == "Unmatched \u2192 Eleanor Nursing Care"

    @pytest.mark.asyncio
    async def test_a_malformed_match_payload_is_refused_at_propose(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        stream, txn = await self._fixture(svc, async_db_session)

        with pytest.raises(ValueError):
            await svc.propose_change(
                "recurring.match",
                {"transaction_id": txn.id, "stream_id": stream.id, "force": True},
                owner_user_id=1,
            )

    @pytest.mark.asyncio
    async def test_a_vanished_stream_fails_the_approval_not_the_queue(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        stream, txn = await self._fixture(svc, async_db_session)
        row = await svc.propose_change(
            "recurring.match",
            {"transaction_id": txn.id, "stream_id": stream.id},
            owner_user_id=1,
        )
        await svc.delete_recurring(stream.id, owner_user_id=1)

        with pytest.raises(Exception):
            await svc.approve_change(row.id, owner_user_id=1)

        await async_db_session.refresh(row)
        assert row.status == "pending"
        assert row.result.get("error")
        await async_db_session.refresh(txn)
        assert txn.recurring_stream_id is None


class TestAssignPayeeExecutor:
    """FW-06's second half: 'these withdrawals are Hudson Valley
    Grounded' as a proposal. Approval find-or-creates the payee by
    normalized name and points the rows at it - the same service verbs
    the register UI calls, no new mutation path."""

    @pytest.mark.asyncio
    async def test_approve_assigns_the_payee_creating_it_once(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        one = await _txn(svc, account.id, -2_500, date(2026, 8, 3), name="ATM 881")
        two = await _txn(svc, account.id, -2_500, date(2026, 8, 17), name="ATM 882")

        first = await svc.propose_change(
            "transaction.assign_payee",
            {"transaction_id": one.id, "payee": "Hudson Valley Grounded"},
            owner_user_id=1,
        )
        second = await svc.propose_change(
            "transaction.assign_payee",
            {"transaction_id": two.id, "payee": "hudson valley grounded"},
            owner_user_id=1,
        )
        await svc.approve_change(first.id, owner_user_id=1)
        await svc.approve_change(second.id, owner_user_id=1)

        await async_db_session.refresh(one)
        await async_db_session.refresh(two)
        assert one.merchant_id is not None
        # Same normalized name = same payee row, not a duplicate.
        assert two.merchant_id == one.merchant_id
        rows = await svc.list_merchants(owner_user_id=1)
        names = [m.name for m in rows]
        assert names.count("Hudson Valley Grounded") == 1

    @pytest.mark.asyncio
    async def test_propose_moves_nothing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txn = await _txn(svc, account.id, -2_500, date(2026, 8, 3), name="ATM 881")

        await svc.propose_change(
            "transaction.assign_payee",
            {"transaction_id": txn.id, "payee": "Hudson Valley Grounded"},
            owner_user_id=1,
        )

        await async_db_session.refresh(txn)
        assert txn.merchant_id is None
        assert await svc.list_merchants(owner_user_id=1) == []

    @pytest.mark.asyncio
    async def test_the_card_shows_the_move(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txn = await _txn(svc, account.id, -2_500, date(2026, 8, 3), name="ATM 881")

        row = await svc.propose_change(
            "transaction.assign_payee",
            {"transaction_id": txn.id, "payee": "Hudson Valley Grounded"},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}

        assert display["Payee"] == "Unassigned \u2192 Hudson Valley Grounded"
        assert "ATM 881" in display["Transaction"]

    @pytest.mark.asyncio
    async def test_the_card_shows_what_it_replaces(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txn = await _txn(svc, account.id, -2_500, date(2026, 8, 3), name="ATM 881")
        old = await svc.create_merchant("Chase ATM", owner_user_id=1)
        await svc.assign_merchant([txn.id], old.id, owner_user_id=1)

        row = await svc.propose_change(
            "transaction.assign_payee",
            {"transaction_id": txn.id, "payee": "Hudson Valley Grounded"},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}

        assert display["Payee"] == "Chase ATM \u2192 Hudson Valley Grounded"

    @pytest.mark.asyncio
    async def test_a_blank_payee_is_refused_at_propose(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txn = await _txn(svc, account.id, -2_500, date(2026, 8, 3), name="ATM 881")

        with pytest.raises(ValueError, match="payee"):
            await svc.propose_change(
                "transaction.assign_payee",
                {"transaction_id": txn.id, "payee": "   "},
                owner_user_id=1,
            )

    @pytest.mark.asyncio
    async def test_a_vanished_transaction_fails_the_approval_not_the_queue(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txn = await _txn(svc, account.id, -2_500, date(2026, 8, 3), name="ATM 881")
        row = await svc.propose_change(
            "transaction.assign_payee",
            {"transaction_id": txn.id, "payee": "Hudson Valley Grounded"},
            owner_user_id=1,
        )
        await svc.soft_delete_transactions([txn.id], owner_user_id=1)

        with pytest.raises(ValueError, match="not found"):
            await svc.approve_change(row.id, owner_user_id=1)

        refreshed = await async_db_session.get(FinancePendingChange, row.id)
        assert refreshed is not None and refreshed.status == "pending"


class TestTagExecutors:
    """transaction.tag / transaction.untag: the label axis, behind the
    queue. Rides the register's own verbs (get-or-create by normalized
    name, idempotent attach) - the bulk toolbar and an approval here are
    one code path."""

    @staticmethod
    async def _fixture(svc: FinanceService, session: AsyncSession):
        account = await _account(svc)
        txn = await _txn(svc, account.id, -900, date(2026, 8, 24), name="Link.com")
        return txn

    @pytest.mark.asyncio
    async def test_approve_tags_the_transaction(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.ledger.transactions import (
            transaction_tags,
        )

        txn = await self._fixture(svc, async_db_session)
        row = await svc.propose_change(
            "transaction.tag",
            {"transaction_id": txn.id, "tag": "Business"},
            owner_user_id=1,
        )
        assert (await transaction_tags(async_db_session, [txn.id])).get(
            txn.id, []
        ) == []

        await svc.approve_change(row.id, owner_user_id=1)

        tags = await transaction_tags(async_db_session, [txn.id])
        assert [t.name for t in tags[txn.id]] == ["Business"]

    @pytest.mark.asyncio
    async def test_tags_accumulate_they_do_not_replace(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The whole point of the axis: labels are a SET, never a slot."""
        from app.services.finance.domains.ledger.transactions import (
            transaction_tags,
        )

        txn = await self._fixture(svc, async_db_session)
        for name in ("Business", "Travel"):
            row = await svc.propose_change(
                "transaction.tag",
                {"transaction_id": txn.id, "tag": name},
                owner_user_id=1,
            )
            await svc.approve_change(row.id, owner_user_id=1)

        tags = await transaction_tags(async_db_session, [txn.id])
        assert sorted(t.name for t in tags[txn.id]) == ["Business", "Travel"]

    @pytest.mark.asyncio
    async def test_the_tag_card_shows_the_set_before_and_after(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.ledger.transactions import (
            tag_transactions,
        )

        txn = await self._fixture(svc, async_db_session)
        await tag_transactions(async_db_session, [txn.id], "Travel", owner_user_id=1)

        row = await svc.propose_change(
            "transaction.tag",
            {"transaction_id": txn.id, "tag": "Business"},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}

        assert display["Tags"] == "Travel \u2192 Business, Travel"

    @pytest.mark.asyncio
    async def test_an_untagged_transaction_reads_none(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        txn = await self._fixture(svc, async_db_session)
        row = await svc.propose_change(
            "transaction.tag",
            {"transaction_id": txn.id, "tag": "Business"},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}
        assert display["Tags"] == "none \u2192 Business"

    @pytest.mark.asyncio
    async def test_approve_untag_detaches_only_that_tag(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.ledger.transactions import (
            tag_transactions,
            transaction_tags,
        )

        txn = await self._fixture(svc, async_db_session)
        await tag_transactions(async_db_session, [txn.id], "Business", owner_user_id=1)
        await tag_transactions(async_db_session, [txn.id], "Travel", owner_user_id=1)

        row = await svc.propose_change(
            "transaction.untag",
            {"transaction_id": txn.id, "tag": "Business"},
            owner_user_id=1,
        )
        await svc.approve_change(row.id, owner_user_id=1)

        tags = await transaction_tags(async_db_session, [txn.id])
        assert [t.name for t in tags[txn.id]] == ["Travel"]

    @pytest.mark.asyncio
    async def test_untagging_an_unknown_tag_fails_the_approval(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        txn = await self._fixture(svc, async_db_session)
        row = await svc.propose_change(
            "transaction.untag",
            {"transaction_id": txn.id, "tag": "Nonesuch"},
            owner_user_id=1,
        )

        with pytest.raises(Exception):
            await svc.approve_change(row.id, owner_user_id=1)

        await async_db_session.refresh(row)
        assert row.status == "pending"
        assert row.result.get("error")

    @pytest.mark.asyncio
    async def test_the_card_never_shows_a_duplicate_it_will_not_create(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Execute dedupes by normalized name ("business" attaches the
        existing "Business" tag); the card must predict with the same
        rule, not show "Business, business"."""
        from app.services.finance.domains.ledger.transactions import (
            tag_transactions,
        )

        txn = await self._fixture(svc, async_db_session)
        await tag_transactions(async_db_session, [txn.id], "Business", owner_user_id=1)

        row = await svc.propose_change(
            "transaction.tag",
            {"transaction_id": txn.id, "tag": "business"},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}

        assert display["Tags"] == "Business \u2192 Business"

    @pytest.mark.asyncio
    async def test_untag_describe_matches_by_normalized_name_too(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.ledger.transactions import (
            tag_transactions,
        )

        txn = await self._fixture(svc, async_db_session)
        await tag_transactions(async_db_session, [txn.id], "Business", owner_user_id=1)

        row = await svc.propose_change(
            "transaction.untag",
            {"transaction_id": txn.id, "tag": "BUSINESS!"},
            owner_user_id=1,
        )
        display = {d.label: d.value for d in await svc.describe_pending_change(row)}

        assert display["Tags"] == "Business \u2192 none"


class TestWithdraw:
    """The cleanup half of propose: an agent retracting its own pending
    mistake. Guarded to the proposer, lands as a rejection with a note -
    the audit trail keeps the fumble visible, the user never has to
    clean it up by hand."""

    @staticmethod
    async def _proposed(
        svc: FinanceService, session: AsyncSession, *, agent: str | None
    ) -> FinancePendingChange:
        account = await _account(svc)
        groceries = await _category(session, "Food & Dining:Groceries")
        txn = await _txn(svc, account.id, -897, date(2026, 6, 10), name="Deli")
        return await svc.propose_change(
            "transaction.categorize",
            {"transaction_id": txn.id, "category_id": groceries.id},
            owner_user_id=1,
            proposed_by_agent=agent,
        )

    @pytest.mark.asyncio
    async def test_the_proposer_can_withdraw_its_pending_card(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains import writes

        row = await self._proposed(svc, async_db_session, agent="finance-assistant")

        withdrawn = await writes.withdraw(
            async_db_session, row.id, agent_slug="finance-assistant", owner_user_id=1
        )

        assert withdrawn.status == "rejected"
        assert (withdrawn.result or {}).get("note") == "Withdrawn by finance-assistant."

    @pytest.mark.asyncio
    async def test_a_withdraw_reason_rides_on_the_note(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The retracted card stays visible to the user, so it has to say
        why it went - "superseded" reads as care, a bare "withdrawn" as
        flailing."""
        from app.services.finance.domains import writes

        row = await self._proposed(svc, async_db_session, agent="finance-assistant")

        withdrawn = await writes.withdraw(
            async_db_session,
            row.id,
            agent_slug="finance-assistant",
            owner_user_id=1,
            reason="Superseded by the five-row card.",
        )

        assert (withdrawn.result or {}).get("note") == (
            "Withdrawn by finance-assistant. Superseded by the five-row card."
        )

    @pytest.mark.asyncio
    async def test_an_agent_can_list_only_its_own_open_cards(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """What ``pending()`` reads: before filing a replacement, the agent
        sees what it already has open - and nothing anyone else filed."""
        from app.services.finance.domains import writes

        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        filed = []
        for day, agent in ((10, "finance-assistant"), (11, "other-agent"), (12, None)):
            txn = await _txn(svc, account.id, -897, date(2026, 6, day), name="Deli")
            filed.append(
                await svc.propose_change(
                    "transaction.categorize",
                    {"transaction_id": txn.id, "category_id": groceries.id},
                    owner_user_id=1,
                    proposed_by_agent=agent,
                )
            )
        mine = filed[0]

        rows = await writes.list_changes(
            async_db_session, owner_user_id=1, proposed_by_agent="finance-assistant"
        )

        assert [r.id for r in rows] == [mine.id]

    @pytest.mark.asyncio
    async def test_sqlite_waits_for_a_busy_writer(self) -> None:
        """Tool calls commit on their own connection while the chat run
        holds another; SQLite must wait for the lock, not fail on it."""
        from sqlalchemy import text

        from app.core import db as app_db

        if app_db.async_engine.dialect.name != "sqlite":
            pytest.skip("busy_timeout is a SQLite knob")
        async with app_db.async_engine.connect() as conn:
            timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
        assert timeout == 30000

    @pytest.mark.asyncio
    async def test_a_whole_batch_withdraws_in_one_call(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """One card, one call, one reason - and a row the user already
        decided is not dragged back into it."""
        from app.services.finance.domains import writes

        account = await _account(svc)
        groceries = await _category(async_db_session, "Food & Dining:Groceries")
        payloads = []
        for day in (10, 11, 12):
            txn = await _txn(svc, account.id, -897, date(2026, 6, day), name="Deli")
            payloads.append({"transaction_id": txn.id, "category_id": groceries.id})
        rows = await writes.propose_many(
            async_db_session,
            "transaction.categorize",
            payloads,
            owner_user_id=1,
            proposed_by_agent="finance-assistant",
        )
        batch_id = rows[0].batch_id
        await writes.reject(async_db_session, rows[0].id, owner_user_id=1)

        withdrawn = await writes.withdraw_batch(
            async_db_session,
            batch_id,
            agent_slug="finance-assistant",
            owner_user_id=1,
            reason="Superseded by the five-row card.",
        )

        assert withdrawn == 2
        notes = {
            (r.result or {}).get("note")
            for r in await writes.batch_rows(async_db_session, batch_id, owner_user_id=1)
        }
        assert "Withdrawn by finance-assistant. Superseded by the five-row card." in notes
        assert None in notes, "the row the user rejected kept its own resolution"

    @pytest.mark.asyncio
    async def test_only_the_proposer_may_withdraw(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains import writes

        row = await self._proposed(svc, async_db_session, agent="finance-assistant")

        with pytest.raises(ValueError, match="proposing agent"):
            await writes.withdraw(
                async_db_session, row.id, agent_slug="other-agent", owner_user_id=1
            )
        with pytest.raises(ValueError, match="proposing agent"):
            await writes.withdraw(
                async_db_session, row.id, agent_slug=None, owner_user_id=1
            )

    @pytest.mark.asyncio
    async def test_a_resolved_card_cannot_be_withdrawn(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains import writes

        row = await self._proposed(svc, async_db_session, agent="finance-assistant")
        await svc.reject_change(row.id, owner_user_id=1)

        with pytest.raises(ValueError, match="already rejected"):
            await writes.withdraw(
                async_db_session,
                row.id,
                agent_slug="finance-assistant",
                owner_user_id=1,
            )


class TestLegacyInvalidPayloads:
    """Rows filed before a payload rule tightened must stay resolvable.

    Validation guards the DOOR (propose); a stored card that no longer
    validates is exactly the thing reject/withdraw exist to clean up,
    so resolution and description fall back to the raw payload instead
    of raising."""

    @staticmethod
    def _legacy_row() -> FinancePendingChange:
        # Filed directly, the way a pre-validator card exists in the DB.
        return FinancePendingChange(
            owner_user_id=1,
            change_type="transaction.split",
            payload={
                "transaction_id": 999,
                "parts": [{"amount": -399, "category_id": 1, "memo": None}],
            },
            proposed_by_agent="finance-assistant",
        )

    @pytest.mark.asyncio
    async def test_a_no_longer_valid_card_can_still_be_rejected(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains import writes

        row = self._legacy_row()
        async_db_session.add(row)
        await async_db_session.flush()

        rejected = await writes.reject(async_db_session, row.id, owner_user_id=1)

        assert rejected.status == "rejected"
        display = (rejected.result or {}).get("display")
        assert display and "-399" in str(display)  # raw payload as the record

    @pytest.mark.asyncio
    async def test_and_still_be_withdrawn_and_described(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains import writes

        row = self._legacy_row()
        async_db_session.add(row)
        await async_db_session.flush()

        card = await writes.describe_change(async_db_session, row)
        assert "-399" in str(card)  # renders instead of raising

        withdrawn = await writes.withdraw(
            async_db_session, row.id, agent_slug="finance-assistant", owner_user_id=1
        )
        assert withdrawn.status == "rejected"
