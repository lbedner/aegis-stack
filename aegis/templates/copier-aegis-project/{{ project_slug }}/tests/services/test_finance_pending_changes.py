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
        display = {
            d["label"]: d["value"] for d in await svc.describe_pending_change(row)
        }

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
        display = {
            d["label"]: d["value"] for d in await svc.describe_pending_change(row)
        }

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
            d["label"]: d["value"] for d in await svc.describe_pending_change(resolved)
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
            d["label"]: d["value"] for d in await svc.describe_pending_change(resolved)
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
        display = {
            d["label"]: d["value"] for d in await svc.describe_pending_change(row)
        }

        assert "$1,000.00" in display["Payment"]
        assert "2026-07-31" in display["Payment"]
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
        display = {
            d["label"]: d["value"] for d in await svc.describe_pending_change(row)
        }

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
        display = {
            d["label"]: d["value"] for d in await svc.describe_pending_change(row)
        }
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
