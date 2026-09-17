"""The PyPI downloads tab."""

from __future__ import annotations  # noqa: I001


import flet as ft

from app.components.frontend.dashboard.modals.insights_modal.constants import (
    RANGE_OPTIONS,
)

from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.views.formatting import pct as pct_change
from app.services.insights.views.events import (
    PYPI_EVENT_TYPES,
)

from ..modal_sections import (
    ChartColors,
    ChartPoint,
    MetricCard,
    PieChartCard,
)
from app.components.frontend.dashboard.modals.insights_modal.base import (
    InsightsTab,
)
from app.components.frontend.dashboard.modals.insights_modal.charts import (
    _make_legend,
    _make_line_chart,
    _pretty_date,
)


# Event type → chip border/highlight color

# Shared date range options for all tabs

# Milestone category config (for Overview trophy cards)

# Event type to status mapping (for activity feed dot colors)


# The human/bot split reads green against red wherever it appears in
# this tab. These are not the theme's SUCCESS and ERROR - those are
# #17CCBF and #D32F2F - so they are named here rather than swapped,
# which would change what the tab looks like.
HUMAN_COLOR = "#22C55E"
BOT_COLOR = "#EF4444"

# Above this share of bot traffic the percentage itself turns red.
BOT_SHARE_ALARM = 0.8


def version_sort_key(version: str) -> tuple[int, ...]:
    """Order versions roughly by release, for the downloads chart.

    Pre-release markers become separators, so 1.2.0rc1 reads as
    (1, 2, 0, 1). That puts it AFTER 1.2.0 rather than before it, which
    is backwards for a release candidate - the shorter tuple always
    wins. Behaviour preserved from when this was a nested function;
    worth fixing, but it reorders bars in a chart, so not quietly.

    Anything that is not a number sorts as zero rather than raising: a
    version string is whatever the index was given.
    """
    parts = version.replace("rc", ".").replace("a", ".").replace("b", ".").split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def split_downloads(info: dict | int) -> tuple[int, int, int]:
    """Total, human and bot counts for one version.

    Older rows carry a bare total rather than a breakdown, so an int
    means "all total, no attribution known" rather than zero humans.
    """
    if isinstance(info, dict):
        total, human = info.get("total", 0), info.get("human", 0)
    else:
        total, human = info, 0
    return total, human, total - human


def bot_share_label(total: int, bot: int) -> str:
    """Bot share as a percentage, or an em-dash when there is nothing
    to take a share of."""
    if total <= 0:
        return "\u2014"
    return f"{bot / total * 100:.0f}%"


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
        releases = data.get("releases", {})
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
        if daily:
            max_val = max(d["total"] for d in daily)

            # Smart rounding: small values round to nearest 5, medium to 25, large to 100  # noqa: E501
            if max_val <= 20:
                step = 5
            elif max_val <= 100:
                step = 10
            elif max_val <= 500:
                step = 50
            else:
                step = 100
            rounded_max = int((max_val // step + 1) * step)

            releases = data.get("releases", {})
            highlighted = self._highlighted_dates

            total_points: list[ft.LineChartDataPoint] = []
            human_points: list[ft.LineChartDataPoint] = []
            release_points: list[ft.LineChartDataPoint] = []
            for i, d in enumerate(daily):
                is_hl = d["date"] in highlighted
                point_style = ChartPoint.highlight() if is_hl else None
                total_points.append(
                    ft.LineChartDataPoint(
                        i,
                        d["total"],
                        tooltip=f"Total: {d['total']:,}",
                        point=point_style,
                    )
                )
                human_points.append(
                    ft.LineChartDataPoint(
                        i,
                        d["human"],
                        tooltip=f"Human: {d['human']:,}",
                    )
                )

                rel = releases.get(d["date"])
                if rel:
                    release_points.append(
                        ft.LineChartDataPoint(i, 0, tooltip=f"{rel}", show_tooltip=True)
                    )
                else:
                    release_points.append(
                        ft.LineChartDataPoint(i, 0, show_tooltip=False)
                    )

            chart1_series = [
                # Total = teal filled area (pulse THEME.teal #17CCBF)
                ft.LineChartData(
                    data_points=total_points,
                    stroke_width=2,
                    color=ChartColors.TEAL,
                    below_line_bgcolor=ft.Colors.with_opacity(0.15, ChartColors.TEAL),
                    curved=True,
                    stroke_cap_round=True,
                ),
                # Human = indigo line on top (pulse THEME.indigo #6366F1)
                ft.LineChartData(
                    data_points=human_points,
                    stroke_width=2,
                    color=ChartColors.INDIGO,
                    curved=True,
                    stroke_cap_round=True,
                ),
                # Release annotations — invisible series, tooltip-only
                ft.LineChartData(
                    data_points=release_points,
                    stroke_width=0,
                    color="#9CA3AF",
                ),
            ]

            chart1 = _make_line_chart(chart1_series, rounded_max, daily, step)
            legend1 = _make_legend(
                [
                    (ChartColors.TEAL, "Total"),
                    (ChartColors.INDIGO, "Human"),
                ]
            )

            chart1_wrapped = ft.Container(
                content=chart1,
                margin=ft.margin.only(right=20),
            )
            content.extend([ft.Container(height=8), chart1_wrapped, legend1])

        # Bar chart: downloads by version
        versions = data["versions"]
        if versions:
            # Only versions anyone actually downloaded, in release order.
            sorted_versions = [
                ver
                for ver in sorted(versions, key=version_sort_key)
                if split_downloads(versions[ver])[0] > 0
            ]

            bar_groups = []
            bar_max = 0
            for i, ver in enumerate(sorted_versions):
                val, _, _ = split_downloads(versions[ver])
                bar_max = max(bar_max, val)

                bar_groups.append(
                    ft.BarChartGroup(
                        x=i,
                        bar_rods=[
                            ft.BarChartRod(
                                from_y=0,
                                to_y=val,
                                width=max(8, 400 // len(sorted_versions)),
                                color=ChartColors.TEAL,
                                border_radius=ft.border_radius.only(
                                    top_left=3, top_right=3
                                ),
                                tooltip=f"{ver}: {val:,}",
                            )
                        ],
                    )
                )

            bar_rounded_max = int(bar_max * 1.15) + 1 if bar_max > 0 else 10

            # Show every Nth label to avoid overlap
            label_step = max(1, len(sorted_versions) // 12)

            version_bar = ft.BarChart(
                bar_groups=bar_groups,
                left_axis=ft.ChartAxis(
                    labels_size=50, labels_interval=max(1, bar_rounded_max // 4)
                ),
                bottom_axis=ft.ChartAxis(
                    labels_size=50,
                    labels=[
                        ft.ChartAxisLabel(
                            value=i,
                            label=ft.Text(
                                ver, size=8, color=ft.Colors.ON_SURFACE_VARIANT
                            ),
                        )
                        for i, ver in enumerate(sorted_versions)
                        if i % label_step == 0 or i == len(sorted_versions) - 1
                    ],
                ),
                horizontal_grid_lines=ft.ChartGridLines(
                    interval=bar_rounded_max // 4 or 1,
                    color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                    width=1,
                ),
                tooltip_bgcolor=Theme.Colors.SURFACE_1,
                tooltip_rounded_radius=8,
                tooltip_padding=10,
                tooltip_tooltip_border_side=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                max_y=bar_rounded_max,
                height=250,
                expand=True,
            )

            bar_wrapped = ft.Container(
                content=version_bar, margin=ft.margin.only(right=20)
            )
            bar_legend = ft.Row(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=10,
                                height=10,
                                bgcolor=ChartColors.TEAL,
                                border_radius=5,
                            ),
                            SecondaryText(
                                "Downloads by Version",
                                size=Theme.Typography.BODY_SMALL,
                            ),
                        ],
                        spacing=4,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            )

            content.extend([ft.Container(height=12), bar_wrapped, bar_legend])

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
        if versions:
            from app.components.frontend.controls.data_table import (
                DataTable,
                DataTableColumn,
            )

            version_columns = [
                DataTableColumn(header="Version", width=100, style="primary"),
                DataTableColumn(header="Total", width=80, alignment="right"),
                DataTableColumn(header="Human", width=80, alignment="right"),
                DataTableColumn(header="Bot", width=80, alignment="right"),
                DataTableColumn(header="Bot %", width=70, alignment="right"),
            ]

            version_rows_data = []
            for ver, info in list(versions.items())[:10]:
                t, h, b = split_downloads(info)
                pct = bot_share_label(t, b)
                pct_color = (
                    BOT_COLOR if t > 0 and b / t > BOT_SHARE_ALARM else HUMAN_COLOR
                )
                version_rows_data.append(
                    [
                        ver,
                        f"{t:,}",
                        ft.Text(f"{h:,}", color=HUMAN_COLOR, size=12),
                        ft.Text(f"{b:,}", color=BOT_COLOR, size=12),
                        ft.Text(
                            pct, color=pct_color, size=12, weight=ft.FontWeight.W_600
                        ),
                    ]
                )

            # Totals row
            splits = [split_downloads(info) for info in versions.values()]
            total_t = sum(s[0] for s in splits)
            total_h = sum(s[1] for s in splits)
            total_b = total_t - total_h
            total_pct = bot_share_label(total_t, total_b)

            version_rows_data.append(
                [
                    ft.Text("TOTAL", size=12, weight=ft.FontWeight.W_700),
                    ft.Text(f"{total_t:,}", size=12, weight=ft.FontWeight.W_700),
                    ft.Text(
                        f"{total_h:,}",
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color=HUMAN_COLOR,
                    ),
                    ft.Text(
                        f"{total_b:,}",
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color=BOT_COLOR,
                    ),
                    ft.Text(
                        total_pct,
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color=BOT_COLOR
                        if total_t > 0 and total_b / total_t > 0.8
                        else HUMAN_COLOR,
                    ),
                ]
            )

            version_table = DataTable(
                columns=version_columns,
                rows=version_rows_data,
            )

            # Daily downloads table (sorted by highest day)
            daily_columns = [
                DataTableColumn(header="Date", width=80, style="primary"),
                DataTableColumn(header="Total", width=70, alignment="right"),
                DataTableColumn(header="Human", width=70, alignment="right"),
                DataTableColumn(header="Bot", width=70, alignment="right"),
            ]

            sorted_days = sorted(daily, key=lambda d: d["date"], reverse=True)
            daily_rows_data = []
            for d in sorted_days:
                bot = d["total"] - d["human"]
                daily_rows_data.append(
                    [
                        d["date"][-5:],
                        f"{d['total']:,}",
                        ft.Text(f"{d['human']:,}", color=HUMAN_COLOR, size=12),
                        ft.Text(f"{bot:,}", color=BOT_COLOR, size=12),
                    ]
                )

            daily_table = DataTable(
                columns=daily_columns,
                rows=daily_rows_data,
                scroll_height=400,
            )

            content.extend(
                [
                    ft.Container(height=12),
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    H3Text(f"Downloads by Version ({range_label})"),
                                    version_table,
                                ],
                                expand=True,
                            ),
                            ft.Column(
                                [
                                    H3Text(f"Daily Downloads ({range_label})"),
                                    daily_table,
                                ],
                                expand=True,
                            ),
                        ],
                        spacing=Theme.Spacing.LG,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ]
            )

        self._content_column.controls = content

    def _load_data(self, days: int = 14) -> dict:
        """Load PyPI data from bulk pre-loaded data."""
        from app.services.insights.domains.metrics import InsightQueryService

        cutoff, prev_cutoff = InsightQueryService.compute_cutoffs(days)

        # Total
        total_row = self._bulk.latest.get("downloads_total")
        total = int(total_row.value) if total_row else 0

        # Daily total + human
        daily_rows = [
            r for r in self._bulk.daily.get("downloads_daily", []) if r.date >= cutoff
        ]
        human_rows = [
            r
            for r in self._bulk.daily.get("downloads_daily_human", [])
            if r.date >= cutoff
        ]
        human_map = {str(r.date)[:10]: int(r.value) for r in human_rows}

        daily = []
        for r in daily_rows:
            day = str(r.date)[:10]
            t = int(r.value)
            h = human_map.get(day, 0)
            daily.append({"date": day, "total": t, "human": h})

        today_total = daily[-1]["total"] if daily else 0
        today_human = daily[-1]["human"] if daily else 0

        # Bot % computed over entire selected range
        range_total = sum(d["total"] for d in daily)
        range_human = sum(d["human"] for d in daily)
        bot_pct = (
            ((range_total - range_human) / range_total * 100) if range_total > 0 else 0
        )

        # Latest installer breakdown (aggregate from all days)
        all_installers: dict[str, int] = {}
        for r in [
            r
            for r in self._bulk.daily.get("downloads_by_installer", [])
            if r.date >= cutoff
        ]:
            meta = r.metadata_ or {}
            for name, count in meta.get("installers", {}).items():
                all_installers[name] = all_installers.get(name, 0) + count
        installers = dict(sorted(all_installers.items(), key=lambda x: -x[1]))

        # Latest country breakdown (aggregate)
        all_countries: dict[str, int] = {}
        for r in [
            r
            for r in self._bulk.daily.get("downloads_by_country", [])
            if r.date >= cutoff
        ]:
            meta = r.metadata_ or {}
            for code, count in meta.get("countries", {}).items():
                all_countries[code] = all_countries.get(code, 0) + count
        countries = dict(sorted(all_countries.items(), key=lambda x: -x[1]))

        # Per-day per-version data
        version_daily_rows = [
            r
            for r in self._bulk.daily.get("downloads_by_version", [])
            if r.date >= cutoff
        ]
        version_daily: dict[str, dict[str, int]] = {}
        for r in version_daily_rows:
            day = str(r.date)[:10]
            meta = r.metadata_ or {}
            day_versions = meta.get("versions", {})
            version_daily[day] = {
                ver: split_downloads(info)[0] for ver, info in day_versions.items()
            }

        # Version breakdown with real human/bot
        versions: dict[str, dict[str, int]] = {}
        for r in version_daily_rows:
            meta = r.metadata_ or {}
            for ver, info in meta.get("versions", {}).items():
                total, human, _ = split_downloads(info)
                running = versions.setdefault(ver, {"total": 0, "human": 0})
                running["total"] += total
                running["human"] += human
        versions = dict(sorted(versions.items(), key=lambda x: -x[1]["total"]))

        # Distribution type breakdown
        all_types: dict[str, int] = {}
        for r in [
            r for r in self._bulk.daily.get("downloads_by_type", []) if r.date >= cutoff
        ]:
            meta = r.metadata_ or {}
            for t, count in meta.get("types", {}).items():
                all_types[t] = all_types.get(t, 0) + count
        dist_types = dict(sorted(all_types.items(), key=lambda x: -x[1]))

        # Events for chart annotations
        all_events: list[tuple[str, str, str]] = []
        for r in self._bulk.events.get("releases", []):
            tag = (r.metadata_ or {}).get("tag", "")
            if tag:
                all_events.append((str(r.date)[:10], tag, "release"))
        for ev in [
            ev for ev in self._bulk.insight_events if ev.event_type in PYPI_EVENT_TYPES
        ]:
            all_events.append((str(ev.date)[:10], ev.description[:60], ev.event_type))

        release_map: dict[str, str] = {}
        for date, label, _ in all_events:
            if date in release_map:
                release_map[date] += f"\n{label}"
            else:
                release_map[date] = label

        return {
            "total": total,
            "today_total": today_total,
            "today_human": today_human,
            "bot_percent": bot_pct,
            "prev_total": sum(
                int(r.value)
                for r in self._bulk.daily.get("downloads_daily", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "prev_human": sum(
                int(r.value)
                for r in self._bulk.daily.get("downloads_daily_human", [])
                if prev_cutoff <= r.date < cutoff
            ),
            "daily": daily,
            "version_daily": version_daily,
            "installers": installers,
            "countries": countries,
            "versions": versions,
            "types": dist_types,
            "releases": release_map,
            "all_events": all_events,
        }
