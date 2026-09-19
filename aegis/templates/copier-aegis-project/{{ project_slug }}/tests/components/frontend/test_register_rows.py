"""A register row sorts by what the column shows.

``DataTable`` sorts a control cell by its ``.data`` (see
``data_table.py``'s ``cell_text``), falling back to ``.value`` for
plain text. Payee and Tags both render a ``ft.Row``, which has no
``.value`` of its own - so both columns stop sorting the moment a cell
is built without setting ``.data``.

That failure is silent. Nothing raises, the rows render correctly, and
the only symptom is a header click that does nothing. Two comments in
the old closures said as much; this asserts it instead.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.rows import (
    RegisterRowBuilder,
)


class _RecordingPicker:
    """Stands in for a picker button; records what it was opened for."""

    def __init__(self) -> None:
        self.opened_for: list[list[Any]] = []

    def open_for(self, ids: list[Any], event: ft.ControlEvent) -> None:
        self.opened_for.append(ids)


def _builder(*, all_accounts: bool = False) -> RegisterRowBuilder:
    return RegisterRowBuilder(
        all_accounts=all_accounts,
        account_names={7: "Checking"},
        category_picker=_RecordingPicker(),
        merchant_picker=_RecordingPicker(),
        on_tag_tap=lambda tag: None,
        split_category_cell=lambda record: ft.Text("split"),
    )


TXN = {
    "id": 1,
    "date": "2026-09-18",
    "name": "SQ *BLUE BOTTLE 1234",
    "merchant": "Blue Bottle",
    "category": "Coffee",
    "account_id": 7,
    "source": "plaid",
    "amount": -650,
    "tags": [{"name": "work"}, {"name": "travel"}],
}


class TestSortingSurvivesTheControlCells:
    def test_the_payee_cell_sorts_by_the_payee(self) -> None:
        cell = _builder().payee_cell(TXN)
        assert cell.data == "Blue Bottle"

    def test_a_payee_less_row_sorts_by_the_bank_descriptor(self) -> None:
        """The descriptor is what the column shows when there is no
        payee, so it is what the column must sort by."""
        cell = _builder().payee_cell({**TXN, "merchant": None})
        assert cell.data == "SQ *BLUE BOTTLE 1234"

    def test_the_tags_cell_sorts_by_its_tag_names(self) -> None:
        cell = _builder().tags_cell(TXN)
        assert cell.data == "work, travel"

    def test_an_untagged_row_sorts_as_empty_not_as_missing(self) -> None:
        """``None`` would sort a blank cell against a string and raise;
        empty sorts it to one end, which is the wanted behaviour."""
        cell = _builder().tags_cell({**TXN, "tags": []})
        assert cell.data == ""


class TestTheAccountColumn:
    def test_it_is_absent_for_a_single_account_register(self) -> None:
        assert _builder().account_cells(TXN) == []

    def test_it_names_the_account_when_showing_all_of_them(self) -> None:
        cells = _builder(all_accounts=True).account_cells(TXN)
        assert [c.value for c in cells] == ["Checking"]

    def test_an_unknown_account_reads_as_no_value(self) -> None:
        cells = _builder(all_accounts=True).account_cells({**TXN, "account_id": 999})
        assert [c.value for c in cells] == ["—"]


class TestTheRowShape:
    def test_a_transaction_and_a_trade_produce_the_same_column_count(self) -> None:
        """They share one table, so a row that is short by a cell
        silently shifts every column after it."""
        trade = {"trade_date": "2026-09-18", "type": "buy", "amount": 1000}
        assert len(_builder().row("txn", TXN)) == len(_builder().row("trade", trade))

    def test_the_account_column_widens_both_kinds_together(self) -> None:
        trade = {"trade_date": "2026-09-18", "type": "buy", "amount": 1000}
        one = _builder()
        every = _builder(all_accounts=True)
        assert len(every.row("txn", TXN)) == len(one.row("txn", TXN)) + 1
        assert len(every.row("trade", trade)) == len(one.row("trade", trade)) + 1

    def test_a_trade_is_not_categorised(self) -> None:
        """Trades are position moves, not spending - the category cell
        is a dash rather than a picker trigger."""
        trade = {"trade_date": "2026-09-18", "type": "buy", "amount": 1000}
        assert _builder().row("trade", trade)[2].value == "—"
