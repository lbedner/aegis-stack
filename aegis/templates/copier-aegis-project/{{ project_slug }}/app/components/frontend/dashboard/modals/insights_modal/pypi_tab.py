"""The PyPI downloads tab."""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.dashboard.modals.insights_modal.base import (
    InsightsTab,
)
from app.components.frontend.dashboard.modals.insights_modal.charts import (
    _pretty_date,
)
from app.components.frontend.dashboard.modals.insights_modal.constants import (
    RANGE_OPTIONS,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.views.formatting import pct as pct_change

from ..modal_sections import (
    ChartColors,
    MetricCard,
    PieChartCard,
)
from .pypi_sections import (
    _daily_table,
    _downloads_chart,
    _version_bars,
)
from .pypi_data import (
    pypi_data,
)

# Event type → chip border/highlight color

# Shared date range options for all tabs

# Milestone category config (for Overview trophy cards)

# Event type to status mapping (for activity feed dot colors)


class PyPITab(InsightsTab):
    """PyPI: real data from database with date range filter.

    Mirrors the aegis-pulse PyPI panel — always shows Total downloads
    (teal, filled) and Human-only downloads (indigo, line on top) on a
    single chart. The CI/mirror split lives in the chart, not behind a
    toggle, since users typically want to see both at once and seeing
    them stacked is the comparison that actually answers the
    "how much real adoption?" question.
    """

    _default_days = 7

    def _build_content(self) -> None:
        """Build or rebuild content for the current date range."""
        data = self._data
        daily = data["daily"]

        # Compute averages from daily data
        bot_pct = data["bot_percent"]
        num_days = len(daily) if daily else 1
        range_label = next(
            (label for label, days in RANGE_OPTIONS if days == self._days),
            f"{self._days}d",
        )

        range_all = sum(d["total"] for d in daily) if daily else 0

        # Headline metric tracks the same number pulse leads with: total
        # downloads (incl. CI/mirror). Human-only is still on the chart
        # — readers who care about real adoption see the indigo line
        # over the teal area and can compare visually.
        total_display = f"{range_all:,}"
        avg_day = range_all // num_days if num_days else 0

        avg_week = avg_day * 7
        avg_month = avg_day * 30

        last_date = daily[-1]["date"] if daily else ""
        content: list[ft.Control] = [
            self._make_filter_bar(last_updated=last_date),
            ft.Container(height=8),
        ]

        # Period-over-period change tracks the headline (total).
        prev_val = data.get("prev_total", 0)
        cur_val = range_all

        # Latest day's value for subtitle
        last_day = daily[-1] if daily else {}
        last_dl = last_day.get("total", 0)
        last_dl_date = last_day.get("date", "")
        from datetime import datetime as _dt

        _dl_days_ago = (
            (_dt.now() - _dt.strptime(last_dl_date, "%Y-%m-%d")).days
            if last_dl_date
            else 0
        )
        _dl_label = (
            "today"
            if _dl_days_ago == 0
            else "yesterday"
            if _dl_days_ago == 1
            else f"{_dl_days_ago}d ago"
        )

        # Metric cards
        metrics_row = ft.Row(
            [
                MetricCard(
                    "Total Downloads",
                    total_display,
                    ChartColors.TEAL,
                    change_pct=pct_change(cur_val, prev_val),
                    prev_value=f"+{last_dl:,} {_dl_label}",
                ),
                MetricCard(
                    "Avg / Day",
                    f"{avg_day:,}",
                    Theme.Colors.INFO,
                    prev_value=f"in {range_label}",
                ),
                MetricCard(
                    "Avg / Week",
                    f"{avg_week:,}",
                    Theme.Colors.SUCCESS,
                    prev_value=f"in {range_label}",
                ),
                MetricCard(
                    "Avg / Month",
                    f"{avg_month:,}",
                    Theme.Colors.PRIMARY,
                    prev_value=f"in {range_label}",
                ),
                MetricCard(
                    "Bot %",
                    f"{bot_pct:.0f}%",
                    Theme.Colors.WARNING if bot_pct > 50 else Theme.Colors.INFO,
                    prev_value=f"in {range_label}",
                ),
            ],
            spacing=Theme.Spacing.MD,
        )
        content.append(metrics_row)

        # Date range + events in window
        if daily:
            date_range = f"{_pretty_date(daily[0]['date'])} \u2014 {_pretty_date(daily[-1]['date'])}"  # noqa: E501
            content.append(ft.Container(height=8))
            content.append(SecondaryText(date_range, size=Theme.Typography.BODY_SMALL))

            # Event chips
            first_date = daily[0]["date"] if daily else ""
            last_date = daily[-1]["date"] if daily else ""
            window_events = [
                (date, label, etype)
                for date, label, etype in data.get("all_events", [])
                if first_date <= date <= last_date
            ]
            chips = self._render_event_chips(window_events)
            if chips:
                content.append(chips)

        # Chart 1: Downloads — always shows both Total (teal, filled
        # area) and Human (indigo, line on top), matching the
        # aegis-pulse PyPI panel exactly. Total is the upper bound, so
        # the y-axis is sized to it.
        _downloads_chart(content, daily, data, self._highlighted_dates)

        # Bar chart: downloads by version
        versions = data["versions"]
        _version_bars(content, versions)

        # Three pie charts in one row
        pie_charts: list[ft.Control] = []

        installers = data["installers"]
        if installers:
            total_inst = sum(installers.values())
            pie_charts.append(
                PieChartCard(
                    title=f"By Installer ({range_label})",
                    sections=[
                        {"value": count, "label": f"{name} ({count / total_inst:.0%})"}
                        for name, count in list(installers.items())[:8]
                    ],
                )
            )

        countries = data["countries"]
        if countries:
            total_c = sum(countries.values())
            pie_charts.append(
                PieChartCard(
                    title=f"By Country ({range_label})",
                    sections=[
                        {"value": count, "label": f"{code} ({count / total_c:.0%})"}
                        for code, count in list(countries.items())[:10]
                    ],
                )
            )

        dist_types = data.get("types", {})
        if dist_types:
            total_t = sum(dist_types.values())
            pie_charts.append(
                PieChartCard(
                    title=f"Dist Type ({range_label})",
                    sections=[
                        {"value": count, "label": f"{name} ({count / total_t:.0%})"}
                        for name, count in dist_types.items()
                    ],
                )
            )

        if pie_charts:
            content.extend(
                [
                    ft.Container(height=8),
                    ft.Row(pie_charts, spacing=Theme.Spacing.MD),
                ]
            )

        # Version table
        versions = data["versions"]
        _daily_table(content, daily, versions, range_label)

        self._content_column.controls = content

    def _load_data(self, days: int = 30) -> dict[str, Any]:
        return pypi_data(self._bulk, days)
