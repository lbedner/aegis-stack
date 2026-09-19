"""The three big cards on the PyPI tab.

Each takes the control list it appends to, so the tab reads as the
order the cards appear in rather than three hundred lines of
chart construction.
"""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    SecondaryText,
)
from app.components.frontend.dashboard.modals.insights_modal.charts import (
    _make_legend,
    _make_line_chart,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import (
    ChartColors,
    ChartPoint,
)
from .pypi_data import (
    bot_share_label,
    split_downloads,
    version_sort_key,
)

# The human/bot split reads green against red wherever it appears in
# this tab. These are not the theme's SUCCESS and ERROR - those are
# #17CCBF and #D32F2F - so they are named here rather than swapped,
# which would change what the tab looks like.
HUMAN_COLOR = "#22C55E"
BOT_COLOR = "#EF4444"

# Above this share of bot traffic the percentage itself turns red.
BOT_SHARE_ALARM = 0.8


def _downloads_chart(
    content: list[Any], daily: Any, data: dict[str, Any], highlighted_dates: Any
) -> None:
    """The download curve, with release days marked."""
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
        highlighted = highlighted_dates

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
                release_points.append(ft.LineChartDataPoint(i, 0, show_tooltip=False))

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


def _version_bars(content: list[Any], versions: Any) -> None:
    """Downloads per version, as a bar row."""
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
                        label=ft.Text(ver, size=8, color=ft.Colors.ON_SURFACE_VARIANT),
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

        bar_wrapped = ft.Container(content=version_bar, margin=ft.margin.only(right=20))
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


def _daily_table(
    content: list[Any], daily: Any, versions: Any, range_label: str
) -> None:
    """Day by day, with the bot share beside each count."""
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
            pct_color = BOT_COLOR if t > 0 and b / t > BOT_SHARE_ALARM else HUMAN_COLOR
            version_rows_data.append(
                [
                    ver,
                    f"{t:,}",
                    ft.Text(f"{h:,}", color=HUMAN_COLOR, size=12),
                    ft.Text(f"{b:,}", color=BOT_COLOR, size=12),
                    ft.Text(pct, color=pct_color, size=12, weight=ft.FontWeight.W_600),
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
