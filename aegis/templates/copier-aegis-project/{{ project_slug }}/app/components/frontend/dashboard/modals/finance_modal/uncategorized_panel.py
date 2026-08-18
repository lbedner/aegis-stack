"""
Finance Service Detail Modal

A Quicken-style finance workspace, organised into tabs:

* **Accounts** — the register. A left sidebar lists accounts grouped into
  Banking / Credit / Investments / etc., each with its balance and a grand
  total; selecting one shows an account-detail header (with a Manage menu)
  above its transactions (or holdings, for investment accounts). The sidebar
  only lives on this tab.
* **Overview** — a net-worth summary (assets, liabilities, net worth) with a
  per-group breakdown. No sidebar; this is the "home" landing.

Data is fetched async through the internal ``APIClient`` (never a DB session
from the frontend). All colours, spacing, and type come from ``AegisTheme``.
"""

from collections.abc import Callable

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.debounce import Debouncer
from app.components.frontend.controls.form_fields import (
    FormTextField,
)
from app.components.frontend.controls.pickers import (
    BulkActionTrigger,
    CategoryPickerButton,
    TagPickerButton,
    picker_trigger_cell,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
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
    _DENSE_ROW_HEIGHT,
    _UNCATEGORIZED_COLUMNS,
    _UNCATEGORIZED_LOAD_LIMIT,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    CompactIconButton,
    TagApplyMixin,
    apply_category_picks,
    create_category,
    range_start,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import (
    AccountFilter,
    AccountFilterButton,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    _transaction_expanded_content,
    fetch_tag_options,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
    date_cell,
)
from app.components.frontend.theme import AegisTheme as Theme


class UncategorizedPanel(TagApplyMixin, FinancePanel):
    """A work queue for uncategorized transactions, not a report. Two
    consumers share this one class rather than duplicating it: the
    Overview card's dialog (``OverviewTab._open_uncategorized``, fixed
    ``width``) and an embedded section on ``ReviewTab`` (``width=None``,
    fills the tab instead). Each owns its own instance and data load -
    they don't share row/pending/suggestion state. They CAN share the
    ``AccountFilter`` selection (``account_filter``) and, when
    ``register_filter_listener`` is given (the ReviewTab case - a shared
    button already lives above FinanceDetailDialog's tab strip), even
    the filter BUTTON itself; the standalone popup case builds its own
    (see the constructor for why - that button would otherwise be
    unreachable behind the popup).

    Rows render through ``DataTable`` (controls/data_table.py) with
    ``scroll_height`` set, same as the account register at :1540 - that
    puts rows in a ``ft.ListView`` under the hood, so only the rows
    actually on screen get built. A plain ``ft.Column`` (the first version
    of this panel) mounts every row's full widget tree immediately
    regardless of scroll position, which is what made it feel sluggish.

    Nothing is written on pick - review-then-save. A row moves through up
    to three states, all inline (no modal - the list stays visible and
    scrollable the whole time, unlike an earlier version that opened a
    dialog per row):

    - empty: "Tap to categorize" placeholder. Tap -> opens the shared
      ``CategoryPickerButton`` popup (``pickers.py``), positioned
      at that row (``_empty_cell``'s ``on_tap_down`` -> ``open_for``) -
      search-at-top, single-select, same popup mechanism
      ``AccountFilterButton`` already uses. One instance for the whole
      panel, not one per row: an earlier version put a live dropdown in
      EVERY row up front, which with a real category count (267 in
      testing) meant up to 100 rows x 267 options each, ~27,000 Option
      controls built and serialized on every load regardless of the
      ListView only PAINTING visible rows (building the full Python
      control tree eagerly is what made it slow, not the virtualization -
      confirmed by a side-by-side test with the dropdown stripped out,
      which was fast). The shared popup sidesteps that class of problem
      entirely - its option rows are built once, not per row.
    - suggested: Auto-categorize proposed a category for this row
      (``_suggested``) but nothing is saved yet - shows "Suggested: X"
      with an accept (check) and reject (x) affordance, so a suggestion
      can be individually disagreed with rather than accepted as a batch.
    - pending: a manual pick, or an accepted suggestion (``_pending``) -
      ready to save, with a clear (x) to unpick it. The header's Save
      button is disabled until at least one row is pending, and commits
      every pending row in one pass when clicked.

    Auto-categorize never clobbers a row that already has a pending pick
    or an unreviewed suggestion - it only proposes for rows still empty.

    Same reload-not-splice idiom as ReviewTab._action / AttentionTab._dismiss
    above for the actual save: POST each pending row -> SuccessSnackBar ->
    re-``GET /uncategorized``, so a row "disappears" because the next fetch
    no longer includes it (this also resets ``_pending``/``_suggested`` -
    unsaved picks don't survive a reload or the dialog closing). Refreshing
    the Overview card's own count (a separate, read-only preview - see
    ``OverviewTab._load``) is the dialog opener's job, once, on close - not
    this panel's.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        width: int | None = 860,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener)
        # Fixed width for the Overview card's dialog (StyledAlertDialog has
        # no viewport-relative sizing of its own); width=None for embedding
        # directly in a tab (ReviewTab), which already gives it the column's
        # width to fill. No expand=True either way: the content is already
        # height-bounded internally (scroll_height on the DataTable), so
        # claiming extra vertical flex would just take space away from
        # whatever else shares the column - the transfer suggestions list,
        # when embedded - without the panel itself using it.
        if width is not None:
            self.width = width
        self._categories: list[tuple[str, str]] = []
        self._account_names: dict[int, str] = {}
        # Raw list, kept alongside _account_names - _account_filter_button
        # .set_accounts() needs the full account dicts (for grouping), not
        # just the id->name map, and it has to be called on every load (a
        # filter change re-renders the menu's dots/trigger label too, not
        # just the table), while the accounts themselves only need
        # fetching once. Keeping this separately is what lets those two
        # things happen at different frequencies.
        self._account_items: list[dict] = []
        self._items: list[dict] = []
        # Last server-reported backlog size (not just len(self._items),
        # which can be a narrower page) - tracked so Save can update the
        # header after a local splice without a full server refetch.
        self._total = 0
        # transaction_id -> category_id, a manual pick or an accepted
        # suggestion, ready to save.
        self._pending: dict[int, int] = {}
        # transaction_id -> (category_id, category_name), an unreviewed
        # Auto-categorize proposal awaiting accept/reject.
        self._suggested: dict[int, tuple[int, str]] = {}
        # Checkbox selection (DataTable's ``selectable``) - transaction
        # ids, not the table's own row indices, so a selection survives
        # a sort/rebuild instead of pointing at whatever row happens to
        # land on that index next. Scopes Auto-categorize to "just these"
        # when non-empty; the full backlog otherwise, unchanged.
        self._selected: set[int] = set()
        self._ordered: list[dict] = []
        # One stable Container per currently-rendered row's category cell,
        # keyed by transaction id - a pick/accept/reject/clear swaps just
        # THAT container's content in place (_refresh_category_cell)
        # instead of rebuilding all ~900 rows for a single row's state
        # change. Repopulated fresh on every real _render_table() rebuild.
        self._category_cells: dict[int, ft.Container] = {}
        # One shared popup for every row's category cell - see
        # pickers.py's own docstring for why this is a single
        # instance opened via open_for(), not one CategoryPickerButton
        # built per row.
        self._category_picker = CategoryPickerButton(
            categories=self._categories,
            on_pick=self._pick_category,
            on_create=self._create_category,
        )
        self._selection_label = SecondaryText("", visible=False)
        self._bulk_categorize_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_categorize
        )
        self._tags: list[tuple[str, str]] = []
        self._tag_picker = TagPickerButton(
            tags=self._tags,
            on_pick=self._apply_tag,
            on_create=self._apply_tag,
        )
        # Applies immediately, unlike the category picks this queue
        # stages behind Save - a tag is an annotation, not a
        # classification you might want to review as a batch.
        self._bulk_tag_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_tag,
            label="Tag",
            tooltip="Put a tag on every checked row at once",
        )
        self._header = SecondaryText("Loading…")
        self._body = ft.Container()
        # Same payee search as the Accounts register (TransactionsPanel,
        # :1096-1103) - same FormTextField + Debouncer wiring, same ``q``
        # param, same case-insensitive substring-on-name match server-side.
        self._query = ""
        self._debounce = Debouncer(page)
        self._search = FormTextField(
            label="Search payee",
            on_change=self._on_search_change,
            on_submit=self._on_search_submit,
            width=280,
            compact=True,
            clearable=True,
        )
        # Same trailing-window picker as the Accounts register (:1104-1122)
        # - the exact DateRangeChips control every range picker in the
        # product uses, not a bespoke one. Defaults to "All": this is a
        # work queue, not a historical register, and a narrower default
        # would silently hide backlog rows the same way the old 100-row
        # cap used to (see _UNCATEGORIZED_LOAD_LIMIT above).
        self._range_days = 9999
        self._range = DateRangeChips(
            options=[
                ("1d", 1),
                ("7d", 7),
                ("14d", 14),
                ("1m", 30),
                ("3m", 90),
                ("1y", 365),
                ("All", 9999),
            ],
            selected_days=self._range_days,
            on_change=self._on_range_change,
        )
        # Own account-filter BUTTON only when standalone (the Overview
        # card's popup, OverviewTab._open_uncategorized) - when embedded
        # as a tab (ReviewTab), FinanceDetailDialog already shows ONE
        # shared button above the tab strip, and building a second one
        # here duplicated UI over the same AccountFilter with no way to
        # keep both in sync (confirmed live: changing one left the
        # other's dots/trigger label stale - see FinanceDetailDialog's
        # own docstring on this). register_filter_listener being given at
        # all is what signals "a shared button already covers this."
        self._account_filter_button: AccountFilterButton | None = None
        if register_filter_listener is None:
            self._account_filter_button = AccountFilterButton(
                on_change=self._on_account_filter_change,
                account_filter=account_filter,
            )
            # Standalone: the button owns the filter, replacing the
            # base's default. Embedded (listener given), the base
            # already adopted the shared filter and registered the
            # reload.
            self._account_filter = self._account_filter_button.filter
        # Indeterminate (value=None -> looping, not a fake percentage - the
        # sweep is one request/response, there's no real progress fraction
        # to report) - shown only while Auto-categorize is in flight. Same
        # teal as the tab indicator (Theme.Colors.ACCENT, controls/tabs.py).
        self._progress = ft.ProgressBar(
            value=None,
            color=Theme.Colors.ACCENT,
            bgcolor=ft.Colors.with_opacity(0.15, Theme.Colors.ACCENT),
            visible=False,
        )
        self._save_button = PulseButton(
            on_click_callable=self._save_pending,
            text="Save",
            compact=True,
        )
        # Set after construction, not as a kwarg: PulseButton accepts
        # **kwargs but never forwards them to the Flet control, so
        # disabled=True was inert and Save looked clickable with nothing
        # staged until the first table render corrected it.
        self._save_button.disabled = True
        # None when a shared button above the tab strip already covers
        # this (see the constructor comment above).
        controls_row: list[ft.Control] = [self._search]
        if self._account_filter_button is not None:
            controls_row.append(self._account_filter_button)
        controls_row.append(self._range)
        self.content = ft.Column(
            [
                # On its own line: sharing a row with the search/filter
                # controls meant its own text length ("Nothing left to
                # categorize." vs "4 to review") shifted everything to its
                # right sideways every time the count changed.
                self._header,
                ft.Row(
                    [
                        *controls_row,
                        # A Container, not the ProgressBar directly: it
                        # keeps claiming this flex space regardless of the
                        # bar's own visible=True/False, so the buttons to
                        # its right don't jump sideways when the bar
                        # appears/disappears - only what's drawn inside
                        # this reserved gap changes.
                        ft.Container(
                            content=self._progress,
                            expand=True,
                            alignment=ft.alignment.center,
                        ),
                        self._selection_label,
                        self._bulk_categorize_trigger,
                        self._bulk_tag_trigger,
                        PulseButton(
                            on_click_callable=self._auto_categorize,
                            text="Auto-categorize",
                            variant="amber",
                            compact=True,
                            tooltip=(
                                "Scoped to the checked rows when any are "
                                "selected; the whole backlog otherwise"
                            ),
                        ),
                        self._save_button,
                    ],
                    spacing=Theme.Spacing.SM,
                    # END, not CENTER: _search is a FormTextField (a label
                    # ABOVE the input), everything else here is a single
                    # label-less line (chips, the filter button, buttons).
                    # Centering the whole row middles those against the
                    # label+input block's combined height, which reads as
                    # floating above the input rather than beside it - END
                    # lines their bottom edge up with the input's own.
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                self._body,
                # Zero-size: this is the shared category-picker popup's
                # OWN mount point, not part of the visible layout - see
                # its own docstring. Has to sit somewhere in the tree for
                # its did_mount to fire and register into page.overlay.
                self._category_picker,
                self._tag_picker,
            ],
            spacing=Theme.Spacing.MD,
            tight=True,
        )

    def refresh(self) -> None:
        """Public reload for a caller that keeps its own reference to a
        CACHED panel instance (``OverviewTab._open_uncategorized``) -
        ``did_mount`` only fires once, on first mount, so a cached
        panel's data would otherwise go stale after the first open."""
        if self.page:
            self.page.run_task(self._load)

    def _on_search_change(self, event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        self._query = (getattr(control, "value", "") or "").strip()
        # Type-ahead: re-filters on its own once typing pauses, same as
        # the Accounts register - Enter becomes optional, not required.
        self._debounce.schedule(lambda: self._load(reset_state=False))

    def _on_search_submit(self, event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        self._query = (getattr(control, "value", "") or "").strip()
        self._debounce.run_now(lambda: self._load(reset_state=False))

    def _on_range_change(self, days: int) -> None:
        self._range_days = days
        # Through the debouncer, not a raw page.run_task(lambda: ...) -
        # Page.run_task asserts its handler is an actual coroutine
        # function, which a lambda wrapping a call is not (see the
        # run_now fix in controls/debounce.py). Also correctly supersedes
        # an in-flight search debounce, same as pressing Enter would.
        self._debounce.run_now(lambda: self._load(reset_state=False))

    def _on_account_filter_change(self) -> None:
        self._debounce.run_now(lambda: self._load(reset_state=False))

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

    def _category_cell(self, transaction_id: int) -> ft.Control:
        """A stable Container, tracked in ``self._category_cells`` -
        ``_refresh_category_cell`` swaps its content in place later
        without needing a full table rebuild to reach it."""
        container = ft.Container(content=self._category_cell_content(transaction_id))
        # DataTable's generic column sort reads a cell's .value (or
        # .content.value) for plain text; this cell is a Row of buttons,
        # not text, so .data carries the sortable name explicitly -
        # DataTable's _cell_text falls back to it. Flet's own generic
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

    def _pick_category(self, transaction_ids: list[int], category_key: str) -> None:
        """CategoryPickerButton's on_pick contract - a single row's pick
        and a bulk "categorize the selected rows" pick are the same call,
        just with a longer list (see pickers.py's own docstring).
        Stages the pick(s) - does not save."""
        if not category_key:
            return
        category_id = int(category_key)
        for transaction_id in transaction_ids:
            self._pending[transaction_id] = category_id
            self._suggested.pop(transaction_id, None)
            self._refresh_category_cell(transaction_id)

    def _create_category(self, transaction_ids: list[int], name: str) -> None:
        """Name a category, then STAGE it on the rows - this panel saves
        on its own Save button, and creating one must not quietly become
        the exception that writes immediately."""
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._create_and_stage, transaction_ids, name)

    async def _create_and_stage(self, transaction_ids: list[int], name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await create_category(api, name)
        if created is None:
            ErrorSnackBar("Could not create that category.").launch(self.page)
            return
        key, stored = created
        if key not in {k for k, _ in self._categories}:
            self._categories = sorted(
                [*self._categories, (key, stored)], key=lambda c: c[1].casefold()
            )
            self._category_picker.update_categories(self._categories)
        self._pick_category(transaction_ids, key)
        self.page.update()

    def _clear_pending(self, transaction_id: int) -> None:
        self._pending.pop(transaction_id, None)
        self._refresh_category_cell(transaction_id)

    def _accept_suggestion(self, transaction_id: int) -> None:
        suggestion = self._suggested.pop(transaction_id, None)
        if suggestion is not None:
            self._pending[transaction_id] = suggestion[0]
        self._refresh_category_cell(transaction_id)

    def _reject_suggestion(self, transaction_id: int) -> None:
        self._suggested.pop(transaction_id, None)
        self._refresh_category_cell(transaction_id)

    async def _auto_categorize(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        self._progress.visible = True
        if self.page:
            self.update()

        scope = set(self._selected)  # snapshot - cleared below before the render
        api = get_session_state(self.page).api_client
        body = {"transaction_ids": list(scope)} if scope else {}
        result = await api.post(
            "/api/v1/finance/transactions/auto-categorize", json=body
        )
        self._progress.visible = False
        if self.page:
            self.update()
        suggestions = result.get("items", []) if isinstance(result, dict) else []
        added = 0
        for s in suggestions:
            txn_id = s.get("transaction_id")
            # Don't clobber a row the user already picked or already has
            # an unreviewed suggestion on.
            if txn_id is None or txn_id in self._pending or txn_id in self._suggested:
                continue
            self._suggested[txn_id] = (s["category_id"], s.get("category_name") or "")
            added += 1
        scoped_note = f" from {len(scope):,} selected" if scope else ""
        SuccessSnackBar(
            f"{added} suggestion{'s' if added != 1 else ''} ready to review"
            f"{scoped_note}."
            if added
            else "No new suggestions - nothing had a clear category precedent yet."
        ).launch(self.page)
        self._selected.clear()
        # A real rebuild here on purpose (unlike a single accept/reject):
        # this is what re-sorts newly-suggested rows to the top, the
        # whole point of clicking this button being able to review what
        # it proposed without hunting for it in 900 date-sorted rows.
        # Tried skipping this for speed (in-place per-cell updates,
        # keeping rows in place) - lost the grouping, which mattered
        # more than the speed here. Reverted.
        self._render_table()

    async def _save_pending(self) -> None:
        if not self._pending:
            return
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        to_save = list(self._pending.items())
        saved_ids = await apply_category_picks(api, to_save)
        failed = len(to_save) - len(saved_ids)
        message = (
            f"Saved {len(saved_ids)}."
            if not failed
            else f"Saved {len(saved_ids)}, {failed} failed."
        )
        (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)

        # A saved row disappears immediately - tried leaving it visible
        # with a "Saved" confirmation to skip the rebuild below entirely,
        # but that's not what was wanted: hitting Save should remove the
        # row, not leave it lingering until the next reload. Reverted.
        #
        # Still no re-``GET /uncategorized`` though - the POST results
        # above already say exactly which rows just left the backlog, so
        # splicing locally and rebuilding once (no network round trip)
        # is the honest middle ground: correct behavior, still cheaper
        # than the original refetch-then-rebuild.
        saved = set(saved_ids)
        for transaction_id, _ in to_save:
            self._pending.pop(transaction_id, None)
        if saved:
            self._items = [t for t in self._items if t["id"] not in saved]
            self._selected -= saved
            self._total = max(self._total - len(saved), 0)
        self._render_table()
