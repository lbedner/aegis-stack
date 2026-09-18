"""The Overview tab: provider status, key metrics, revenue over time.

The only tab that fetches a series rather than a list. It paints the
metrics immediately and fills the chart when revenue arrives, so a slow
provider delays the chart and not the tab.
"""

from typing import Any

import flet as ft
from app.components.frontend import styles
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import MetricCard
from .formatting import _short_date


class OverviewTab(ft.Container):
    """Key metrics + a 30-day revenue trend chart."""

    # How many days of revenue to plot. 30 is short enough that daily
    # granularity still reads well and long enough to show a trend.
    _REVENUE_WINDOW_DAYS = 30

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}

        total_txns = metadata.get("total_transactions", 0)
        revenue_cents = metadata.get("total_revenue_cents", 0)
        active_subs = metadata.get("active_subscriptions", 0)
        open_disputes = metadata.get("open_disputes", 0)

        # Metric cards row — mirrors database_modal's layout
        metric_cards = ft.Row(
            [
                MetricCard(
                    "Transactions",
                    f"{total_txns:,}",
                    Theme.Colors.INFO,
                ),
                MetricCard(
                    "Revenue",
                    f"${revenue_cents / 100:,.2f}",
                    Theme.Colors.SUCCESS,
                ),
                MetricCard(
                    "Subscriptions",
                    str(active_subs),
                    Theme.Colors.INFO,
                ),
                MetricCard(
                    "Open Disputes",
                    str(open_disputes),
                    Theme.Colors.ERROR if open_disputes else Theme.Colors.SUCCESS,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
        )

        # Chart placeholder — async-populated by _load_revenue on mount.
        # Rendered inside a bordered card so it matches the modal's rhythm
        # before data arrives. Height tuned so the axis labels and curve
        # have breathing room; LineChart's label_size (40px left, 20px
        # bottom) alone eats ~60px, so a 240px box left <180px of plot
        # area and the curve visibly clipped.
        self._chart_container = ft.Container(
            content=ft.Row(
                [BodyText("Loading revenue…")],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=ft.padding.all(Theme.Spacing.LG),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            height=340,
        )

        self.content = ft.Column(
            [
                metric_cards,
                ft.Container(height=Theme.Spacing.LG),
                H3Text(f"Cumulative revenue — last {self._REVENUE_WINDOW_DAYS} days"),
                ft.Container(height=Theme.Spacing.SM),
                self._chart_container,
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

        page.run_task(self._load_revenue)

    async def _load_revenue(self) -> None:
        """Fetch the timeseries and swap in the teal line chart."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(
            "/api/v1/payment/revenue-timeseries",
            params={"days": self._REVENUE_WINDOW_DAYS},
        )
        if not isinstance(data, dict):
            self._chart_container.content = self._empty_state("Could not load chart.")
            self._refresh_chart()
            return

        points = data.get("points", [])
        if not points or all(p["amount_cents"] == 0 for p in points):
            self._chart_container.content = self._empty_state(
                f"No revenue yet in the last {self._REVENUE_WINDOW_DAYS} days"
            )
            self._refresh_chart()
            return

        self._chart_container.content = self._build_chart(points)
        self._refresh_chart()

    def _refresh_chart(self) -> None:
        if self.page:
            self._chart_container.update()

    @staticmethod
    def _empty_state(message: str) -> ft.Control:
        return ft.Row(
            [SecondaryText(message)],
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _build_chart(self, points: list[dict[str, Any]]) -> ft.Control:
        """Render a teal-stroked cumulative-revenue area chart.

        The daily series from the endpoint is summed into a running total
        client-side so the line reads as continuous growth (monotonically
        non-decreasing) rather than noisy day-over-day spikes. Empty days
        simply carry the prior day's total forward.
        """
        teal = styles.PulseColors.TEAL
        running = 0.0
        dollars: list[float] = []
        for p in points:
            running += p["amount_cents"] / 100.0
            dollars.append(running)
        max_y = dollars[-1] if dollars else 0.0
        # Round the y-axis ceiling up so the top label isn't flush against
        # the curve's final point.
        y_max = max(10.0, max_y * 1.15)

        data_points = [
            ft.LineChartDataPoint(x=float(i), y=dollars[i]) for i in range(len(dollars))
        ]
        series = ft.LineChartData(
            data_points=data_points,
            stroke_width=2,
            color=teal,
            curved=True,
            stroke_cap_round=True,
            below_line_bgcolor=ft.Colors.with_opacity(0.15, teal),
            below_line_cutoff_y=0.0,
            point=False,
        )

        # Label the first, middle, and last x-ticks only — one per week is
        # too noisy on a 30-day window.
        tick_idxs = {0, len(points) // 2, len(points) - 1}
        x_labels = [
            ft.ChartAxisLabel(
                value=float(i),
                label=ft.Text(
                    _short_date(points[i]["date"]),
                    size=10,
                    color=styles.PulseColors.MUTED,
                ),
            )
            for i in tick_idxs
            if 0 <= i < len(points)
        ]

        return ft.LineChart(
            data_series=[series],
            border=ft.Border(
                bottom=ft.BorderSide(1, styles.PulseColors.BORDER),
                left=ft.BorderSide(1, styles.PulseColors.BORDER),
            ),
            horizontal_grid_lines=ft.ChartGridLines(
                interval=y_max / 4 if y_max else 1,
                color=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                width=1,
            ),
            left_axis=ft.ChartAxis(
                labels=[
                    ft.ChartAxisLabel(
                        value=v,
                        label=ft.Text(
                            f"${v:,.0f}",
                            size=10,
                            color=styles.PulseColors.MUTED,
                        ),
                    )
                    for v in (0.0, y_max / 2, y_max)
                ],
                labels_size=40,
            ),
            bottom_axis=ft.ChartAxis(labels=x_labels, labels_size=20),
            min_y=0.0,
            max_y=y_max,
            min_x=0.0,
            max_x=float(len(points) - 1),
            animate=500,
            expand=True,
        )
