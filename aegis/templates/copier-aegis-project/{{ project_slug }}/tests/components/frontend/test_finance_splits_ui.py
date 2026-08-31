"""The register's split-transaction surfaces.

A split parent's category cell stops being a category picker (its own
category no longer reports) and becomes the split summary; the row-expand
detail lists the lines and carries the edit/remove actions; an unsplit
row offers the way in.
"""

from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    _transaction_expanded_content,
    split_summary_label,
)
from tests.components.frontend._tree import texts

_SPLITS = [
    {"id": 1, "amount": -2_500, "category": "Food:Groceries", "memo": "food"},
    {"id": 2, "amount": -5_100, "category": "Shopping", "memo": None},
]


class TestSplitSummaryLabel:
    def test_two_lines_show_the_first_leaf_and_a_count(self) -> None:
        assert split_summary_label(_SPLITS) == "Split · Groceries +1"

    def test_a_single_line_shows_just_the_leaf(self) -> None:
        assert split_summary_label(_SPLITS[:1]) == "Split · Groceries"

    def test_an_uncategorized_line_reads_as_such(self) -> None:
        assert (
            split_summary_label([{"id": 1, "amount": -100, "category": None}])
            == "Split · Uncategorized"
        )


class TestExpandedContent:
    def test_split_rows_list_their_lines_with_actions(self) -> None:
        txn = {"id": 7, "amount": -7_600, "is_split": True, "splits": _SPLITS}

        content = _transaction_expanded_content(
            txn,
            on_edit_split=lambda _t: None,
            on_unsplit=lambda _t: None,
        )

        rendered = texts(content)
        assert "Food:Groceries" in rendered
        assert "Shopping" in rendered
        assert "$25.00" in " ".join(rendered)
        assert "food" in rendered
        assert any("Edit split" in t for t in rendered)
        assert any("Remove split" in t for t in rendered)

    def test_unsplit_rows_offer_the_way_in(self) -> None:
        txn = {"id": 7, "amount": -7_600, "is_split": False, "splits": []}

        content = _transaction_expanded_content(
            txn, on_edit_split=lambda _t: None, on_unsplit=lambda _t: None
        )

        rendered = texts(content)
        assert any("Split" in t for t in rendered)
        assert not any("Remove split" in t for t in rendered)

    def test_without_callbacks_no_split_actions_render(self) -> None:
        """Surfaces outside the register (recurring previews, drill-downs)
        pass no callbacks and must render exactly as before."""
        txn = {"id": 7, "amount": -7_600, "is_split": False, "splits": []}

        rendered = texts(_transaction_expanded_content(txn))

        assert not any("Split" in t for t in rendered)
