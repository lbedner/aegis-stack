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
    BaseIconButton,
    DataTable,
    DataTableColumn,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.table import TableCellText, TableNameText
from app.components.frontend.dashboard.modals.base_popup import OverlayStyledDialog
from app.components.frontend.dashboard.modals.finance_modal.accounts_tab import (
    _list_card,
    _overview_row,
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
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _ACCOUNT_GROUPS,
    _MAX_CASHFLOW_BARS,
    _OVERVIEW_CARD_HEIGHT,
    _PIE_CATEGORIES,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import AccountFilter
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _account_display_balance,
    _amount_cell,
    _balance_color,
    _group_for,
    _month_label,
    _usd,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    _transaction_expanded_content,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_panel import (
    UncategorizedPanel,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.dashboard.modals.modal_sections import (
    PIE_CHART_TAIL_COLOR,
    BarChartCard,
    BarSeries,
    ChartColors,
    DateRangeChips,
    EmptyStatePlaceholder,
    LineChartCard,
    LineSeries,
    PieChartCard,
    RankedBar,
    RankedBarCard,
    chart_floor,
    date_cell,
    headline_stat,
    headline_stat_color,
    ledger_amount_color,
)
from app.components.frontend.theme import AegisTheme as Theme


class OverviewTab(FinancePanel):
    """Net-worth summary: assets, liabilities, net worth, a per-group breakdown,
    and spending by category. No sidebar — this is the landing view."""

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener)
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._body = ft.Column(
            spacing=Theme.Spacing.LG, scroll=ft.ScrollMode.AUTO, expand=True
        )
        # Built once, on first open, then reused - see _open_uncategorized.
        # A fresh dialog + UncategorizedPanel on every click (the original
        # design) never actually left page.overlay once closed: Flet's
        # page.close()/`.open = False` only hides a dialog, it doesn't
        # remove it or its subtree - so every reopen was a permanent leak.
        # This mirrors _open_modal's own cache pattern (card_utils.py) for
        # exactly that reason.
        #
        # OverlayStyledDialog, not StyledAlertDialog: this dialog's body
        # (UncategorizedPanel) hosts its own account-filter Dropdown - a
        # page.overlay-based popup - and a real ft.AlertDialog (what
        # StyledAlertDialog wraps) renders through Flutter's own dialog
        # route, which always paints above page.overlay content regardless
        # of append order. That nested Dropdown opened BEHIND this dialog
        # instead of above it (confirmed live) until this swap - see
        # OverlayStyledDialog's own docstring (base_popup.py).
        self._uncategorized_dialog: OverlayStyledDialog | None = None
        self._uncategorized_panel: UncategorizedPanel | None = None
        # One window drives every card on the page, so the pie, the bars
        # and the net-worth line always describe the same span - three
        # charts on different periods invite false comparisons.
        self._days = 180
        # Parallel to the pie's own ``slices`` (index i here -> the
        # category name(s) slice i represents) - rebuilt every ``_load``.
        # A named slice is one parent category (spending_by_category's own
        # rollup); "Other" is every name that didn't make the cut, which
        # is why this is a list of lists, not a list of names.
        self._pie_slice_categories: list[list[str]] = []
        # Header matches the Projected tab: title + subtitle on the left,
        # the headline figures bare against the right edge. Cards below
        # would cost the chart a card's height and box it twice.
        self._stats = ft.Row(
            [],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                H3Text("Net worth"),
                                SecondaryText(
                                    "Everything you own, less everything you owe"
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Container(expand=True),
                        DateRangeChips(
                            options=[
                                ("1m", 30),
                                ("3m", 90),
                                ("6m", 180),
                                ("1y", 365),
                                ("All", 9999),
                            ],
                            selected_days=self._days,
                            on_change=self._on_range,
                        ),
                        BaseIconButton(
                            self._load,
                            icon=ft.Icons.REFRESH,
                            icon_size=18,
                            tooltip="Refresh overview",
                        ),
                        self._stats,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.LG,
                ),
                # Separates the headline banner from the charts below, so
                # the figures read as a summary OF the page rather than as
                # a caption on the first card.
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self._body,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    def _on_range(self, days: int) -> None:
        self._days = days
        self._reload()

    def _on_pie_slice_click(self, index: int) -> None:
        if index >= len(self._pie_slice_categories) or not self.page:
            return
        categories = self._pie_slice_categories[index]
        label = categories[0] if len(categories) == 1 else "Other"

        # A real async function, not page.run_task(lambda: ...) - Page.run_task
        # asserts its handler is an actual coroutine function, which a lambda
        # wrapping a call is not (see the run_now fix in controls/debounce.py).
        async def _open() -> None:
            await self._open_category_drilldown(categories, label)

        self.page.run_task(_open)

    async def _open_category_drilldown(self, categories: list[str], label: str) -> None:
        """The transactions behind one pie slice - same DataTable + inline
        row-expand flow the Accounts register uses (TransactionsPanel._load).
        Built fresh per click rather than cached: unlike
        ``_open_uncategorized`` (always the same content), a different
        slice needs different rows every time, so there's nothing to reuse
        between opens. Row-expand rather than a second, nested dialog -
        this table already lives inside a ``StyledAlertDialog`` of its own.
        """
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        window = 3650 if self._days >= 9000 else self._days
        params: dict[str, object] = {
            "days": window,
            "categories": categories,
            **self._account_filter.params(),
        }
        data = await api.get("/api/v1/finance/spending/transactions", params=params)
        items = data.get("items", []) if isinstance(data, dict) else []

        columns = [
            DataTableColumn("Date", width=120),
            DataTableColumn("Payee", hideable=False),
            DataTableColumn("Category", width=200),
            DataTableColumn("Amount", width=150, alignment="right"),
        ]
        rows = [
            [
                date_cell(item.get("date")),
                TableNameText(item.get("name") or ""),
                TableCellText(item.get("category") or "—"),
                _amount_cell(item.get("amount", 0)),
            ]
            for item in items
        ]

        def _expand_detail(idx: int, _items: list = items) -> ft.Control:
            return _transaction_expanded_content(_items[idx])

        table = DataTable(
            columns=columns,
            rows=rows,
            empty_message="No transactions in this window.",
            scroll_height=440,
            expandable_content=_expand_detail,
        )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        dialog = StyledAlertDialog(
            title=f"{label} · last {window}d",
            body=ft.Container(content=table, width=780),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Close",
                    variant="muted",
                    compact=True,
                )
            ],
            width=820,
        )
        self.page.open(dialog)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        # Everything below describes only the accounts in view. An EMPTY
        # selection ("Remove all") must render an empty page - its params
        # would serialize to nothing and read as "no filter" server-side,
        # so the filtered sections are ignored client-side instead.
        filter_empty = self._account_filter.is_empty
        filter_params = self._account_filter.params()
        window = 3650 if self._days >= 9000 else self._days
        # One surface, one round trip (house rule): the whole Overview
        # arrives as a single composite payload; the granular endpoints
        # remain for targeted refreshes only.
        overview = await api.get(
            "/api/v1/finance/overview",
            params={
                "days": window,
                "months": max(1, min(36, round(window / 30))),
                **filter_params,
            },
        )
        if not isinstance(overview, dict):
            overview = {}
        data = overview.get("accounts") or {}
        all_items = data.get("items", []) if isinstance(data, dict) else []
        items = [a for a in all_items if self._account_filter.allows(a.get("id"))]

        assets = sum(
            _account_display_balance(a)
            for a in items
            if a.get("classification") != "liability"
        )
        liabilities = sum(
            _account_display_balance(a)
            for a in items
            if a.get("classification") == "liability"
        )
        net_worth = assets + liabilities

        # Net-worth trend (materialized daily by the scheduler; empty until it
        # has run against real accounts).
        nw = [] if filter_empty else overview.get("net_worth") or []
        points = nw if isinstance(nw, list) else []
        chart: ft.Control | None = None
        if len(points) >= 2:
            values = [p.get("net_worth_amount", 0) / 100 for p in points]
            chart = LineChartCard(
                title="Net worth over time",
                subtitle="",
                x_labels=[str(p.get("as_of_date", "")) for p in points],
                series=[
                    LineSeries(
                        label="Net Worth",
                        color=Theme.Colors.SUCCESS,
                        points=[(i, v) for i, v in enumerate(values)],
                        tooltips=[_usd(p.get("net_worth_amount", 0)) for p in points],
                        fill=True,
                        stroke_width=3,
                    )
                ],
                min_y=chart_floor(values),
            )

        self._stats.controls = [
            headline_stat("Assets", _usd(assets), headline_stat_color(assets)),
            headline_stat(
                "Liabilities", _usd(liabilities), headline_stat_color(liabilities)
            ),
            headline_stat("Net Worth", _usd(net_worth), headline_stat_color(net_worth)),
        ]
        if self._stats.page is not None:
            self._stats.update()

        # Per-group breakdown (same buckets as the sidebar).
        grouped: dict[str, list] = {}
        for account in items:
            grouped.setdefault(_group_for(account.get("account_type", "")), []).append(
                account
            )
        breakdown_rows: list[ft.Control] = []
        for label, _types in _ACCOUNT_GROUPS:
            group = grouped.get(label)
            if not group:
                continue
            subtotal = sum(_account_display_balance(a) for a in group)
            plural = "s" if len(group) != 1 else ""
            breakdown_rows.append(
                _overview_row(
                    label,
                    f"{len(group)} account{plural}",
                    subtotal,
                    _balance_color(subtotal),
                )
            )

        # Income vs spend per month - grouped bars, one axis. Two series get
        # the house ramp's most-separated pair (validated for CVD), never
        # red for spending: outflow is the assumption here, not an alarm.
        # Months, not days: 36 is the endpoint's ceiling and also as many
        # bars as fit before they turn into hairlines.
        cash = {} if filter_empty else overview.get("cashflow") or {}
        cash_months = cash.get("items", []) if isinstance(cash, dict) else []
        cash_card: ft.Control | None = None
        if any(m.get("income") or m.get("expense") for m in cash_months):
            cash_months = _fold_cashflow(cash_months)
            cash_card = BarChartCard(
                x_labels=[str(m.get("label", "")) for m in cash_months],
                series=[
                    BarSeries(
                        "Income",
                        ChartColors.TEAL,
                        [(m.get("income") or 0) / 100 for m in cash_months],
                    ),
                    BarSeries(
                        "Spending",
                        ChartColors.VIOLET,
                        [(m.get("expense") or 0) / 100 for m in cash_months],
                    ),
                ],
                value_format=lambda v: f"${v:,.0f}",
            )

        # Who took the most, and what is about to hit. Both are ranked
        # lists rather than plots: the labels are names, and the ordering
        # is the point.
        payees = overview.get("top_payees") or {}
        payee_items = payees.get("items", []) if isinstance(payees, dict) else []
        payee_card: ft.Control | None = None
        if payee_items:
            payee_card = RankedBarCard(
                title=f"Top payees · {window}d",
                rows=[
                    RankedBar(
                        label=item.get("payee") or "",
                        value=(item.get("amount") or 0) / 100,
                        display=_usd(item.get("amount") or 0),
                        meta=f"{item.get('transaction_count', 0)}x",
                    )
                    for item in payee_items
                ],
            )

        # Upcoming bills come from the same projection the Projected tab
        # walks, so the two can never disagree about what is due.
        upcoming = overview.get("projection") or {}
        points = upcoming.get("points", []) if isinstance(upcoming, dict) else []
        bills = [p for p in points if (p.get("amount") or 0) < 0][:7]
        bills_card: ft.Control | None = None
        if bills:
            bills_card = RankedBarCard(
                title="Upcoming bills · next 30 days",
                rows=[
                    RankedBar(
                        label=bill.get("name") or "",
                        value=abs(bill.get("amount") or 0) / 100,
                        display=_usd(abs(bill.get("amount") or 0)),
                        meta=str(bill.get("date", ""))[5:],
                    )
                    for bill in bills
                ],
                color=ChartColors.VIOLET,
            )

        # Recent transactions: the ledger itself, newest first. Not ranked
        # and not plotted - it answers "what just happened", where the
        # ORDER is the information, so bars would be actively misleading.
        recent = overview.get("recent_transactions") or {}
        recent_items = recent.get("items", []) if isinstance(recent, dict) else []
        recent_card: ft.Control | None = None
        if recent_items:
            recent_card = _list_card(
                "Recent transactions",
                [
                    _overview_row(
                        item.get("name") or "",
                        f"{item.get('date', '')} · {item.get('category') or 'uncategorized'}",
                        item.get("amount") or 0,
                        ledger_amount_color(item.get("amount") or 0),
                    )
                    for item in recent_items
                ],
            )

        # Uncategorized: work waiting, not a metric. The title carries the
        # FULL backlog count while the rows show only the newest few, so
        # the card says how much there is without pretending to list it.
        uncat = overview.get("uncategorized") or {}
        uncat_items = uncat.get("items", []) if isinstance(uncat, dict) else []
        uncat_total = uncat.get("total", 0) if isinstance(uncat, dict) else 0
        uncat_card: ft.Control | None = None
        if uncat_items:
            uncat_card = _list_card(
                f"Uncategorized · {uncat_total:,} to review",
                [
                    _overview_row(
                        item.get("name") or "",
                        str(item.get("date", "")),
                        item.get("amount") or 0,
                        ledger_amount_color(item.get("amount") or 0),
                    )
                    for item in uncat_items
                ],
                on_click=self._open_uncategorized,
            )

        # Spending by category (last 30 days) — outflows, largest first.
        spending = [] if filter_empty else overview.get("spending") or []
        spend_list = spending if isinstance(spending, list) else []
        # ``category`` here is already the PARENT category name -
        # spending_by_category rolls up "Parent:Child" leaves before it
        # ever reaches this endpoint (domains/ledger/categories.py), specifically
        # so this pie doesn't fragment a real ledger's spending across
        # every sub-category and dump most of it in "Other" (was 30.7%
        # leaf-grouped on real data, 16.3% parent-rolled-up, 5.3% at
        # _PIE_CATEGORIES=15 - the fix lives server-side, not here; the
        # slice COUNT is tuned above). The legend scrolls if it runs past
        # the chart's own height (modal_sections.py) rather than clipping
        # entries silently; the tail keeps a fixed neutral color so it
        # reads as tail, not category.
        pie_card: ft.Control | None = None
        top_spend = spend_list[:_PIE_CATEGORIES]
        self._pie_slice_categories = []
        if top_spend:
            tail_items = spend_list[_PIE_CATEGORIES:]
            tail = sum(item.get("amount", 0) for item in tail_items)
            slices = [
                {
                    "value": item.get("amount", 0) / 100,
                    "label": item.get("category", ""),
                }
                for item in top_spend
            ]
            self._pie_slice_categories = [
                [item.get("category", "")] for item in top_spend
            ]
            if tail:
                slices.append(
                    {
                        "value": tail / 100,
                        "label": "Other",
                        "color": PIE_CHART_TAIL_COLOR,
                    }
                )
                self._pie_slice_categories.append(
                    [item.get("category", "") for item in tail_items]
                )
            pie_card = PieChartCard(
                "Spending by category",
                slices,
                value_formatter=lambda value: f"${value:,.2f}",
                on_slice_click=self._on_pie_slice_click,
                # This card sits in a Row stretched to _OVERVIEW_CARD_HEIGHT
                # (320px) - PieChartCard's own default 130px chart left most
                # of that height empty (see chart_size's own docstring).
                # 230 -> a 310px card, close to the 320 stretch target.
                chart_size=230,
            )

        spend_rows = [
            _overview_row(
                s.get("category", ""),
                "",
                s.get("amount", 0),
                Theme.Colors.ERROR,
            )
            for s in spend_list[:_PIE_CATEGORIES]
        ]

        self._body.controls.clear()
        # One card row, three questions: where is it going (pie), am I
        # keeping any of it (bars), and where has it got me (net worth).
        # Each card expands, so the Row divides the width between however
        # many of them have data.
        # Each card is wrapped in an expanding Container so the Row hands
        # it a FINITE width. Charts inside are ``expand=True``; in a Row
        # with no bound that resolves to infinity and fl_chart fails to
        # lay out, which is why an unwrapped card row renders blank.
        card_row = [c for c in (chart, pie_card, cash_card) if c is not None]
        if card_row:
            self._body.controls.append(
                ft.Row(
                    [ft.Container(content=card, expand=True) for card in card_row],
                    spacing=Theme.Spacing.MD,
                    # STRETCH, not START: cards whose content differs in
                    # height (a donut is shorter than a plot + legend)
                    # otherwise end at three different baselines.
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    height=_OVERVIEW_CARD_HEIGHT,
                )
            )
        # Second row: the two ranked lists. Kept off the first row so the
        # plots there keep enough width to be readable.
        for row_cards in (
            (payee_card, bills_card, recent_card),
            (uncat_card,),
        ):
            cards = [c for c in row_cards if c is not None]
            if not cards:
                continue
            self._body.controls.append(
                ft.Row(
                    [ft.Container(content=card, expand=True) for card in cards],
                    spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    height=_OVERVIEW_CARD_HEIGHT,
                )
            )
        if breakdown_rows:
            self._body.controls.append(
                SecondaryText(
                    "By group",
                    size=Theme.Typography.CAPTION,
                    color=Theme.Colors.TEXT_SECONDARY,
                    weight=ft.FontWeight.W_600,
                )
            )
            self._body.controls.append(ft.Column(breakdown_rows, spacing=0))
        elif not items:
            self._body.controls.append(
                EmptyStatePlaceholder(message="No accounts yet.")
            )
        if spend_rows:
            self._body.controls.append(
                SecondaryText(
                    "Spending · last 30 days",
                    size=Theme.Typography.CAPTION,
                    color=Theme.Colors.TEXT_SECONDARY,
                    weight=ft.FontWeight.W_600,
                )
            )
            self._body.controls.append(ft.Column(spend_rows, spacing=0))
        if self._body.page is not None:
            self._body.update()

    def _open_uncategorized(self) -> None:
        """Build once, on first open, then reuse - ``page.close()``/
        ``dialog.open = False`` only hides a dialog, Flet never actually
        removes it (or its subtree) from ``page.overlay``, so a fresh
        dialog + ``UncategorizedPanel`` on every click was a permanent
        leak on every reopen. Same cache-and-refresh shape ``_open_modal``
        already uses for the whole Finance modal itself.
        """
        if self._uncategorized_dialog is None:
            # Same shared AccountFilter FinanceDetailDialog's own button
            # drives, so a narrower view set there keeps applying inside
            # this popup too - this panel builds its OWN button though
            # (register_filter_listener not given): the shared one lives
            # above the tab strip, which this popup covers when open, so
            # there'd be no way to reach it otherwise.
            #
            # 1200, not UncategorizedPanel's own 860 default: search,
            # account filter, seven date chips, and two buttons all share
            # one row, and narrower widths packed them edge to edge, and
            # left the table's own Payee column (the identity column, the
            # one actually worth reading) squeezed down to a handful of
            # characters before it ellipsed.
            panel = UncategorizedPanel(
                self.page, width=1200, account_filter=self._account_filter
            )
            self._uncategorized_panel = panel

            async def _done() -> None:
                dialog.hide()
                self.page.update()
                await self._load()

            dialog = OverlayStyledDialog(
                self.page,
                title="Uncategorized transactions",
                body=panel,
                width=1200,
                actions=[
                    PulseButton(on_click_callable=_done, text="Done", compact=True)
                ],
            )
            self._uncategorized_dialog = dialog
            # OverlayStyledDialog isn't auto-attached to the page the way
            # page.open() handles a real AlertDialog - caller owns this
            # one-time append (see its own docstring).
            self.page.overlay.append(dialog)
        else:
            # Reopening a cached panel - did_mount already fired once and
            # won't again, so this is what keeps the data from going stale.
            self._uncategorized_panel.refresh()
        self._uncategorized_dialog.show()
        self.page.update()


def _fold_cashflow(months: list[dict]) -> list[dict]:
    """Group a monthly cashflow series into at most ``_MAX_CASHFLOW_BARS``.

    Returns rows carrying a display ``label`` alongside the summed income
    and expense. Short windows pass through untouched, labelled by month.
    """
    if len(months) <= _MAX_CASHFLOW_BARS:
        return [
            {**month, "label": _month_label(month.get("month", ""))} for month in months
        ]

    def bucket(month_key: str) -> str:
        year, _, mon = str(month_key).partition("-")
        if len(months) <= _MAX_CASHFLOW_BARS * 3:  # <= ~3 years -> quarters
            quarter = (int(mon or 1) - 1) // 3 + 1
            return f"Q{quarter} '{year[-2:]}"
        return year

    folded: dict[str, dict] = {}
    for month in months:
        key = bucket(month.get("month", ""))
        row = folded.setdefault(key, {"label": key, "income": 0, "expense": 0})
        row["income"] += month.get("income") or 0
        row["expense"] += month.get("expense") or 0
    return list(folded.values())
