"""The Bills & Income tab core: load, filters, render, sub-tabs."""

from __future__ import annotations

from datetime import date
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BaseIconButton,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.debounce import Debouncer
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.pickers import (
    BulkActionTrigger,
    CategoryPickerButton,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.modals.finance_recurring_tab.actions import (
    StreamActionsMixin,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.base import (
    RecurringTabState,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.dialogs import (
    StreamDialogsMixin,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.editor import (
    StreamEditorMixin,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.rows import (
    RowsMixin,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.shared import (
    _RECURRING_URL,
    _is_curated,
    _usd,
    needs_review,
)
from app.components.frontend.dashboard.modals.modal_sections import DateRangeChips
from app.components.frontend.theme import AegisTheme as Theme


class RecurringTab(
    RowsMixin,
    StreamActionsMixin,
    StreamDialogsMixin,
    StreamEditorMixin,
    RecurringTabState,
):
    """Bills & Income: two tables (income, bills) plus Add and curation."""

    def __init__(
        self,
        page: ft.Page,
        account_filter: Any = None,
        register_filter_listener: Any = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener, expand=True)
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._monthly = SecondaryText("")
        self._body = ft.Container(expand=True)
        self._subtab_index = 0
        # Per-render lazy cache (switching Bills -> Income -> Bills within
        # one load/filter cycle doesn't rebuild a table it already has) -
        # reset fresh in _render(), same lifetime the old per-tab-holder
        # version had. Sub-tab CONTENT lives in self._body now, separate
        # from self._tabs (the header strip) below - a Flet ft.Tab with no
        # ``content`` renders as header-only, which is what lets the strip
        # sit in the same row as search/range instead of owning the full
        # width for its (nonexistent) TabBarView.
        self._holders: list[ft.Control | None] = [None, None, None]
        self._partitions: list[tuple[str, list[dict]]] = []
        self._tabs = PulseTabs(
            tabs=[ft.Tab(text="Bills"), ft.Tab(text="Income"), ft.Tab(text="Detected")],
            selected_index=0,
            expand=False,
            on_change=self._on_subtab_change,
        )
        # The full unfiltered fetch - search/range are applied locally
        # against this on every keystroke/chip click, no re-fetch. Bills &
        # Income tops out at a few hundred streams (unlike the transaction
        # register, which can run to thousands), so there's no need for
        # the server-side q/date-range plumbing TransactionsPanel and
        # UncategorizedPanel have - filtering an already-loaded list of
        # this size is effectively instant either way.
        self._items: list[dict] = []
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
        # Filters by last_date (last actual matching transaction), same as
        # every other DateRangeChips in this app filtering "how far back
        # to look" by activity - NOT by next_expected_date, which would
        # read as a forward-looking due-date planner instead.
        #
        # Defaults to 1y, not "All". The first version defaulted to All on
        # the theory that a narrower default might hide a real bill, with
        # the staleness dot left to mark the dead ones. Real data says
        # otherwise: 219 of 359 streams last matched over a YEAR ago (134
        # over two), so "All" opens Detected on a majority of 2023-era
        # noise - one-off ATM withdrawals and restaurants the cadence
        # detector found a rhythm in. A bill you actually pay has matched
        # within the year by definition; anything older is history, and
        # "All" is one click away when you want it.
        self._range_days = 365
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
        # Checkbox selection, by STREAM ID rather than row index: the table
        # sorts internally and rebuilds on every filter change, so an index
        # would point at whatever row later lands in that slot.
        self._selected: set[int] = set()
        self._selection_label = SecondaryText("", visible=False)
        # Category options, fetched once - the edit/add dialogs and the
        # bulk picker all read this list.
        # For the account dropdown in both dialogs. A bill with no
        # account cannot reach the forecast, so this is worth offering at
        # creation as well as after the fact.
        self._accounts: list[tuple[str, str]] = []
        self._categories: list[tuple[str, str]] = []
        self._category_picker = CategoryPickerButton(
            categories=self._categories, on_pick=self._pick_category
        )
        self._categorize_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_categorize,
            tooltip="Set the category on every checked bill at once",
        )
        self._mute_button = PulseButton(
            on_click_callable=self._bulk_mute,
            text="Mute",
            variant="muted",
            compact=True,
        )
        self._mute_button.tooltip = "Silence insights for the checked rows"
        self._pause_button = PulseButton(
            on_click_callable=self._bulk_pause,
            text="Pause",
            variant="muted",
            compact=True,
        )
        self._pause_button.tooltip = (
            "Pause the checked rows until a date - out of the forecast "
            "and totals, back on their own after"
        )
        self._delete_button = PulseButton(
            on_click_callable=self._bulk_delete,
            text="Delete",
            variant="stop",
            compact=True,
        )
        self._delete_button.tooltip = "Remove the checked rows from Bills & Income"
        # Set through _update_selection rather than a visible=False kwarg:
        # PulseButton accepts **kwargs but never forwards them to the Flet
        # control (BaseElevatedButton calls super().__init__() with no
        # arguments and stashes kwargs on self.kwargs), so the flag was
        # inert and both buttons showed with nothing selected. Going
        # through the same method every later change uses also means there
        # is one definition of "what these look like for N selected".
        self._update_selection()
        # Indeterminate: bulk mute/delete is one request PER stream (the
        # API is per-id), so there IS a real fraction here - but the work
        # is short and a looping bar avoids implying precision about
        # requests that can fail individually.
        self._progress = ft.ProgressBar(
            value=None,
            color=Theme.Colors.ACCENT,
            bgcolor=ft.Colors.with_opacity(0.15, Theme.Colors.ACCENT),
            visible=False,
        )
        add_button = PulseButton(
            on_click_callable=self._open_add,
            text="Add",
            variant="teal",
            compact=True,
        )
        add_button.tooltip = "Declare a bill or income the detector cannot see"
        # One reconciliation session over every overdue bill, instead of
        # find-click-close per row. Hidden until something is overdue;
        # _render keeps the count honest on every reload.
        self._review_button = PulseButton(
            on_click_callable=self._open_review_queue,
            text="Review",
            variant="teal",
            compact=True,
        )
        self._review_button.tooltip = (
            "Step through each overdue bill's likely payments"
        )
        self._review_button.visible = False
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        H3Text("Bills & Income"),
                        self._monthly,
                        ft.Container(
                            content=self._progress,
                            expand=True,
                            alignment=ft.alignment.center,
                        ),
                        self._selection_label,
                        self._categorize_trigger,
                        self._mute_button,
                        self._pause_button,
                        self._delete_button,
                        self._review_button,
                        add_button,
                        BaseIconButton(
                            self._rescan,
                            icon=ft.Icons.MANAGE_SEARCH,
                            icon_size=18,
                            tooltip=(
                                "Re-scan for bills - picks up payees you have "
                                "named since the last scan"
                            ),
                        ),
                        BaseIconButton(
                            self._load,
                            icon=ft.Icons.REFRESH,
                            icon_size=18,
                            tooltip="Refresh",
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.MD,
                ),
                ft.Row(
                    [self._tabs, ft.Container(expand=True), self._search, self._range],
                    spacing=Theme.Spacing.MD,
                    # END, not CENTER: _search is a FormTextField (a label
                    # above the input) - see TransactionsPanel/
                    # UncategorizedPanel for the same reasoning.
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                self._body,
                # Zero-size mount point for the picker's own overlay - a
                # SearchPickerButton builds its popup from wherever it is
                # mounted, so it has to be in the tree even though it
                # renders nothing here (see its docstring).
                self._category_picker,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    # -- data --------------------------------------------------------------

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        if not self._categories:
            from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES

            cat_data = await api.get("/api/v1/finance/categories/options")
            cat_items = cat_data.get("items", []) if isinstance(cat_data, dict) else []
            self._categories = [
                (str(c["id"]), c["name"])
                for c in cat_items
                if str(c.get("name", "")).lower() not in UNCATEGORIZED_CATEGORY_NAMES
            ]
            self._category_picker.update_categories(self._categories)
        if not self._accounts:
            accounts = await api.get(
                "/api/v1/finance/accounts", params={"page_size": 200}
            )
            self._accounts = [
                (str(a["id"]), a.get("name", "Account"))
                for a in (
                    accounts.get("items", []) if isinstance(accounts, dict) else []
                )
            ]
        data = await api.get(_RECURRING_URL)
        self._items = data.get("items", []) if isinstance(data, dict) else []
        # monthly_cost is a fact about the whole backlog (the rollup over
        # every commitment), not the current search/date-range VIEW of it
        # - set once per fetch, untouched by _render() so it doesn't
        # flicker as you type.
        monthly = data.get("monthly_cost", 0) if isinstance(data, dict) else 0
        self._monthly.value = (
            f"about {_usd(monthly)}/month in recurring bills" if monthly else ""
        )
        self._render()
        if self._monthly.page is not None:
            self._monthly.update()

    def _on_account_filter_change(self) -> None:
        # Local-refilter override: the fetch already holds every
        # account's streams, so a narrower filter re-renders the
        # cached list instead of refetching (see _filtered_items).
        self._render()

    async def _apply_filters(self) -> None:
        """Debouncer trampoline - _render() itself is synchronous (no
        re-fetch), but schedule()/run_now() both need an async callable."""
        self._render()

    def _on_search_change(self, event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        self._query = (getattr(control, "value", "") or "").strip()
        self._debounce.schedule(self._apply_filters)

    def _on_search_submit(self, event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        self._query = (getattr(control, "value", "") or "").strip()
        self._debounce.run_now(self._apply_filters)

    def _on_range_change(self, days: int) -> None:
        self._range_days = days
        self._debounce.run_now(self._apply_filters)

    def _render(self) -> None:
        items = self._filtered_items()

        # Bills and Income both hold CURATED rows only - anything the
        # detector merely guessed waits in Detected until approved.
        #
        # Income used to show every inflow on the theory that income
        # guesses are "few and high-signal (paychecks, not shopping
        # habits)". They are not: on real data 9 of 10 detected inflows
        # were credit-card payments posting as credits, transfers between
        # the user's own accounts, the same pension under two descriptors,
        # and a $0.31 dividend. Showing those as income inflates the
        # forecast with money nobody receives, and buries the two streams
        # the user actually set up.
        #
        # Detected = unapproved proposals in BOTH directions + anything
        # muted, so Unmute stays reachable. Selection survives a reload.
        bills = [
            s
            for s in items
            if s.get("direction") == "outflow"
            and _is_curated(s)
            and not s.get("is_muted")
        ]
        income = [
            s
            for s in items
            if s.get("direction") == "inflow"
            and _is_curated(s)
            and not s.get("is_muted")
        ]
        placed = {id(s) for s in bills} | {id(s) for s in income}
        detected = [s for s in items if id(s) not in placed]

        # Lazy sub-tabs: only the visible tab's table is BUILT (hundreds of
        # rows x buttons serialize over the websocket - constructing all
        # three per load is what made this tab feel slow; the API itself
        # answers in ~10ms). The others build on first visit - see
        # _show_subtab.
        due = [s for s in items if needs_review(s, date.today().isoformat())]
        # .text is a dead store after construction (BaseElevatedButton
        # renders a content Text built in __init__) - the label lives in
        # content.value.
        if isinstance(self._review_button.content, ft.Text):
            self._review_button.content.value = f"Review ({len(due)})"
        self._review_button.visible = bool(due)
        if self._review_button.page is not None:
            self._review_button.update()
        self._partitions = [
            (f"Bills ({len(bills)})", bills),
            (f"Income ({len(income)})", income),
            (f"Detected ({len(detected)})", detected),
        ]
        self._holders = [None, None, None]
        for tab, (label, _) in zip(self._tabs.tabs, self._partitions):
            tab.text = label
        if self._tabs.page is not None:
            self._tabs.update()
        self._show_subtab(self._subtab_index)

    def _show_subtab(self, index: int) -> None:
        holder = self._holders[index]
        if holder is None:
            holder = self._table(self._partitions[index][1])
            self._holders[index] = holder
        self._body.content = holder
        if self._body.page is not None:
            self._body.update()

    def _on_subtab_change(self, event: ft.ControlEvent) -> None:
        self._subtab_index = int(event.control.selected_index or 0)
        # Selection is per sub-tab: the ids checked on Bills aren't on
        # screen once Detected is showing, so keeping them would leave
        # "12 selected" (and an armed Delete) pointing at rows the user
        # can no longer see.
        self._selected.clear()
        self._update_selection()
        self._show_subtab(self._subtab_index)

    def _update_selection(self) -> None:
        count = len(self._selected)
        self._selection_label.value = f"{count} selected" if count else ""
        self._selection_label.visible = bool(count)
        self._mute_button.visible = bool(count)
        self._pause_button.visible = bool(count)
        self._delete_button.visible = bool(count)
        self._mute_button.text = f"Mute ({count})" if count else "Mute"
        self._pause_button.text = f"Pause ({count})" if count else "Pause"
        self._delete_button.text = f"Delete ({count})" if count else "Delete"
        self._categorize_trigger.set_count(count)
        for control in (
            self._selection_label,
            self._mute_button,
            self._pause_button,
            self._delete_button,
        ):
            if control.page:
                control.update()
