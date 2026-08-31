"""Split transactions: one purchase, many categories.

The schema (``FinanceTransactionSplit`` + ``is_split``) predates this;
these tests pin the surface that makes it a feature. The contract:

- The parent row is never touched - its amount, category and history
  stay exactly as imported. Splits are separate child rows.
- Parts are given as positive magnitudes and the service fills the
  difference: split a $76 Target run knowing only "food was $25" and a
  $51 remainder line inheriting the parent's own category appears.
- Category reporting swaps a split parent for its lines - budgets and
  the categories tab count $25 of food, not $76 of Shopping - while
  payee, cashflow and account math stay on the parent (the lines sum to
  it, so nothing double-counts).
"""

from datetime import date

import pytest

from app.services.finance.domains import writes
from app.services.finance.domains.ledger import queries as ledger_queries
from app.services.finance.domains.planning import queries as planning_queries
from app.services.finance.domains.planning.budgets import (
    queries as budget_queries,
)
from app.services.finance.schemas import SplitPart
from app.services.finance.service import FinanceService

AUG = date(2026, 8, 15)


async def _target_run(
    svc: FinanceService, *, amount: int = -7_600
) -> tuple[int, int, int]:
    """A categorized Target purchase: (transaction_id, shopping_id, food_id)."""
    shopping = await svc.get_or_create_category_from_hint("Shopping")
    food = await svc.get_or_create_category_from_hint("Food:Groceries")
    account = await svc.create_manual_account(
        name="Checking",
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )
    txn = await svc.create_transaction(
        account_id=account.id,
        amount=amount,
        txn_date=AUG,
        owner_user_id=1,
        name="Target",
        category_id=shopping.id,
    )
    return txn.id, shopping.id, food.id


class TestSplitTransaction:
    @pytest.mark.asyncio
    async def test_remainder_is_filled_with_the_parent_category(
        self, svc: FinanceService
    ) -> None:
        """Knowing only "food was $25" of a $76 run must produce the $51
        difference automatically, filed under the parent's own category."""
        txn_id, shopping_id, food_id = await _target_run(svc)

        splits = await svc.split_transaction(
            txn_id,
            [SplitPart(amount=2_500, category_id=food_id, memo="groceries")],
            owner_user_id=1,
        )

        assert [(s.amount, s.category_id) for s in splits] == [
            (-2_500, food_id),
            (-5_100, shopping_id),
        ]
        parent = await ledger_queries.transaction_by_id(svc.db, txn_id)
        assert parent is not None
        assert parent.amount == -7_600
        assert parent.category_id == shopping_id
        assert parent.is_split is True

    @pytest.mark.asyncio
    async def test_exact_parts_add_no_remainder_line(
        self, svc: FinanceService
    ) -> None:
        txn_id, shopping_id, food_id = await _target_run(svc)

        splits = await svc.split_transaction(
            txn_id,
            [
                SplitPart(amount=2_500, category_id=food_id),
                SplitPart(amount=5_100, category_id=shopping_id),
            ],
            owner_user_id=1,
        )

        assert [s.amount for s in splits] == [-2_500, -5_100]
        assert sum(s.amount for s in splits) == -7_600

    @pytest.mark.asyncio
    async def test_resplitting_replaces_the_prior_lines(
        self, svc: FinanceService
    ) -> None:
        """Correcting a split must not stack new lines on the old ones."""
        txn_id, _, food_id = await _target_run(svc)
        await svc.split_transaction(
            txn_id, [SplitPart(amount=2_500, category_id=food_id)], owner_user_id=1
        )

        await svc.split_transaction(
            txn_id, [SplitPart(amount=3_000, category_id=food_id)], owner_user_id=1
        )

        by_parent = await svc.transaction_splits([txn_id])
        assert [s.amount for s in by_parent[txn_id]] == [-3_000, -4_600]
        assert sum(s.amount for s in by_parent[txn_id]) == -7_600

    @pytest.mark.asyncio
    async def test_parts_exceeding_the_parent_are_rejected(
        self, svc: FinanceService
    ) -> None:
        txn_id, _, food_id = await _target_run(svc)

        with pytest.raises(ValueError, match="exceed"):
            await svc.split_transaction(
                txn_id,
                [SplitPart(amount=9_999, category_id=food_id)],
                owner_user_id=1,
            )

    @pytest.mark.asyncio
    async def test_nonpositive_and_empty_parts_are_rejected(
        self, svc: FinanceService
    ) -> None:
        """Parts are magnitudes; the parent's sign is applied for you."""
        txn_id, _, food_id = await _target_run(svc)

        with pytest.raises(ValueError, match="positive"):
            await svc.split_transaction(
                txn_id,
                [SplitPart(amount=-2_500, category_id=food_id)],
                owner_user_id=1,
            )
        with pytest.raises(ValueError, match="at least one"):
            await svc.split_transaction(txn_id, [], owner_user_id=1)

    @pytest.mark.asyncio
    async def test_unsplit_removes_the_lines_and_clears_the_flag(
        self, svc: FinanceService
    ) -> None:
        txn_id, _, food_id = await _target_run(svc)
        await svc.split_transaction(
            txn_id, [SplitPart(amount=2_500, category_id=food_id)], owner_user_id=1
        )

        removed = await svc.unsplit_transaction(txn_id, owner_user_id=1)

        assert removed == 2
        parent = await ledger_queries.transaction_by_id(svc.db, txn_id)
        assert parent is not None
        assert parent.is_split is False
        assert await svc.transaction_splits([txn_id]) == {}

    @pytest.mark.asyncio
    async def test_income_splits_carry_the_parent_sign(
        self, svc: FinanceService
    ) -> None:
        """A positive parent (a refund, a paycheck) splits into positive
        lines - magnitudes always follow the parent's sign."""
        txn_id, _, food_id = await _target_run(svc, amount=7_600)

        splits = await svc.split_transaction(
            txn_id, [SplitPart(amount=2_500, category_id=food_id)], owner_user_id=1
        )

        assert [s.amount for s in splits] == [2_500, 5_100]


class TestSplitAwareReporting:
    async def _split_target_run(self, svc: FinanceService) -> tuple[int, int, int]:
        txn_id, shopping_id, food_id = await _target_run(svc)
        await svc.split_transaction(
            txn_id, [SplitPart(amount=2_500, category_id=food_id)], owner_user_id=1
        )
        return txn_id, shopping_id, food_id

    @pytest.mark.asyncio
    async def test_spend_by_category_counts_lines_not_the_parent(
        self, svc: FinanceService
    ) -> None:
        """The budget-actuals read: $25 of food and $51 of shopping,
        never $76 of shopping (and never both, which would double-count)."""
        _, shopping_id, food_id = await self._split_target_run(svc)

        spent = await planning_queries.spend_by_category(
            svc.db,
            owner_user_id=1,
            start=date(2026, 8, 1),
            end=date(2026, 9, 1),
            category_ids=[shopping_id, food_id],
        )

        assert spent == {food_id: 2_500, shopping_id: 5_100}

    @pytest.mark.asyncio
    async def test_outflow_tuples_swaps_the_parent_for_its_lines(
        self, svc: FinanceService
    ) -> None:
        """The budget-summary corpus: category tallies see the lines,
        while the payee tally still sees the full $76 under Target."""
        _, shopping_id, food_id = await self._split_target_run(svc)

        rows = await budget_queries.outflow_tuples(
            svc.db, owner_user_id=1, start=date(2026, 8, 1), end=date(2026, 9, 1)
        )

        amounts_by_category: dict[int | None, int] = {}
        for category_id, _merchant, _original, _name, amount, _stream in rows:
            amounts_by_category[category_id] = (
                amounts_by_category.get(category_id, 0) + amount
            )
        assert amounts_by_category == {food_id: -2_500, shopping_id: -5_100}
        assert all(name == "Target" for _c, _m, _o, name, _a, _s in rows)
        assert sum(amount for *_ignored, amount, _stream in rows) == -7_600

    @pytest.mark.asyncio
    async def test_category_usage_rows_count_the_lines(
        self, svc: FinanceService
    ) -> None:
        """The categories tab: food shows 1 use / $25, shopping shows the
        $51 remainder rather than the whole run."""
        _, shopping_id, food_id = await self._split_target_run(svc)

        rows = await ledger_queries.category_usage_rows(svc.db, owner_user_id=1)

        by_id = {row[0]: (row[4], row[5]) for row in rows}
        assert by_id[food_id] == (1, -2_500)
        assert by_id[shopping_id] == (1, -5_100)

    @pytest.mark.asyncio
    async def test_category_spend_totals_count_the_lines(
        self, svc: FinanceService
    ) -> None:
        _, _, food_id = await self._split_target_run(svc)

        totals = dict(
            await ledger_queries.category_spend_totals(
                svc.db, owner_user_id=1, start=date(2026, 8, 1)
            )
        )

        assert totals["Food:Groceries"] == -2_500
        assert totals["Shopping"] == -5_100

    @pytest.mark.asyncio
    async def test_register_category_filter_surfaces_the_split_parent(
        self, svc: FinanceService
    ) -> None:
        """Filtering the register by a line's category must find the
        parent - the $76 Target row IS where the $25 of food lives."""
        txn_id, _, food_id = await self._split_target_run(svc)

        rows, total = await ledger_queries.transactions_page(
            svc.db, owner_user_id=1, category_id=food_id
        )

        assert total == 1
        assert [t.id for t in rows] == [txn_id]

    @pytest.mark.asyncio
    async def test_split_parents_never_count_as_uncategorized(
        self, svc: FinanceService
    ) -> None:
        """An uncategorized parent whose lines are all filed is done -
        it must not sit in the attention queue forever."""
        food = await svc.get_or_create_category_from_hint("Food:Groceries")
        account = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        txn = await svc.create_transaction(
            account_id=account.id,
            amount=-7_600,
            txn_date=AUG,
            owner_user_id=1,
            name="Target",
        )
        await svc.split_transaction(
            txn.id, [SplitPart(amount=7_600, category_id=food.id)], owner_user_id=1
        )

        rows, total = await ledger_queries.uncategorized_page(
            svc.db, owner_user_id=1
        )

        assert total == 0
        assert rows == []


class TestSplitChangeType:
    """The agent write surface: ``transaction.split`` rides the
    propose/approve queue like every other mutation - proposed with
    magnitudes, described with the remainder the approval will create,
    executed only on the user's nod."""

    @pytest.mark.asyncio
    async def test_propose_describes_and_approve_executes(
        self, svc: FinanceService
    ) -> None:
        txn_id, _, food_id = await _target_run(svc)

        row = await writes.propose(
            svc.db,
            "transaction.split",
            {
                "transaction_id": txn_id,
                "parts": [
                    {"amount": 2_500, "category_id": food_id, "memo": "groceries"}
                ],
            },
            owner_user_id=1,
            proposed_by_agent="finance-assistant",
        )
        card = await writes.describe_change(svc.db, row)

        # Itemized: one row per line, so the approval card reads as the
        # split the user is about to authorize - remainder included.
        assert [line.label for line in card[1:]] == ["Food:Groceries", "Shopping"]
        assert card[1].value == "$25.00 · groceries"
        assert card[2].value == "$51.00 · the rest"
        # The subject line reads like a person wrote it, not a log line.
        assert "Aug 15, 2026" in card[0].value
        assert "2026-08-15" not in card[0].value

        await writes.approve(svc.db, row.id, owner_user_id=1)

        by_parent = await svc.transaction_splits([txn_id])
        assert [s.amount for s in by_parent[txn_id]] == [-2_500, -5_100]

    @pytest.mark.asyncio
    async def test_bad_magnitudes_die_at_propose_not_as_cards(
        self, svc: FinanceService
    ) -> None:
        """The queue's contract: a card the user cannot safely approve
        must never exist. Negative or empty parts are refused at the
        door, so the error loops back to the agent instead of lingering
        as a zombie card."""
        txn_id, _, food_id = await _target_run(svc)

        with pytest.raises(ValueError, match="positive magnitudes"):
            await writes.propose(
                svc.db,
                "transaction.split",
                {
                    "transaction_id": txn_id,
                    "parts": [{"amount": -2_500, "category_id": food_id}],
                },
                owner_user_id=1,
            )
        with pytest.raises(ValueError, match="at least one part"):
            await writes.propose(
                svc.db,
                "transaction.split",
                {"transaction_id": txn_id, "parts": []},
                owner_user_id=1,
            )

    @pytest.mark.asyncio
    async def test_an_overflowing_proposal_fails_at_approve_and_stays_pending(
        self, svc: FinanceService
    ) -> None:
        """Magnitude rules are the service's; the queue's job is to
        surface the failure as audit and leave the decision open."""
        txn_id, _, food_id = await _target_run(svc)
        row = await writes.propose(
            svc.db,
            "transaction.split",
            {
                "transaction_id": txn_id,
                "parts": [{"amount": 9_999_999, "category_id": food_id}],
            },
            owner_user_id=1,
        )

        with pytest.raises(ValueError, match="exceed"):
            await writes.approve(svc.db, row.id, owner_user_id=1)

        assert row.status == "pending"
        assert "exceed" in (row.result or {}).get("error", "")
