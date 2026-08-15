"""The Bills & Income tab: recurring commitments, declared and detected.

One surface over ``finance_recurring_stream``: income (inflow) and bills
(outflow), whether hand-entered ("Add" here, ``source="user"``) or found
by the detector. Curation lives on the rows - Confirm promotes a detected
rhythm into a commitment the missed-payment rule chases; Mute silences a
stream's insights. Detection cannot see a bill that predates the imported
history or is paid outside these accounts; that is what manual entry is for.
"""

from datetime import date, timedelta
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import ConfirmDialog, PulseButton
from app.components.frontend.controls.data_table import DataTable, DataTableColumn
from app.components.frontend.controls.debounce import Debouncer
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDateField,
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.pickers import (
    BulkActionTrigger,
    CategoryPickerButton,
    CategoryPickerField,
)
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.modals.modal_sections import (
    ChartColors,
    DateRangeChips,
    EmptyStatePlaceholder,
    LineChartCard,
    LineSeries,
    chart_floor,
    date_cell,
    headline_stat,
    headline_stat_color,
    ledger_amount_color,
    row_matches,
    status_dot,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date

from .finance_modal import (
    BILL_FREQUENCY_OPTIONS,
    FinancePanel,
    _category_leaf,
    _frequency_label,
)

_RECURRING_URL = "/api/v1/finance/recurring"


# Name is the width-less column: it absorbs whatever the modal has left,
# so the table fills its panel instead of stranding empty space rightward.
# An Actions column is appended per-table, only when a row has a verb to
# offer (Confirm, on unapproved outflows) - Bills and Income have none.
# Health (staleness) is always shown, unlike the curation-state Status
# column appended below - it's a second, separate signal (still real vs.
# gone quiet), not a replacement for it.
_COLUMNS = [
    DataTableColumn("Name", style="body", hideable=False),
    DataTableColumn("Category", width=150, style="secondary"),
    DataTableColumn("Account", width=150, style="secondary"),
    DataTableColumn("Amount", width=110, alignment="right", style="secondary"),
    DataTableColumn("Cadence", width=160, style="secondary"),
    DataTableColumn("Next due", width=110, style="secondary"),
    DataTableColumn("Health", width=100),
]
_NEXT_DUE_COLUMN = 5
# ASCENDING: this page answers "what is coming up", so the first row has
# to be the next thing due. Descending put the furthest-away bill at the
# top and the one due tomorrow below the fold. Blanks are unaffected -
# DataTable's type-ranked key sorts them last either way, which is where
# a bill with no due date belongs on a list about what is next.
_NEXT_DUE_SORT_DESC = False

# staleness (backend, stream_staleness) -> (label, color, tooltip-body).
# Mirrors the exact recency signal _missed_recurring already uses to
# decide whether a bill is genuinely overdue vs. a zombie out of imported
# history - this just surfaces it per-row instead of a hidden insight.
_HEALTH_STYLE: dict[str, tuple[str, str, str]] = {
    "fresh": (
        "Active",
        Theme.Colors.SUCCESS,
        "Matched recently and on cadence.",
    ),
    "overdue": (
        "Overdue",
        Theme.Colors.WARNING,
        "Past due beyond the grace window - hasn't arrived yet.",
    ),
    "stale": (
        "Stale",
        Theme.Colors.ERROR,
        "Last matched before the lookback window - probably not a live bill anymore.",
    ),
}


def _parse_dollars(text: str) -> int:
    """Dollars string -> integer cents. Tolerates ``$``, commas, and blanks."""
    cleaned = (text or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return 0


def _usd(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.2f}"


def _usd_signed(cents: int, *, plus: bool = False) -> str:
    """Signed money: ``-$115.35``, and ``+$1,200.00`` when ``plus`` is on."""
    sign = "-" if cents < 0 else ("+" if plus else "")
    return f"{sign}{_usd(abs(cents))}"


def _is_curated(stream: dict) -> bool:
    """A stream the user personally vouched for - THE RECORD.

    ``is_subscription`` no longer counts: it is the detector's own guess
    (plus the Quicken-category promote pass), and honouring it here put
    71 rows nobody confirmed into Bills - which is how a 2019 Capital One
    auto-payment sat in the user's "real bills" charging the forecast.
    Bills/Income = what you set. Everything else waits in Detected for
    the Confirm that is now the single door in.
    """
    return bool(stream.get("source") == "user" or stream.get("is_user_confirmed"))


def pause_options(today: date) -> list[tuple[str, date]]:
    """The pause dialog's quick picks, as real calendar months.

    ``add_months`` (the cadence engine's own stepper) rather than day
    arithmetic: "3 months" from Aug 9 is Nov 9, and from Aug 31 it clamps
    to the shorter month instead of drifting into the next one.
    """
    from app.services.finance.constants import add_months

    return [
        (f"{n} month{'s' if n > 1 else ''}", add_months(today, n)) for n in (1, 2, 3, 6)
    ]


def pause_label(until_iso: str) -> str:
    """ "until Nov 9" or "indefinitely" - the year 9999 is an
    implementation detail nobody should ever read."""
    from app.services.finance.constants import PAUSE_INDEFINITE

    if date.fromisoformat(str(until_iso)) >= PAUSE_INDEFINITE:
        return "indefinitely"
    return f"until {until_iso}"


def stream_is_paused(stream: dict) -> bool:
    """The frontend half of ``is_paused``: same lazy comparison, read off
    the response dict."""
    until = stream.get("paused_until")
    if not until:
        return False
    return date.today() < date.fromisoformat(str(until))


def _status_key(stream: dict) -> str:
    """The status a row WOULD show. Used to decide whether the Status
    column earns its place: on a tab where every row reads the same, the
    column is 88 copies of a word the tab title already said."""
    if stream.get("is_muted"):
        return "muted"
    if stream_is_paused(stream):
        return "paused"
    if stream.get("is_payment"):
        return "payment"
    if stream.get("direction") == "inflow":
        return "income"
    if _is_curated(stream):
        return "good"
    return "detected"


def projection_columns() -> list[DataTableColumn]:
    """The projection ledger's columns: Date, Name, Amount, Balance.

    Category and Account ship hidden (one click away in the picker).
    That is a WIDTH budget, not a taste call: the ledger gets 9/20 of
    the modal, ~565px on a small laptop, and a flex column gets only
    what the fixed ones leave. With Category visible the fixed widths
    plus the picker gutter and spacing overflowed that share, so the one
    flex column - Name, the identity column - silently rendered at ZERO
    width and the ledger showed category strings where bill names
    belong. Confirmed live at 1459px; the control tree looks correct the
    whole time, which is why only the width-budget test can hold the
    line. (``build_cell``'s docstring records the same collapse shipping
    twice before in other tables.)
    """
    # Widths sized to their real content ("Aug 15, 2026", "-$14,349.00"),
    # not round numbers - every spare pixel here is Name width.
    return [
        DataTableColumn("Date", width=100, style="secondary"),
        DataTableColumn("Name", style="body", hideable=False),
        DataTableColumn("Category", width=170, style="secondary", visible=False),
        DataTableColumn("Account", width=170, style="secondary", visible=False),
        DataTableColumn("Amount", width=110, alignment="right"),
        DataTableColumn("Balance", width=120, alignment="right"),
    ]


def projection_layout(chart: ft.Control, table: ft.Control) -> ft.Row:
    """Chart beside the ledger, not above it.

    Stacked, the chart ate the height and left the ledger ~4 visible
    rows. The two halves answer one question together - the line says
    WHEN the balance turns, the rows say WHAT turns it - so they share
    the width rather than hiding one behind a sub-tab. The chart keeps
    the wider share (a compressed date axis stops being readable before
    a table does); the ledger gets the full tab height.

    ``expand=True`` on the Row is load-bearing, not styling: STRETCH
    against an unbounded parent renders NOTHING in Flet's release build
    (the import-review dialog shipped exactly that bug).
    """
    return ft.Row(
        [
            ft.Container(content=chart, expand=11),
            ft.Container(content=table, expand=9),
        ],
        spacing=Theme.Spacing.MD,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        expand=True,
    )


class ProjectionPanel(FinancePanel):
    """Projected cash balance, the Quicken "Projected Balances" view:
    today's cash balance walked forward through scheduled bills and
    income. Chart on top (the house line-chart card), the occurrence
    ledger underneath with a running balance per row."""

    _RANGES = [
        ("1d", 1),
        ("2d", 2),
        ("7d", 7),
        ("14d", 14),
        ("1m", 30),
        ("3m", 90),
        ("6m", 180),
        ("1y", 365),
    ]

    def __init__(
        self,
        page: ft.Page,
        account_filter: Any = None,
        register_filter_listener: Any = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener, expand=True)
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._days = 180
        self._body = ft.Container(expand=True)
        # The headline figures live bare in the header row (label over
        # number, no card chrome), pinned to the right edge with the
        # range chips to their left - a whole row of cards below cost
        # the chart and ledger a card's height of space.
        self._cards = ft.Row(
            [],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        # The title Column IS the flex child (replacing the
                        # old spacer Container): the subtitle absorbs any
                        # squeeze by ellipsizing, so the chips and headline
                        # figures to its right can never be pushed off the
                        # edge. Same confirmed-live pattern as the register
                        # header (TransactionsPanel's title/subtitle). The
                        # tooltip keeps the full sentence one hover away
                        # when it is truncated.
                        ft.Column(
                            [
                                H3Text("Projected balance"),
                                SecondaryText(
                                    "Every scheduled bill and paycheck applied "
                                    "to today's balance, day by day, so you can "
                                    "see exactly when money gets tight",
                                    no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    tooltip=(
                                        "Every scheduled bill and paycheck "
                                        "applied to today's balance, day by "
                                        "day, so you can see exactly when "
                                        "money gets tight"
                                    ),
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        DateRangeChips(
                            options=self._RANGES,
                            selected_days=self._days,
                            on_change=self._on_range,
                        ),
                        self._cards,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.LG,
                ),
                self._body,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    def _on_range(self, days: int) -> None:
        self._days = days
        if self.page:
            self.page.run_task(self._load)

    async def _load(self) -> None:
        from datetime import date as date_cls
        from datetime import timedelta

        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        if self._account_filter.is_empty:
            # Nothing checked is not the same as no filter - see
            # AccountFilter.params. Skip the fetch rather than send an
            # empty list the server would read as "everything".
            self._body.content = EmptyStatePlaceholder(message="No accounts selected.")
            if self._body.page:
                self._body.update()
            return
        data = await api.get(
            f"{_RECURRING_URL}/projection",
            params={"days": self._days, **self._account_filter.params()},
        )
        if not isinstance(data, dict):
            return
        points = data.get("points", [])
        start = data.get("start_balance", 0)
        end = data.get("end_balance", 0)
        upcoming = data.get("upcoming_total", 0)
        as_of = date_cls.fromisoformat(data.get("as_of", date_cls.today().isoformat()))
        days = data.get("horizon_days", self._days)

        # Only the SIGNED card gets teal. "Upcoming total" is the one
        # rendered with a leading + or -, so it is the one where a
        # positive means "money arriving". The two balance cards are
        # levels, not changes - colouring those too would be the thing
        # headline_stat_color exists to avoid, where every healthy number
        # is tinted and colour stops marking anything.
        def _delta_color(cents: int) -> str:
            if cents < 0:
                return Theme.Colors.ERROR
            return Theme.Colors.SUCCESS if cents > 0 else Theme.Colors.TEXT_PRIMARY

        self._cards.controls = [
            headline_stat(
                "Today's balance", _usd_signed(start), headline_stat_color(start)
            ),
            headline_stat(
                "Upcoming total",
                _usd_signed(upcoming, plus=True),
                _delta_color(upcoming),
            ),
            headline_stat(
                "Projected balance", _usd_signed(end), headline_stat_color(end)
            ),
        ]

        # Daily-resolution walk so the x-axis is time, not event count -
        # a quiet month should read as a long flat stretch.
        by_day: dict[str, list[dict]] = {}
        for point in points:
            by_day.setdefault(str(point.get("date", "")), []).append(point)
        values: list[float] = []
        labels: list[str] = []
        tooltips: list[str] = []
        balance = start
        for offset in range(days + 1):
            key = (as_of + timedelta(days=offset)).isoformat()
            events = by_day.get(key, [])
            if events:
                balance = events[-1].get("balance", balance)
            values.append(balance / 100)
            labels.append(key)
            # Count + total only: a payday can carry a dozen items, and an
            # itemized tooltip that long covers the chart. The ledger below
            # is where the line items live.
            if events:
                day_total = sum(e.get("amount", 0) for e in events)
                summary = (
                    f"{len(events)} transaction{'s' if len(events) != 1 else ''}"
                    f"  {_usd_signed(day_total, plus=True)}"
                )
                tooltips.append(
                    "\n".join([key, summary, f"Balance  {_usd_signed(balance)}"])
                )
            else:
                tooltips.append(f"{key}\nBalance  {_usd_signed(balance)}")
        chart = LineChartCard(
            title="Projected balance",
            subtitle=f"next {days} days · {len(points)} scheduled items",
            # Taller than the stacked default: the chart owns the left
            # column now and a squat line under a tall table reads odd.
            height=420,
            x_labels=labels,
            series=[
                # Polarity on the SEGMENTS, not the whole line: the old
                # treatment coloured everything by where the projection
                # ENDED, so a week underwater mid-window read all-teal and
                # a $10 miss read all-red. Zero is the midpoint that
                # matters, and the days below it are the point of the
                # chart.
                LineSeries(
                    label="Balance",
                    color=Theme.Colors.SUCCESS,
                    points=[(i, v) for i, v in enumerate(values)],
                    tooltips=tooltips,
                    fill=True,
                    stroke_width=3,
                    split_y=0.0,
                    split_below_color=ChartColors.ERROR,
                )
            ],
            min_y=chart_floor(values),
        )

        columns = projection_columns()
        rows = [
            [
                date_cell(p.get("date"), SecondaryText),
                TableNameText(p.get("name") or ""),
                SecondaryText(p.get("category") or "—"),
                SecondaryText(p.get("account") or "—"),
                NumericText(
                    _usd_signed(p.get("amount", 0), plus=True),
                    color=ledger_amount_color(p.get("amount", 0)),
                ),
                NumericText(
                    _usd_signed(p.get("balance", 0)),
                    color=(
                        Theme.Colors.TEXT_PRIMARY
                        if p.get("balance", 0) >= 0
                        else Theme.Colors.ERROR
                    ),
                ),
            ]
            for p in points
        ]
        self._body.content = projection_layout(
            chart,
            DataTable(
                columns=columns,
                rows=rows,
                row_padding=6,
                show_header_border=True,
                show_row_borders=True,
                initial_sort=0,
                column_picker=True,
                empty_message=(
                    "Nothing scheduled in this window. Confirm or "
                    "add bills and income to project them."
                ),
                expand=True,
            ),
        )
        if self._body.page is not None:
            self._body.update()
        if self._cards.page is not None:
            self._cards.update()


class RecurringTab(FinancePanel):
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
                        add_button,
                        ft.IconButton(
                            icon=ft.Icons.MANAGE_SEARCH,
                            icon_color=ft.Colors.ON_SURFACE_VARIANT,
                            icon_size=18,
                            tooltip=(
                                "Re-scan for bills - picks up payees you have "
                                "named since the last scan"
                            ),
                            on_click=lambda e: e.page.run_task(self._rescan),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            icon_color=ft.Colors.ON_SURFACE_VARIANT,
                            icon_size=18,
                            tooltip="Refresh",
                            on_click=lambda e: e.page.run_task(self._load),
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

    def _filtered_items(self) -> list[dict]:
        """Account filter + search + date-range applied to the last fetch
        - see __init__ for why this is local filtering, not a re-fetch."""
        items = [
            s for s in self._items if self._account_filter.allows(s.get("account_id"))
        ]
        if self._query.strip():
            # The same values the row renders - name, category, account,
            # amount, cadence, next due - so "if you can see it, you can
            # search it" (see row_matches).
            items = [
                s
                for s in items
                if row_matches(
                    self._query,
                    (
                        s.get("name"),
                        s.get("category_name"),
                        s.get("account_name"),
                        _usd(s.get("expected_amount") or s.get("average_amount") or 0),
                        _frequency_label(s.get("frequency", "")),
                        format_date(s.get("next_expected_date")),
                    ),
                )
            ]
        if self._range_days < 9000:
            cutoff = date.today() - timedelta(days=self._range_days)

            def _in_range(stream: dict) -> bool:
                last = stream.get("last_date")
                # No activity recorded yet (a just-declared bill) - a date
                # filter has nothing to judge it against, so it stays
                # rather than getting silently dropped.
                return date.fromisoformat(last) >= cutoff if last else True

            items = [s for s in items if _in_range(s)]
        return items

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

    def _table(self, streams: list[dict]) -> ft.Control:
        has_actions = any(
            s.get("direction") == "outflow" and not _is_curated(s) for s in streams
        )
        # Status only when the rows disagree: Bills is every-row "Good" and
        # Income every-row "Good", so the column says nothing the sub-tab
        # has not. Detected mixes Detected with Muted, and there it earns
        # its width.
        has_status = len({_status_key(s) for s in streams}) > 1
        columns = list(_COLUMNS)
        if has_status:
            columns.append(DataTableColumn("Status", width=110))
        if has_actions:
            columns.append(DataTableColumn("Actions", width=110, hideable=False))
        rows = [
            self._row(stream, with_status=has_status, with_actions=has_actions)
            for stream in streams
        ]

        # Row click opens the edit dialog (indices are pre-sort originals).
        # The in-row buttons win their own taps, so Confirm still works.
        def _edit_row(index: int) -> None:
            if self.page:
                self.page.run_task(self._open_edit, streams[index])

        def _on_selection(indices: set[int], _streams: list = streams) -> None:
            self._selected = {
                _streams[i]["id"]
                for i in indices
                if i < len(_streams) and _streams[i].get("id") is not None
            }
            self._update_selection()

        # A selection survives a re-render (a search keystroke, a sub-tab
        # switch back) for any row still on screen - same id-based seeding
        # UncategorizedPanel uses.
        selected_indices = {
            i for i, s in enumerate(streams) if s.get("id") in self._selected
        }

        return ft.Container(
            content=DataTable(
                columns=columns,
                rows=rows,
                row_padding=6,
                show_header_border=True,
                show_row_borders=True,
                on_row_click=_edit_row,
                selectable=True,
                selected_indices=selected_indices,
                on_selection_change=_on_selection,
                initial_sort=_NEXT_DUE_COLUMN,
                initial_sort_desc=_NEXT_DUE_SORT_DESC,
                column_picker=True,
                empty_message="None yet. Add one, or import a file.",
                # Virtualized + fills the tab: detection over a deep import
                # leaves hundreds of streams.
                expand=True,
            ),
            padding=ft.padding.only(top=Theme.Spacing.SM),
            expand=True,
        )

    def _row(
        self,
        stream: dict,
        *,
        with_status: bool = False,
        with_actions: bool = False,
    ) -> list:
        amount = stream.get("expected_amount") or stream.get("average_amount")
        cadence = _frequency_label(stream.get("frequency", ""))
        if stream.get("amount_is_variable"):
            cadence = f"{cadence} · varies"

        # Three states, health-style: green Good (being watched), amber
        # Detected (awaiting your call), gray Muted. WHY a stream is good
        # (income, hand-entered, confirmed, promoted from your categories)
        # lives in the tooltip instead of splintering the label.
        if stream.get("is_muted"):
            status_control = status_dot(
                "Muted",
                Theme.Colors.TEXT_SECONDARY,
                "Silenced. This stream raises no insights until unmuted.",
            )
        elif stream_is_paused(stream):
            until = stream.get("paused_until")
            note = stream.get("pause_note")
            status_control = status_dot(
                "Paused",
                Theme.Colors.TEXT_SECONDARY,
                f"Paused {pause_label(until)}."
                + (f" Why: {note}" if note else "")
                + " Out of the forecast, the Bills total and every nag "
                "until then; back on its own the day the date passes.",
            )
        elif stream.get("is_payment"):
            # A transfer, but a payment FIRST: it drains cash on a rhythm
            # the forecast charges once confirmed, while staying out of
            # the Bills total (the card's swipes already counted there).
            status_control = status_dot(
                "Payment",
                Theme.Colors.ACCENT,
                "A card or loan payment. Confirm it (and pin the amount) "
                "and the cash forecast will charge it; it never counts in "
                "the Bills total, because the card's own charges already "
                "did.",
            )
        elif stream.get("direction") == "inflow":
            # Income needs no curation: the missed-payment rule chases
            # every income stream at any cadence, so "Detected" would be
            # a question with nothing riding on the answer.
            status_control = status_dot(
                "Good",
                Theme.Colors.SUCCESS,
                "Income is always tracked. A missed deposit is flagged "
                "at any cadence, no confirmation needed.",
            )
        elif stream.get("source") == "user":
            status_control = status_dot(
                "Good",
                Theme.Colors.SUCCESS,
                "You added this by hand. It is treated as a real "
                "commitment: missed payments are flagged.",
            )
        elif stream.get("is_user_confirmed"):
            status_control = status_dot(
                "Good",
                Theme.Colors.SUCCESS,
                "You confirmed this is real. Missed payments are flagged "
                "and it counts toward the monthly total.",
            )
        elif stream.get("is_subscription"):
            status_control = status_dot(
                "Good",
                Theme.Colors.SUCCESS,
                "Marked as a bill from your own categorization (or a "
                "recognized subscription). Counts toward the monthly total.",
            )
        else:
            status_control = status_dot(
                "Detected",
                Theme.Colors.WARNING,
                "The cadence detector thinks this repeats and may be a "
                "bill. Confirm to treat it as one, or Mute to dismiss.",
            )

        actions: list[ft.Control] = []
        stream_id = stream.get("id")
        # Confirm is Detected's verb: it promotes an unapproved outflow into
        # a chased commitment. Income is chased unconditionally, and a
        # curated bill is already vouched for - on both, a Confirm button
        # would be a no-op wearing a label.
        if stream.get("direction") == "outflow" and not _is_curated(stream):
            confirm = PulseButton(
                on_click_callable=self._action(stream_id, "confirm"),
                text="Confirm",
                compact=True,
            )
            confirm.tooltip = "Mark as a real bill; missed payments will be flagged"
            actions.append(confirm)
        name = stream.get("name") or ""
        # expand=True on the TEXT, not tight=True on the Row - same
        # truncation recipe _pending_cell already uses below: without it
        # the Row sizes to its children's full natural width (icon + the
        # WHOLE untruncated name) instead of the column's actual width,
        # and a long detected-transaction name (raw bank descriptors run
        # long) paints straight past the Name column into Category
        # (confirmed live from a screenshot - not a hypothetical).
        name_cell = ft.Row(
            [
                ProviderIcon(name, stream.get("icon_b64")),
                ft.Container(content=TableNameText(name), expand=True),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        # DataTable sorts a control cell by its .data (see data_table.py's
        # _cell_text) - a Row has no .value of its own the way the plain
        # TableNameText this replaced did, so Name would silently stop
        # sorting without this.
        name_cell.data = name
        label, color, tooltip = _HEALTH_STYLE.get(
            stream.get("staleness", "fresh"), _HEALTH_STYLE["fresh"]
        )
        if stream.get("staleness") == "stale" and stream.get("last_date"):
            tooltip = f"Last matched {stream['last_date']} - probably not a live bill anymore."
        health_cell = status_dot(label, color, tooltip)
        cells: list = [
            name_cell,
            SecondaryText(_category_leaf(stream.get("category_name") or "") or "—"),
            SecondaryText(stream.get("account_name") or "—"),
            NumericText(_usd(amount), color=Theme.Colors.TEXT_PRIMARY),
            SecondaryText(cadence),
            date_cell(stream.get("next_expected_date"), SecondaryText),
            health_cell,
        ]
        if with_status:
            cells.append(status_control)
        if with_actions:
            cells.append(ft.Row(actions, spacing=Theme.Spacing.SM))
        return cells

    def _open_bulk_categorize(self, e: ft.ControlEvent) -> None:
        if self._selected:
            self._category_picker.open_for(list(self._selected), e)

    def _pick_category(self, stream_ids: list[int], category_key: str) -> None:
        """CategoryPickerButton's on_pick contract. The bills only - their
        transactions keep the categories they have, because a bill's
        category is otherwise inferred from them and a cascade would
        overwrite corrections made by hand."""
        if not category_key or not stream_ids or self.page is None:
            return
        self.page.run_task(self._apply_category, stream_ids, int(category_key))

    async def _apply_category(self, stream_ids: list[int], category_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._set_busy(True)
        try:
            result = await api.post(
                f"{_RECURRING_URL}/categorize",
                json={"stream_ids": stream_ids, "category_id": category_id},
            )
            if not isinstance(result, dict):
                ErrorSnackBar("Could not set the category.").launch(self.page)
                return
            updated = result.get("updated", 0)
            SuccessSnackBar(
                f"Category set on {updated} bill{'s' if updated != 1 else ''}."
            ).launch(self.page)
            self._selected.clear()
            self._update_selection()
            await self._load()
        finally:
            self._set_busy(False)

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

    def _set_busy(self, busy: bool) -> None:
        self._progress.visible = busy
        if self._progress.page:
            self._progress.update()

    async def _rescan(self) -> None:
        """Re-run detection so payees named since the last pass attach to
        their bills (and their icons follow)."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._set_busy(True)
        try:
            result = await api.post(f"{_RECURRING_URL}/rescan")
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Re-scan failed.").launch(self.page)
                return
            detected = result.get("detected", 0)
            pruned = result.get("pruned", 0)
            SuccessSnackBar(
                f"Re-scanned: {detected} bill{'s' if detected != 1 else ''}"
                + (f", {pruned} retired" if pruned else "")
                + "."
            ).launch(self.page)
            await self._load()
        finally:
            self._set_busy(False)

    async def _open_match_dialog(self, stream: dict) -> None:
        """Pick the transaction that paid this bill.

        Candidates come pre-shortlisted (same direction, unclaimed,
        amount in the bill's neighborhood, newest first) but the CHOICE
        is the user's - this exists precisely because the automatic
        matcher was wrong to find nothing, so a second automatic guess
        would repeat the mistake with confidence.
        """
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(f"{_RECURRING_URL}/{stream.get('id')}/match-candidates")
        if not isinstance(data, dict):
            # A failed fetch is not "no matches" - saying so sent a real
            # payment on a hunt for a bug that was actually a 500 here.
            ErrorSnackBar(api.last_error or "Could not load match candidates.").launch(
                self.page
            )
            return
        items = data.get("items", [])
        dialog: StyledAlertDialog | None = None

        async def _cancel() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _pick(txn: dict) -> None:
            await _cancel()
            result = await api.post(
                f"{_RECURRING_URL}/{stream.get('id')}/attach",
                json={"transaction_id": txn.get("id")},
            )
            if result is None:
                ErrorSnackBar(api.last_error or "Could not match.").launch(self.page)
                return
            SuccessSnackBar(
                f"Matched. {stream.get('name')} is paid; next expected "
                f"{result.get('next_expected_date') or 'never (one-time)'}."
            ).launch(self.page)
            await self._load()

        if not items:
            rows: list[ft.Control] = [
                SecondaryText(
                    "No unclaimed transactions look like this bill. The "
                    "payment may not be imported yet, or its amount is "
                    "far from the bill's figure."
                )
            ]
        else:
            rows = [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Column(
                                [
                                    TableNameText(
                                        t.get("merchant") or t.get("name") or ""
                                    ),
                                    SecondaryText(
                                        f"{t.get('date')} · "
                                        f"{t.get('account_name') or ''}",
                                        size=Theme.Typography.BODY_SMALL,
                                    ),
                                ],
                                spacing=0,
                                tight=True,
                            ),
                            expand=True,
                        ),
                        NumericText(
                            _usd(t.get("amount", 0)),
                            size=Theme.Typography.BODY_SMALL,
                        ),
                        PulseButton(
                            on_click_callable=(lambda txn=t: _pick(txn)),
                            text="This one",
                            variant="teal",
                            compact=True,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for t in items
            ]

        dialog = StyledAlertDialog(
            title=f"Which payment was {stream.get('name')}?",
            body=ft.Column(
                rows,
                spacing=Theme.Spacing.SM,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                height=min(60 * max(len(rows), 1) + 20, 420),
            ),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                )
            ],
            width=520,
        )
        self.page.open(dialog)

    def _open_pause_dialog(self, stream_ids: list[int]) -> None:
        """Until when, and optionally why. One dialog for a single row
        (the edit dialog's Pause) and a checked set (the bulk action).

        The why goes to ``metadata_`` server-side and comes back on the
        row's Paused tooltip - the note future-you reads after forgetting
        why an investment went quiet ("waiting until the pool is paid
        off"). Optional on purpose; a required field would get junk.
        """
        from app.services.finance.constants import PAUSE_INDEFINITE, add_months

        today = date.today()
        until = FormDateField(
            label="Paused until",
            value=pause_options(today)[2][1].isoformat(),  # 3 months
            width=200,
        )
        note = FormTextField(
            label="Why? (optional, shown on the row)",
            hint="e.g. pausing investments until the pool is paid off",
            width=360,
        )
        state = {"indefinite": False}

        def _on_pick(months: int) -> None:
            # 0 is the "No end date" chip: the date field hides rather
            # than displaying the sentinel year, which is an
            # implementation detail nobody should read.
            state["indefinite"] = months == 0
            until.visible = months != 0
            if months:
                until.value = add_months(today, months).isoformat()
            if until.page:
                until.update()

        # The SAME chips control every range picker in the product uses,
        # so the selected pick carries the standard teal pill treatment
        # instead of four identical muted buttons with no state.
        quick_row = DateRangeChips(
            options=[
                ("1 month", 1),
                ("2 months", 2),
                ("3 months", 3),
                ("6 months", 6),
                ("No end date", 0),
            ],
            selected_days=3,
            on_change=_on_pick,
        )
        dialog: StyledAlertDialog | None = None

        async def _cancel() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _apply() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            if state["indefinite"]:
                when = PAUSE_INDEFINITE
            else:
                raw = (until.value or "").strip()
                try:
                    when = date.fromisoformat(raw)
                except ValueError:
                    ErrorSnackBar("Pick a date to pause until.").launch(self.page)
                    return
                if when <= today:
                    ErrorSnackBar("The pause needs a future date.").launch(self.page)
                    return
            await _cancel()
            api = get_session_state(self.page).api_client
            body: dict[str, str] = {"until": when.isoformat()}
            note_text = (note.value or "").strip()
            if note_text:
                body["note"] = note_text
            done = 0
            for stream_id in stream_ids:
                await api.post(f"{_RECURRING_URL}/{stream_id}/pause", json=body)
                if not api.last_error:
                    done += 1
            failed = len(stream_ids) - done
            message = (
                f"Paused {done} {pause_label(when.isoformat())}."
                if not failed
                else f"Paused {done}, {failed} failed."
            )
            (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)
            self._selected.clear()
            self._update_selection()
            await self._load()

        count = len(stream_ids)
        dialog = StyledAlertDialog(
            title=("Pause this bill" if count == 1 else f"Pause {count} bills"),
            body=ft.Column(
                [
                    quick_row,
                    until,
                    note,
                    SecondaryText(
                        "Out of the forecast, the Bills total and every "
                        "nag until then - back on its own the day the "
                        "date passes.",
                        size=Theme.Typography.BODY_SMALL,
                    ),
                ],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_apply,
                    text="Pause",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=420,
        )
        self.page.open(dialog)

    async def _bulk_pause(self) -> None:
        if self._selected:
            self._open_pause_dialog(sorted(self._selected))

    async def _bulk_mute(self) -> None:
        """Mute is reversible (Unmute stays reachable on Detected), so it
        applies straight away - no confirm for something a click undoes."""
        await self._bulk_apply("mute")

    async def _bulk_delete(self) -> None:
        """Delete asks first: it drops rows out of Bills & Income, and for
        a hand-entered bill there is nothing to re-detect it from."""
        count = len(self._selected)
        if not count:
            return

        async def _confirm() -> None:
            await self._bulk_apply("delete")

        ConfirmDialog(
            page=self.page,
            title="Delete these?",
            message=(
                f"Remove {count} row{'s' if count != 1 else ''} from Bills & "
                "Income? Detected ones are muted so detection cannot bring "
                "them straight back; anything you added by hand is gone for "
                "good."
            ),
            confirm_text=f"Delete {count}",
            destructive=True,
            on_confirm=_confirm,
        ).show()

    async def _bulk_apply(self, verb: str) -> None:
        """One request per stream - the recurring API is per-id, and a
        failure on one row should not abandon the rest, so results are
        tallied rather than raised."""
        from app.components.frontend.state.session_state import get_session_state

        ids = sorted(self._selected)
        if not ids:
            return
        api = get_session_state(self.page).api_client
        self._set_busy(True)
        try:
            done = 0
            for stream_id in ids:
                if verb == "delete":
                    await api.delete(f"{_RECURRING_URL}/{stream_id}")
                else:
                    await api.post(f"{_RECURRING_URL}/{stream_id}/{verb}")
                # APIClient returns None on failure and never raises; delete
                # answers 204 (no body), so "not None" is the wrong test
                # there - last_error is the honest signal for both.
                if not api.last_error:
                    done += 1
            failed = len(ids) - done
            word = "Deleted" if verb == "delete" else "Muted"
            message = (
                f"{word} {done}." if not failed else f"{word} {done}, {failed} failed."
            )
            (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)
            self._selected.clear()
            self._update_selection()
            await self._load()
        finally:
            self._set_busy(False)

    def _action(self, stream_id: int, verb: str):
        async def _do() -> None:
            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            result = await api.post(f"{_RECURRING_URL}/{stream_id}/{verb}")
            if result is None:
                ErrorSnackBar(api.last_error or f"Could not {verb}.").launch(self.page)
                return
            await self._load()

        return _do

    # -- add dialog --------------------------------------------------------

    async def _open_add(self) -> None:
        """Declare a bill or income by hand (name, kind, amount, cadence, due)."""
        form = {"name": "", "amount": "", "due": ""}
        name = FormTextField(
            label="Name",
            on_change=lambda e: form.__setitem__(
                "name", (getattr(e.control, "value", "") or "").strip()
            ),
            width=360,
        )
        kind_dd = FormDropdown(
            label="Kind",
            options=[("outflow", "Bill"), ("inflow", "Income")],
            value="outflow",
            width=360,
        )
        amount = FormTextField(
            label="Amount ($)",
            on_change=lambda e: form.__setitem__(
                "amount", getattr(e.control, "value", "") or ""
            ),
            width=360,
        )
        frequency_dd = FormDropdown(
            label="Repeats",
            options=list(BILL_FREQUENCY_OPTIONS.items()),
            value="monthly",
            width=360,
        )
        due = FormDateField(
            label="Next due date",
            on_change=lambda iso: form.__setitem__("due", iso),
            width=360,
        )
        # Offered at creation, not just afterwards: a bill saved without
        # one is invisible to Projected until somebody notices.
        add_account_dd = FormDropdown(
            label="Account",
            options=[("", "No account"), *self._accounts],
            value="",
            width=360,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _add() -> None:
            if not form["name"]:
                ErrorSnackBar("Name is required.").launch(self.page)
                return
            cents = _parse_dollars(form["amount"])
            if cents <= 0:
                ErrorSnackBar("Amount must be more than $0.").launch(self.page)
                return
            from datetime import date as date_cls

            try:
                due_date = date_cls.fromisoformat(form["due"])
            except ValueError:
                # Only reachable when nothing was picked - the calendar
                # cannot hand back a malformed date.
                ErrorSnackBar("Pick a next due date.").launch(self.page)
                return
            dialog.open = False
            self.page.update()

            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            result = await api.post(
                _RECURRING_URL,
                json={
                    "name": form["name"],
                    "direction": kind_dd.value or "outflow",
                    "frequency": frequency_dd.value or "monthly",
                    "expected_amount": cents,
                    "next_expected_date": due_date.isoformat(),
                    **(
                        {"account_id": int(add_account_dd.value)}
                        if add_account_dd.value
                        else {}
                    ),
                },
            )
            if result is None:
                ErrorSnackBar(api.last_error or "Could not save.").launch(self.page)
                return
            SuccessSnackBar(f"{form['name']} added.").launch(self.page)
            await self._load()

        dialog = StyledAlertDialog(
            title="Add a bill or income",
            body=ft.Column(
                [name, kind_dd, amount, frequency_dd, due, add_account_dd],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_add,
                    text="Add",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    async def _open_edit(self, stream: dict) -> None:
        """Edit a stream's declared facts. Only changed fields are sent, so
        an untouched form is a no-op and a detected stream's fields (like a
        cadence outside the manual-entry set) survive unedited."""
        current_amount = (
            stream.get("expected_amount") or stream.get("average_amount") or 0
        )
        current_freq = stream.get("frequency") or "monthly"
        current_due = stream.get("next_expected_date") or ""
        name = FormTextField(
            label="Name",
            value=stream.get("name") or "",
        )
        # The detector produces cadences (bimonthly, semi-annual) the
        # manual-entry set doesn't offer; the current one is always a
        # choice so opening the dropdown never lies about the stream.
        freq_options = list(BILL_FREQUENCY_OPTIONS.items())
        if current_freq not in BILL_FREQUENCY_OPTIONS:
            freq_options.append((current_freq, current_freq.replace("_", " ").title()))
        frequency_dd = FormDropdown(
            label="Repeats",
            options=freq_options,
            value=current_freq,
        )
        amount = FormTextField(
            label="Amount ($)",
            value=f"{current_amount / 100:.2f}" if current_amount else "",
        )
        due = FormDateField(
            label="Next due date",
            value=current_due,
        )
        # The bill's OWN category. Blank means "keep inferring it from the
        # transactions", which is what every bill does until someone
        # states otherwise (FinanceService.stream_category_names).
        current_category = str(stream.get("category_id") or "")
        category_dd = CategoryPickerField(
            categories=self._categories,
            value=current_category,
        )
        current_account = str(stream.get("account_id") or "")
        account_dd = FormDropdown(
            label="Account",
            options=[("", "No account"), *self._accounts],
            value=current_account,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _toggle_mute() -> None:
            dialog.open = False
            self.page.update()

            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            verb = "unmute" if stream.get("is_muted") else "mute"
            result = await api.post(f"{_RECURRING_URL}/{stream.get('id')}/{verb}")
            if result is None:
                ErrorSnackBar(api.last_error or f"Could not {verb}.").launch(self.page)
                return
            SuccessSnackBar(f"{stream.get('name')} {verb}d.").launch(self.page)
            await self._load()

        async def _confirm_delete() -> None:
            dialog.open = False
            self.page.update()

            async def _do_delete() -> None:
                from app.components.frontend.state.session_state import (
                    get_session_state,
                )

                api = get_session_state(self.page).api_client
                await api.delete(f"{_RECURRING_URL}/{stream.get('id')}")
                SuccessSnackBar(f"{stream.get('name')} deleted.").launch(self.page)
                await self._load()

            detected = stream.get("source") not in (None, "user")
            ConfirmDialog(
                page=self.page,
                title="Delete bill or income",
                message=(
                    f'Delete "{stream.get("name", "")}"? Its transactions are '
                    "kept; only this recurring entry goes away."
                    + (
                        " If the pattern keeps appearing in imports, it can "
                        "be detected again - it will come back muted."
                        if detected
                        else ""
                    )
                ),
                confirm_text="Delete",
                destructive=True,
                on_confirm=_do_delete,
            ).show()

        async def _save() -> None:
            payload: dict = {}
            new_name = (name.value or "").strip()
            if not new_name:
                ErrorSnackBar("Name is required.").launch(self.page)
                return
            if new_name != (stream.get("name") or ""):
                payload["name"] = new_name
            cents = _parse_dollars(amount.value or "")
            if cents <= 0:
                ErrorSnackBar("Amount must be more than $0.").launch(self.page)
                return
            if cents != current_amount:
                payload["expected_amount"] = cents
            if (frequency_dd.value or current_freq) != current_freq:
                payload["frequency"] = frequency_dd.value
            # Always ISO - FormDateField only ever holds what the calendar
            # produced, so there is nothing left to validate here.
            due_text = due.value
            if due_text and due_text != current_due:
                payload["next_expected_date"] = due_text
            picked_category = category_dd.value or ""
            if picked_category != current_category and picked_category:
                payload["category_id"] = int(picked_category)
            picked_account = account_dd.value or ""
            if picked_account != current_account and picked_account:
                payload["account_id"] = int(picked_account)
            dialog.open = False
            self.page.update()
            if not payload:
                return

            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            result = await api.patch(
                f"{_RECURRING_URL}/{stream.get('id')}", json=payload
            )
            if result is None:
                ErrorSnackBar(api.last_error or "Could not save.").launch(self.page)
                return
            SuccessSnackBar(f"{new_name} updated.").launch(self.page)
            await self._load()

        async def _toggle_pause() -> None:
            dialog.open = False
            self.page.update()
            if stream_is_paused(stream):
                from app.components.frontend.state.session_state import (
                    get_session_state,
                )

                api = get_session_state(self.page).api_client
                await api.post(f"{_RECURRING_URL}/{stream.get('id')}/resume")
                if api.last_error:
                    ErrorSnackBar(api.last_error).launch(self.page)
                    return
                SuccessSnackBar(f"{stream.get('name')} resumed.").launch(self.page)
                await self._load()
                return
            self._open_pause_dialog([int(stream.get("id"))])

        async def _open_match() -> None:
            dialog.open = False
            self.page.update()
            await self._open_match_dialog(stream)

        match_button = PulseButton(
            on_click_callable=_open_match,
            text="Match...",
            variant="muted",
            compact=True,
        )
        match_button.tooltip = (
            "Point this bill at the transaction that paid it - consumes "
            "the occurrence and teaches the matcher for next month"
        )
        pause_button = PulseButton(
            on_click_callable=_toggle_pause,
            text="Resume" if stream_is_paused(stream) else "Pause...",
            variant="muted",
            compact=True,
        )
        pause_button.tooltip = (
            f"Paused {pause_label(stream.get('paused_until'))} - end it early"
            if stream_is_paused(stream)
            else "Skip this for a while: out of the forecast and totals "
            "until a date you pick, back on its own after"
        )
        mute_button = PulseButton(
            on_click_callable=_toggle_mute,
            text="Unmute" if stream.get("is_muted") else "Mute",
            variant="muted",
            compact=True,
        )
        mute_button.tooltip = (
            "Resume insights about this stream"
            if stream.get("is_muted")
            else "Stop insights about this stream"
        )
        delete_button = PulseButton(
            on_click_callable=_confirm_delete,
            text="Delete",
            variant="stop",
            compact=True,
        )
        delete_button.tooltip = "Remove this entry. Transactions are kept."
        dialog = StyledAlertDialog(
            title="Edit bill or income",
            # No width pins on the fields: the house form controls
            # stretch by design, and the STRETCH alignment is what lets
            # the dialog's width govern - six hardcoded width=360 pins
            # here are why widening the dialog once just grew margin.
            body=ft.Column(
                [name, amount, frequency_dd, due, category_dd, account_dd],
                spacing=Theme.Spacing.MD,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            # One row, dialog widened to hold it: Delete and the stream
            # verbs (Mute/Pause/Match) sit apart on the left - they act
            # on the bill itself, not the form - Cancel/Save on the
            # right. 400px fit four buttons; six need the width.
            actions=[
                delete_button,
                mute_button,
                pause_button,
                match_button,
                ft.Container(expand=True),
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=560,
        )
        self.page.open(dialog)
