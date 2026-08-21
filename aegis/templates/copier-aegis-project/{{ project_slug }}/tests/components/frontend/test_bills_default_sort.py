"""Bills & Income opens on what is due SOONEST.

The page answers "what is coming up", so the first row has to be the next
thing to pay. It opened newest-due-first, which puts the furthest-away
bill at the top and the one due tomorrow somewhere below the fold.
"""

from app.components.frontend.controls import DataTable, DataTableColumn
from app.components.frontend.dashboard.modals.finance_recurring_tab import (
    _COLUMNS,
    _NEXT_DUE_COLUMN,
    _NEXT_DUE_SORT_DESC,
)
from app.components.frontend.dashboard.modals.modal_sections import date_cell


class TestTheDefaultSort:
    def test_the_sorted_column_really_is_next_due(self) -> None:
        """``_NEXT_DUE_COLUMN`` is an INDEX into ``_COLUMNS``. Inserting a
        column ahead of it silently moves the sort to a neighbour, which
        no other test would notice - the table still sorts, just by the
        wrong thing."""
        assert _COLUMNS[_NEXT_DUE_COLUMN].header == "Next due"

    def test_the_default_is_ascending(self) -> None:
        assert _NEXT_DUE_SORT_DESC is False


class TestWhatThatOrderingActuallyDoes:
    """Through the real DataTable and the real date cell, because the
    ordering is a product of both: ``date_cell`` stamps the ISO date as
    the sort key so a humanized "Aug 1, 2026" does not collate
    alphabetically."""

    def _table(self, days: list[str]) -> DataTable:
        return DataTable(
            columns=[DataTableColumn("Next due")],
            rows=[[date_cell(d)] for d in days],
            initial_sort=0,
            initial_sort_desc=_NEXT_DUE_SORT_DESC,
        )

    def _order(self, table: DataTable) -> list[str]:
        """Display order, which is where the sort actually lives -
        ``_rows`` stays in insertion order and ``_display_order`` maps
        onto it."""
        return [str(table._rows[i][0].data) for i in table._display_order()]

    def test_the_soonest_bill_comes_first(self) -> None:
        table = self._table(["2026-12-01", "2026-08-13", "2026-09-30"])
        assert self._order(table) == ["2026-08-13", "2026-09-30", "2026-12-01"]

    def test_a_bill_with_no_due_date_sinks_to_the_bottom(self) -> None:
        """Ascending would normally float a blank to the top, which is the
        one row you least need to see on a "what is next" list. The
        table's type-ranked key already sorts blanks last; this pins that
        the two behaviours combine the way the page needs."""
        table = self._table(["2026-12-01", "", "2026-08-13"])
        assert self._order(table)[-1] == ""
        assert self._order(table)[0] == "2026-08-13"

    def test_chronological_not_alphabetical(self) -> None:
        """Chronological, not alphabetical: "Aug" before "Dec" is luck,
        "Sep 30" before "Oct 1" is not."""
        table = self._table(["2026-10-01", "2026-09-30"])
        assert self._order(table) == ["2026-09-30", "2026-10-01"]
