"""The panel for transactions that arrived without a payee."""

from collections.abc import Callable

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.debounce import Debouncer
from app.components.frontend.controls.form_fields import (
    FormTextField,
)
from app.components.frontend.controls.pickers import (
    BulkActionTrigger,
    MerchantPickerButton,
    TagPickerButton,
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
    _DENSE_ROW_HEIGHT,
    _NO_PAYEE_PAGE_SIZE,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    TagApplyMixin,
    _group_columns,
    _group_rows,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import AccountFilter
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
)
from app.components.frontend.dashboard.modals.finance_modal.no_payee_assign import (
    PayeeAssignMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    _transaction_expanded_content,
    fetch_tag_options,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.dashboard.modals.modal_sections import (
    date_cell,
)
from app.components.frontend.theme import AegisTheme as Theme


class NoPayeePanel(PayeeAssignMixin, TagApplyMixin, FinancePanel):
    """A work queue for transactions nobody has named a payee for.

    Deliberately leaner than ``UncategorizedPanel``: there is no
    pending/Save staging and no per-row suggestion to accept or reject,
    because a payee has no equivalent of the categorizer's guess - either
    you have told the app who this is or you haven't. Assign applies
    immediately, the same way the register's payee cell does.

    It also skips the register's "also apply to N similar" sweep on
    purpose: in a queue that is BY DEFINITION the unnamed rows, searching
    a payee and bulk-selecting the matches IS that sweep, done with your
    eyes on the actual list instead of a heuristic's guess at it.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener)
        self._items: list[dict] = []
        # Server-reported total, which is NOT len(self._items): this queue
        # starts in the tens of thousands on a real import, so the table
        # shows a bounded page and the header states the honest number.
        self._total = 0
        # "groups" collapses the backlog by payee key so one decision
        # settles a thousand rows; "rows" is the raw list for the cases
        # where you need to see individual transactions.
        self._mode = "groups"
        self._groups: list[dict] = []
        self._active_group: dict | None = None
        self._merchants: list[tuple[str, str]] = []
        self._account_names: dict[int, str] = {}
        self._selected: set[int] = set()
        # Group mode selects KEYS, not row ids - a group is a descriptor
        # shape, not a transaction. Kept separate from ``_selected`` rather
        # than overloaded, because the two modes act through different
        # endpoints (ids -> assign-merchant, keys -> payee-groups/assign).
        self._selected_keys: set[str] = set()
        self._group_total = 0
        self._group_txn_total = 0
        self._query = ""
        self._debounce = Debouncer(page)
        self._header = SecondaryText("Loading…")
        self._body = ft.Container()
        self._search = FormTextField(
            label="Search payee",
            on_change=self._on_search_change,
            on_submit=self._on_search_submit,
            width=280,
            compact=True,
            clearable=True,
        )
        self._merchant_picker = MerchantPickerButton(
            merchants=self._merchants,
            on_pick=self._pick_merchant,
            on_create=self._create_merchant,
        )
        self._selection_label = SecondaryText("", visible=False)
        self._bulk_trigger = BulkActionTrigger(
            on_tap=self._open_bulk,
            label="Set payee",
            tooltip="Assign the same payee to every checked row at once",
        )
        self._tags: list[tuple[str, str]] = []
        self._tag_picker = TagPickerButton(
            tags=self._tags,
            on_pick=self._apply_tag,
            on_create=self._apply_tag,
        )
        self._bulk_tag_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_tag,
            label="Tag",
            tooltip="Put a tag on every checked row at once",
        )
        self._mode_button = PulseButton(
            on_click_callable=self._toggle_mode,
            text="View rows",
            variant="muted",
            compact=True,
        )
        # Indeterminate (value=None -> looping, not a fake percentage):
        # naming a group is ONE request/response, so there's no honest
        # fraction to report - the work is a single server-side UPDATE
        # over rows the client never sees. Same treatment (and same
        # reasoning) as Auto-categorize on the Uncategorized queue.
        self._progress = ft.ProgressBar(
            value=None,
            color=Theme.Colors.ACCENT,
            bgcolor=ft.Colors.with_opacity(0.15, Theme.Colors.ACCENT),
            visible=False,
        )
        self.content = ft.Column(
            [
                self._header,
                ft.Row(
                    [
                        self._search,
                        # A Container, not the bar itself: it keeps claiming
                        # this flex space regardless of visible=True/False,
                        # so the controls to its right don't jump sideways
                        # when the bar appears.
                        ft.Container(
                            content=self._progress,
                            expand=True,
                            alignment=ft.alignment.center,
                        ),
                        self._selection_label,
                        self._bulk_trigger,
                        self._bulk_tag_trigger,
                        self._mode_button,
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                self._body,
                self._merchant_picker,
                self._tag_picker,
            ],
            spacing=Theme.Spacing.MD,
            tight=True,
        )

    def refresh(self) -> None:
        if self.page:
            self.page.run_task(self._load)

    def _on_account_filter_change(self) -> None:
        # Debounced override: a rapid filter toggle must coalesce
        # into one refetch of a queue this large.
        self._debounce.run_now(self._load)

    def _on_search_change(self, event: ft.ControlEvent) -> None:
        self._query = (getattr(event.control, "value", "") or "").strip()
        self._debounce.schedule(self._load)

    def _on_search_submit(self, event: ft.ControlEvent) -> None:
        self._query = (getattr(event.control, "value", "") or "").strip()
        self._debounce.run_now(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._selected.clear()
        self._update_selection_label()
        self._set_busy(True)
        merchants = await api.get("/api/v1/finance/merchants", cache_ttl=30)
        items = merchants.get("items", []) if isinstance(merchants, dict) else []
        self._merchants = [(str(m["id"]), m["name"]) for m in items]
        self._merchant_picker.update_merchants(self._merchants)
        self._tags = await fetch_tag_options(api)
        self._tag_picker.update_tags(self._tags)
        if not self._account_names:
            accounts = await api.get(
                "/api/v1/finance/accounts",
                params={"page_size": 200},
                cache_ttl=30,
            )
            self._account_names = {
                a["id"]: a.get("name", "Account")
                for a in (
                    accounts.get("items", []) if isinstance(accounts, dict) else []
                )
            }

        if self._account_filter.is_empty:
            self._items, self._total = [], 0
        else:
            params: dict[str, object] = {
                "without_merchant": True,
                "page_size": _NO_PAYEE_PAGE_SIZE,
                **self._account_filter.params(),
            }
            if self._query:
                params["q"] = self._query
            data = await api.get("/api/v1/finance/transactions", params=params)
            self._items = data.get("items", []) if isinstance(data, dict) else []
            self._total = (
                data.get("total", len(self._items))
                if isinstance(data, dict)
                else len(self._items)
            )
            groups = await api.get(
                "/api/v1/finance/payee-groups", params={"limit": 300}
            )
            self._groups = groups.get("items", []) if isinstance(groups, dict) else []
            # Totals for the WHOLE backlog, not this page - the header used
            # to report len(self._groups), which is just the limit above.
            self._group_total = (
                groups.get("total", len(self._groups))
                if isinstance(groups, dict)
                else 0
            )
            self._group_txn_total = (
                groups.get("total_transactions", 0) if isinstance(groups, dict) else 0
            )
        self._set_busy(False)
        self._render()

    def _render(self) -> None:
        self._mode_button.text = (
            "View rows" if self._mode == "groups" else "View groups"
        )
        if self._mode_button.page:
            self._mode_button.update()
        if self._mode == "groups":
            self._render_groups()
            return
        shown, total = len(self._items), self._total
        if not total:
            self._header.value = (
                "No matches." if self._query else "Every transaction has a payee."
            )
        elif shown < total:
            self._header.value = (
                f"{total:,} transactions with no payee · showing the first "
                f"{shown:,}. Search a payee to narrow it down."
            )
        else:
            self._header.value = (
                f"{total:,} transaction{'s' if total != 1 else ''} with no payee"
            )
        columns = [
            DataTableColumn("Date", width=110),
            DataTableColumn("Account", width=200, style="secondary"),
            DataTableColumn("Payee", hideable=False),
            DataTableColumn("Amount", width=130, alignment="right"),
        ]
        rows = [
            [
                date_cell(t.get("date")),
                TableCellText(self._account_names.get(t.get("account_id"), "—")),
                TableNameText(t.get("name") or ""),
                _amount_cell(t.get("amount", 0)),
            ]
            for t in self._items
        ]

        def _on_selection(indices: set[int]) -> None:
            self._selected = {
                self._items[i]["id"] for i in indices if i < len(self._items)
            }
            self._update_selection_label()

        def _expand(idx: int) -> ft.Control:
            return _transaction_expanded_content(self._items[idx])

        self._body.content = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            scroll_height=560,
            selectable=True,
            on_selection_change=_on_selection,
            expandable_content=_expand,
            empty_message="Nothing left without a payee.",
        )
        if self.page:
            self.update()

    def _set_busy(self, busy: bool) -> None:
        """Show the working indicator. Covers the whole cycle - the write
        AND the reload behind it - because on this queue the reload is the
        slower half (it re-reads every payee-less row to rebuild the
        groups), and a bar that stops before the list refreshes would be
        lying about when the work is done."""
        self._progress.visible = busy
        if self._progress.page:
            self._progress.update()

    def _toggle_mode(self) -> None:
        self._mode = "rows" if self._mode == "groups" else "groups"
        self._selected.clear()
        self._selected_keys.clear()
        self._update_selection_label()
        self._render()

    def _render_groups(self) -> None:
        query = self._query.casefold()
        # Match the SAMPLE as well as the key: the key is the normalized
        # first few tokens, so searching "door" against keys alone misses
        # "BT*DD *DOORDASH ..." and "VENMO *DOORDASH ..." - exactly the
        # variants a brand sweep is trying to round up.
        groups = [
            g
            for g in self._groups
            if not query
            or query in g.get("key", "").casefold()
            or query in (g.get("sample") or "").casefold()
        ]
        covered = sum(g.get("count", 0) for g in groups)
        self._header.value = self._groups_header(len(groups), covered)
        columns = _group_columns()
        rows = _group_rows(groups)

        def _open_group(idx: int, _groups: list = groups) -> None:
            self._open_group_dialog([_groups[idx]])

        def _on_selection(indices: set[int], _groups: list = groups) -> None:
            self._selected_keys = {
                _groups[i].get("key", "") for i in indices if i < len(_groups)
            } - {""}
            self._update_selection_label()

        # Re-check whatever is still on screen after a re-render (a search
        # narrows the list; the boxes you already ticked should survive it).
        keep = [
            i for i, g in enumerate(groups) if g.get("key", "") in self._selected_keys
        ]
        self._body.content = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            scroll_height=560,
            selectable=True,
            selected_indices=keep,
            on_selection_change=_on_selection,
            on_row_click=_open_group,
            empty_message="Nothing left without a payee.",
        )
        if self.page:
            self.update()

    def _groups_header(self, shown: int, covered: int) -> str:
        """Say what is actually true about the backlog.

        This line used to read "{transactions} with no payee, in {groups}
        groups" from two different populations: the transaction count came
        from /transactions (narrowed by the account filter AND the search
        box) while the group count was len(page) - i.e. the request limit,
        reporting "300 groups" when there were 2,436. Both numbers now come
        from /payee-groups, which counts the whole backlog.
        """
        if not self._groups:
            return "Every transaction has a payee."
        total_groups = self._group_total or len(self._groups)
        line = f"{self._group_txn_total:,} with no payee, in {total_groups:,} groups."
        if shown < total_groups:
            line += f" Showing {shown:,}, settling {covered:,}."
        else:
            line += f" Naming them all settles {covered:,}."
        return line

    def _update_selection_label(self) -> None:
        # Both modes select; they just select different things. Rows count
        # transactions, groups count groups - and the label says which, so
        # "12 selected" can't be misread as 12 transactions when it is 12
        # descriptor shapes covering hundreds.
        if self._mode == "rows":
            count = len(self._selected)
            label = f"{count} selected"
        else:
            count = len(self._selected_keys)
            covered = sum(
                g.get("count", 0)
                for g in self._groups
                if g.get("key", "") in self._selected_keys
            )
            label = f"{count:,} groups · {covered:,} transactions"
        self._selection_label.value = label if count else ""
        self._selection_label.visible = bool(count)
        if self._selection_label.page:
            self._selection_label.update()
        self._bulk_trigger.set_count(count)
        self._bulk_tag_trigger.set_count(count if self._mode == "rows" else 0)

    def _open_bulk_tag(self, e: ft.ControlEvent) -> None:
        # Rows mode only: a group selection is descriptor KEYS, not
        # transaction ids, and the tag endpoint speaks ids.
        if self._mode == "rows" and self._selected:
            self._tag_picker.open_for(list(self._selected), e)

    def _open_bulk(self, e: ft.ControlEvent) -> None:
        if self._mode == "rows":
            if self._selected:
                self._merchant_picker.open_for(list(self._selected), e)
            return
        # Groups go through the dialog, not the anchored picker: this can
        # settle thousands of transactions in one click, and the dialog is
        # where naming a NEW payee (with an optional website for the logo)
        # lives. Same reasoning as the single-group row click.
        selected = [g for g in self._groups if g.get("key", "") in self._selected_keys]
        if selected:
            self._open_group_dialog(selected)
