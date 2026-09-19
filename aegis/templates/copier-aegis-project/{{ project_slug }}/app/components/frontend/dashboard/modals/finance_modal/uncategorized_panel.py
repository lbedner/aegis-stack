"""The uncategorized-transactions work queue."""

from collections.abc import Callable

import flet as ft

from app.components.frontend.controls import (
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
)

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
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    TagApplyMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import (
    AccountFilter,
    AccountFilterButton,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_cells import (
    CategoryCellMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_data import (
    UncategorizedTableMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_staging import (
    CategoryStagingMixin,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
)
from app.components.frontend.theme import AegisTheme as Theme


class UncategorizedPanel(
    UncategorizedTableMixin,
    CategoryCellMixin,
    CategoryStagingMixin,
    TagApplyMixin,
    FinancePanel,
):
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
