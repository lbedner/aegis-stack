"""Fetching the uncategorized rows, and drawing them as a table."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
)
from app.components.frontend.controls.table import TableNameText

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
    _DENSE_ROW_HEIGHT,
    _UNCATEGORIZED_COLUMNS,
    _UNCATEGORIZED_LOAD_LIMIT,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    range_start,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    _transaction_expanded_content,
    fetch_tag_options,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    date_cell,
)


class UncategorizedTableMixin:
    """The read and the draw for ``UncategorizedPanel``. Every control it

    fills is built by the panel's ``__init__``; what this needs is
        declared below so the module type checks on its own.
    """

    if TYPE_CHECKING:
        page: ft.Page | None
        update: Callable[[], None]
        _account_filter: Any
        _account_filter_button: Any
        _account_items: list[dict[str, Any]]
        _account_names: dict[int, str]
        _body: ft.Column
        _bulk_categorize_trigger: Any
        _bulk_tag_trigger: Any
        _categories: list[dict[str, Any]]
        _category_picker: Any
        _tag_picker: Any
        _debounce: Any
        _header: Any
        _items: list[dict[str, Any]]
        _ordered: list[dict[str, Any]]
        _pending: dict[int, int]
        _query: str
        _range_days: int
        _save_button: Any
        _selected: set[int]
        _selection_label: Any
        _suggested: dict[int, Any]
        _tags: list[dict[str, Any]]
        _total: int

        def _category_cell(self, *args: Any, **kwargs: Any) -> Any: ...

    async def _load(self, *, reset_state: bool = True) -> None:
        """``reset_state=False`` for a search-, range-, or account-filter-
        triggered reload: the server response is a different SUBSET of
        the same backlog, not a fresh backlog - a pending pick or an
        unreviewed suggestion on a row that happens not to match the
        current search text, date range, or account selection is still
        real, unsaved work, and narrowing the view was wiping it. True
        fresh loads (initial mount, post-Save) keep clearing: that state
        genuinely doesn't apply to a new fetch there.
        """
        from app.components.frontend.state.session_state import get_session_state
        from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES

        # Claim this run - two requests in flight can return out of
        # order, so a superseded one must not paint (same guard the
        # Accounts register uses around its own search).
        sequence = self._debounce.sequence
        api = get_session_state(self.page).api_client

        if not self._categories:
            cat_data = await api.get("/api/v1/finance/categories/options", cache_ttl=30)
            cat_items = cat_data.get("items", []) if isinstance(cat_data, dict) else []
            self._categories = [
                (str(c["id"]), c["name"])
                for c in cat_items
                if str(c.get("name", "")).lower() not in UNCATEGORIZED_CATEGORY_NAMES
            ]
            self._category_picker.update_categories(self._categories)
        self._tags = await fetch_tag_options(api)
        self._tag_picker.update_tags(self._tags)

        if not self._account_names:
            acct_data = await api.get(
                "/api/v1/finance/accounts",
                params={"page_size": 200},
                cache_ttl=30,
            )
            self._account_items = (
                acct_data.get("items", []) if isinstance(acct_data, dict) else []
            )
            self._account_names = {a["id"]: a["name"] for a in self._account_items}
        # Every load, not just the first fetch above: a filter change
        # (toggling one account, "Remove all") has to redraw the menu's
        # own dots/trigger label too, not just refilter the table below -
        # this was gated behind the fetch-once cache, so the menu stayed
        # stuck showing the state from whenever it first mounted while the
        # table underneath it kept correctly refiltering (confirmed live:
        # "Remove all" correctly emptied the table, but every dot in the
        # still-open menu stayed lit). None when a shared button above the
        # tab strip owns this instead (see the constructor).
        if self._account_filter_button is not None:
            self._account_filter_button.set_accounts(self._account_items)

        # An explicit empty selection ("Remove all") means literally
        # nothing, not "no filter" - AccountFilter.params() is never
        # called in this state (see its own docstring), so the fetch is
        # skipped outright instead, same as OverviewTab's own charts do.
        if self._account_filter.is_empty:
            if not self._debounce.is_current(sequence):
                return
            self._items = []
            self._total = 0
            if reset_state:
                self._pending.clear()
                self._suggested.clear()
                self._selected.clear()
            self._render_table()
            return

        params: dict[str, object] = {
            "limit": _UNCATEGORIZED_LOAD_LIMIT,
            **self._account_filter.params(),
        }
        if self._query:
            params["q"] = self._query
        from_date = range_start(self._range_days)
        if from_date is not None:
            params["from"] = from_date.isoformat()
        data = await api.get("/api/v1/finance/uncategorized", params=params)
        if not self._debounce.is_current(sequence):
            return  # a newer keystroke already owns this load
        self._items = data.get("items", []) if isinstance(data, dict) else []
        self._total = data.get("total", 0) if isinstance(data, dict) else 0
        if reset_state:
            self._pending.clear()
            self._suggested.clear()
            self._selected.clear()

        self._render_table()

    def _header_text(self) -> str:
        return (
            "Nothing left to categorize."
            if not self._items
            else f"Showing {len(self._items)} of {self._total:,}"
            if self._total > len(self._items)
            else f"{self._total:,} to review"
        )

    def _render_table(self) -> None:
        """Rebuild the table from in-memory state (no re-fetch) - called
        after a real data change (a load, a search, a save). A single
        row's pick/accept/reject/clear does NOT come through here - see
        ``_refresh_category_cell``, which swaps just that row's cell in
        place instead of rebuilding all ~900 rows for a one-row change.

        Also the single source of truth for the header text - both
        ``_load`` and ``_save_pending`` used to set it themselves before
        calling this, which was one more place for the two to drift.
        Every real state change ends up here, so this is the one spot
        that always has the freshest counts to hand.

        Suggested rows sort to the top - after Auto-categorize they'd
        otherwise be scattered wherever their transaction falls in normal
        date order, and the whole point of clicking that button is to
        review what it proposed, not hunt through the list for it.
        ``sorted`` is stable, so date order still holds within each group.
        A row accepted/rejected one at a time afterward stays put rather
        than re-sorting out from under the cursor - only a fresh sweep
        (Auto-categorize itself, which does call this) regroups them.
        This is just the NATURAL order though - clicking the Category
        header (or any other column's) overrides it via DataTable's own
        generic sort, same as every other column.
        """
        ordered = sorted(
            self._items, key=lambda txn: 0 if txn["id"] in self._suggested else 1
        )
        self._ordered = ordered
        self._category_cells = {}
        selected_indices = {
            i for i, txn in enumerate(ordered) if txn["id"] in self._selected
        }
        self._header.value = self._header_text()
        self._body.content = DataTable(
            columns=_UNCATEGORIZED_COLUMNS,
            rows=[self._row(item) for item in ordered],
            empty_message="No uncategorized transactions.",
            scroll_height=560,
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            selectable=True,
            selected_indices=selected_indices,
            on_selection_change=self._on_selection_change,
            # Same inline row-expand the Accounts register uses
            # (TransactionsPanel._load) - the checkbox and the category
            # cell each claim their own tap, so this only fires from the
            # rest of the row (date/payee/amount, or empty space), same as
            # any other Flet control nested in a row.
            expandable_content=self._expand_transaction_detail,
        )
        self._save_button.disabled = not self._pending
        self._update_selection_label()
        if self.page:
            self.update()

    def _row(self, txn: dict) -> list[ft.Control]:
        name = txn.get("name") or txn.get("merchant_name") or "(no description)"
        account_name = self._account_names.get(txn.get("account_id"), "—")
        return [
            date_cell(txn.get("date")),
            # A plain string, not a pre-built SecondaryText - letting
            # DataTable's own style_cell() construct it is what gives it
            # the column's style="secondary" AND the single-line ellipsis
            # truncation style_cell applies; a hand-built control bypasses
            # both (style_cell passes any already-built control through
            # untouched).
            account_name,
            TableNameText(name),
            _amount_cell(txn.get("amount") or 0),
            self._category_cell(txn["id"]),
        ]

    def _expand_transaction_detail(self, idx: int) -> ft.Control:
        if idx >= len(self._ordered):
            return ft.Container()
        return _transaction_expanded_content(self._ordered[idx])

    def _on_selection_change(self, indices: set[int]) -> None:
        """DataTable's own checkbox toggling stays cheap (no table
        rebuild) by owning selection between renders itself - this just
        mirrors the result back into transaction ids, which survive
        across the NEXT rebuild (a pick, an accept/reject, a reload)
        where DataTable's own index-based state does not."""
        self._selected = {
            self._ordered[i]["id"] for i in indices if i < len(self._ordered)
        }
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        count = len(self._selected)
        self._selection_label.value = f"{count} selected" if count else ""
        self._selection_label.visible = bool(count)
        if self._selection_label.page:
            self._selection_label.update()
        self._bulk_categorize_trigger.set_count(count)
        self._bulk_tag_trigger.set_count(count)

    def _open_bulk_categorize(self, e: ft.ControlEvent) -> None:
        if self._selected:
            self._category_picker.open_for(list(self._selected), e)

    def _open_bulk_tag(self, e: ft.ControlEvent) -> None:
        if self._selected:
            self._tag_picker.open_for(list(self._selected), e)
