"""One category cell, in each of the states it can be in."""

from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.controls.pickers import (
    picker_trigger_cell,
)
from app.components.frontend.controls.table import TableCellText, TableNameText

# Named rows in the import review's detail sections before the tail folds
# into a count. A Quicken tree can carry hundreds of new categories, and a
# dialog that scrolls for a page stops being read at all.
# One height for every Overview card, so the row has a single baseline.
# Named slices in the spending donut (and rows in the list under it) before
# the tail folds into "Other". Five left "Other" as the biggest slice on any
# real ledger, which hides exactly the breakdown the card exists to show.
# Measured against a real ledger (23 parent-level categories after the
# spending_by_category rollup): 10 slices still left "Other" at 16.3%; 15
# gets it to 5.3%, with everything past #15 individually under 1% of total
# spend - the tail at that point really is "everything else", not a few
# disguised top categories. PieChartCard's legend scrolls within its fixed
# height (modal_sections.py) rather than clipping, so this isn't bounded
# by legend space anymore.
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _CATEGORY_COLUMN_WIDTH,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    CompactIconButton,
)
from app.components.frontend.theme import AegisTheme as Theme


class CategoryCellMixin:
    """Empty, staged, or carrying a suggestion. The panel keeps the cells

    by transaction id so a single row can be redrawn without the table.
    """

    if TYPE_CHECKING:
        _categories: list[dict[str, Any]]
        _category_cells: dict[int, Any]
        _category_picker: Any
        _pending: dict[int, int]
        _save_button: Any
        _suggested: dict[int, Any]

        def _clear_pending(self, *args: Any, **kwargs: Any) -> Any: ...
        def _accept_suggestion(self, *args: Any, **kwargs: Any) -> Any: ...
        def _reject_suggestion(self, *args: Any, **kwargs: Any) -> Any: ...

    def _category_cell(self, transaction_id: int) -> ft.Control:
        """A stable Container, tracked in ``self._category_cells`` -
        ``_refresh_category_cell`` swaps its content in place later
        without needing a full table rebuild to reach it."""
        container = ft.Container(content=self._category_cell_content(transaction_id))
        # DataTable's generic column sort reads a cell's .value (or
        # .content.value) for plain text; this cell is a Row of buttons,
        # not text, so .data carries the sortable name explicitly -
        # DataTable's cell_text falls back to it. Flet's own generic
        # "attach arbitrary data to a control" field, not a new concept.
        container.data = self._category_sort_text(transaction_id)
        self._category_cells[transaction_id] = container
        return container

    def _category_cell_content(self, transaction_id: int) -> ft.Control:
        if transaction_id in self._pending:
            return self._pending_cell(transaction_id)
        if transaction_id in self._suggested:
            return self._suggested_cell(transaction_id)
        return self._empty_cell(transaction_id)

    def _category_sort_text(self, transaction_id: int) -> str:
        """Blank sorts last (DataTable treats "" as no value) - an
        untouched row has no category opinion yet, so it belongs after
        everything that does, in either sort direction."""
        if transaction_id in self._pending:
            return self._category_name(self._pending[transaction_id])
        if transaction_id in self._suggested:
            return self._suggested[transaction_id][1]
        return ""

    def _refresh_category_cell(self, transaction_id: int) -> None:
        """One row's state changed (pick/accept/reject/clear) - swap just
        that row's category cell content, not the whole ~900-row table."""
        container = self._category_cells.get(transaction_id)
        if container is not None:
            container.content = self._category_cell_content(transaction_id)
            container.data = self._category_sort_text(transaction_id)
            if container.page:
                container.update()
        self._save_button.disabled = not self._pending
        if self._save_button.page:
            self._save_button.update()

    def _empty_cell(self, transaction_id: int) -> ft.Container:
        """A cheap placeholder that opens the shared category-picker
        popup on tap - see ``pickers.py`` for why one popup is
        shared across every row instead of building one per cell, and
        ``category_trigger_cell``'s own docstring for why it's the width
        and the on_click no-op, not just on_tap_down, that make this
        reliably clickable."""
        return picker_trigger_cell(
            SecondaryText("Tap to categorize", size=Theme.Typography.CAPTION),
            _CATEGORY_COLUMN_WIDTH,
            on_tap=lambda e, t=transaction_id: self._category_picker.open_for([t], e),
        )

    def _pending_cell(self, transaction_id: int) -> ft.Control:
        name = self._category_name(self._pending[transaction_id])
        return ft.Row(
            [
                # expand=True: the text claims whatever's left after the
                # button's own fixed size and truncates (TableNameText's
                # own ellipsis default) INSIDE that space, instead of the
                # Row sizing to the text's full natural width first and
                # pushing the button out past the column's own edge - a
                # long category path ("Fees & Charges:Finance Charge")
                # was clipping the button clean off before this.
                ft.Container(
                    content=TableNameText(name),
                    expand=True,
                ),
                CompactIconButton(
                    ft.Icons.CLOSE,
                    ft.Colors.ON_SURFACE_VARIANT,
                    "Clear",
                    lambda _e, t=transaction_id: self._clear_pending(t),
                ),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _suggested_cell(self, transaction_id: int) -> ft.Control:
        _category_id, name = self._suggested[transaction_id]
        return ft.Row(
            [
                # Same expand=True reasoning as _pending_cell - two
                # buttons here instead of one, so there's even less
                # margin for the text to push them off the edge.
                ft.Container(
                    content=TableCellText(f"Suggested: {name}"),
                    expand=True,
                ),
                CompactIconButton(
                    ft.Icons.CHECK,
                    Theme.Colors.SUCCESS,
                    "Accept",
                    lambda _e, t=transaction_id: self._accept_suggestion(t),
                ),
                CompactIconButton(
                    ft.Icons.CLOSE,
                    Theme.Colors.ERROR,
                    "Reject",
                    lambda _e, t=transaction_id: self._reject_suggestion(t),
                ),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _category_name(self, category_id: int) -> str:
        key = str(category_id)
        for k, name in self._categories:
            if k == key:
                return name
        return f"Category {category_id}"
