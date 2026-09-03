"""The Projected sub-tab: the balance-forecast chart panel."""

from __future__ import annotations

from datetime import (
    timedelta,
)
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.data_table import DataTable
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_modal import FinancePanel
from app.components.frontend.dashboard.modals.finance_recurring_tab.shared import (
    _RECURRING_URL,
    _usd_signed,
    projection_columns,
    projection_layout,
)
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
)
from app.components.frontend.theme import AegisTheme as Theme


class _OverdueDateText(SecondaryText):
    """A date the money was owed on and did not leave."""

    def __init__(self, value: str, **kwargs: object) -> None:
        super().__init__(value, **kwargs)
        self.color = Theme.Colors.WARNING


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
                # An overdue occurrence lands on today so the balance is
                # right, but the row shows the day it was actually due,
                # in the colour the bills table marks overdue with.
                # Shows the day it was due, sorts by the day it lands.
                # The Balance column is the running total in the order
                # money moves, so a row sorted anywhere else would make
                # that column read as nonsense.
                date_cell(
                    p.get("due_date") or p.get("date"),
                    SecondaryText if not p.get("due_date") else _OverdueDateText,
                    sort_value=p.get("date"),
                ),
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
