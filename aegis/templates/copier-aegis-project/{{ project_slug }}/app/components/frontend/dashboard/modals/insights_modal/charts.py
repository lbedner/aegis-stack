"""Chart primitives and axis helpers shared by the data tabs."""

from __future__ import annotations  # noqa: I001


import flet as ft

from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import ChartColors


# Event type → chip border/highlight color
EVENT_TYPE_COLORS: dict[str, str] = {
    "release": "#22C55E",
    "fork": "#A855F7",
    "star": "#F59E0B",
    "reddit_post": "#FF5722",
    "localization": "#3B82F6",
    "feature": "#06B6D4",
    "milestone_github": "#EC4899",
    "milestone_pypi": "#EC4899",
    "anomaly_github": "#EF4444",
    "external": "#9CA3AF",
}

# Shared date range options for all tabs
RANGE_OPTIONS = [
    ("7d", 7),
    ("14d", 14),
    ("1m", 30),
    ("3m", 90),
    ("6m", 180),
    ("1y", 365),
    ("All", 9999),
]

# Milestone category config (for Overview trophy cards)
CATEGORY_CONFIG: dict[str, dict[str, str]] = {
    "daily_clones": {"label": "GitHub 1-Day Clones", "color": "#2563eb"},
    "daily_unique": {"label": "GitHub 1-Day Unique", "color": "#A855F7"},
    "daily_views": {"label": "GitHub 1-Day Views", "color": "#22C55E"},
    "daily_visitors": {"label": "GitHub 1-Day Visitors", "color": "#F59E0B"},
    "14d_clones": {"label": "GitHub 14-Day Clones", "color": "#06B6D4"},
    "14d_unique": {"label": "GitHub 14-Day Unique", "color": "#EC4899"},
    "14d_visitors": {"label": "GitHub 14-Day Visitors", "color": "#F97316"},
    "pypi_daily": {"label": "PyPI Best Single Day", "color": "#EF4444"},
    "plausible_daily_visitors": {"label": "Docs 1-Day Visitors", "color": "#6366F1"},
    "plausible_daily_pageviews": {"label": "Docs 1-Day Pageviews", "color": "#22C55E"},
    "star_daily": {"label": "Stars Best Day", "color": "#FFD700"},
    "star_monthly": {"label": "Stars Best Month", "color": "#FFD700"},
}

# Event type to status mapping (for activity feed dot colors)
EVENT_STATUS_MAP: dict[str, str] = {
    "release": "success",
    "star": "warning",
    "reddit_post": "info",
    "milestone_github": "warning",
    "milestone_pypi": "warning",
    "feature": "info",
    "anomaly_github": "error",
    "external": "info",
}


def _make_line_chart(
    data_series: list,
    max_y: float,
    daily: list[dict],
    step: int,
    min_y: float = 0,
    height: int = 350,
) -> ft.LineChart:
    """Build a standard line chart with shared tooltip/grid/border config."""
    return ft.LineChart(
        data_series=data_series,
        left_axis=ft.ChartAxis(labels_size=50, labels_interval=step),
        bottom_axis=ft.ChartAxis(
            labels_size=50,
            labels=[
                ft.ChartAxisLabel(
                    value=i,
                    label=ft.Text(
                        d["date"][-5:], size=9, color=ft.Colors.ON_SURFACE_VARIANT
                    ),
                )
                for i, d in enumerate(daily)
                if i % max(1, len(daily) // 8) == 0 or i == len(daily) - 1
            ],
        ),
        horizontal_grid_lines=ft.ChartGridLines(
            interval=step,
            color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
            width=1,
        ),
        tooltip_bgcolor=Theme.Colors.SURFACE_1,
        tooltip_rounded_radius=8,
        tooltip_padding=10,
        tooltip_max_content_width=200,
        tooltip_tooltip_border_side=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        tooltip_fit_inside_vertically=True,
        tooltip_fit_inside_horizontally=True,
        tooltip_show_on_top_of_chart_box_area=True,
        point_line_start=0,
        point_line_end=float("inf"),
        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        interactive=True,
        min_y=min_y,
        max_y=max_y,
        min_x=0,
        max_x=len(daily) - 1,
        height=height,
        expand=True,
    )


def _make_legend(items: list[tuple[str, str]]) -> ft.Row:
    """Build chart legend. items = [(color, label), ...]"""
    return ft.Row(
        [
            ft.Row(
                [
                    ft.Container(width=10, height=10, bgcolor=color, border_radius=5),
                    SecondaryText(label, size=Theme.Typography.BODY_SMALL),
                ],
                spacing=4,
            )
            for color, label in items
        ],
        spacing=16,
        alignment=ft.MainAxisAlignment.CENTER,
    )


def _smart_step(max_val: float) -> int:
    """Pick a nice y-axis interval based on magnitude."""
    if max_val <= 20:
        return 5
    if max_val <= 100:
        return 10
    if max_val <= 500:
        return 50
    return 100


def _pretty_date(date_str: str) -> str:
    """Format '2026-04-03' as 'April 3rd, 2026'."""
    from datetime import datetime as dt

    try:
        d = dt.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str

    day = d.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return d.strftime(f"%B {day}{suffix}, %Y")


def bounds_with_padding(values: list[float]) -> tuple[int, int]:
    """Y-range for a bar chart whose bars are all nearly the same height.

    Anchoring at zero would render seven near-identical bars; padding
    below the minimum and above the maximum is what makes the shape
    readable. The pad is proportional, with a floor of 1 so a flat
    series still has an axis to sit in.
    """
    low, high = min(values), max(values)
    spread = high - low
    pad_bottom = max(spread * 0.3, 1)
    pad_top = max(spread * 0.15, 1)
    return max(0, int(low - pad_bottom)), int(high + pad_top + 0.5)


def emphasis_color(value: float, low: float, high: float) -> str:
    """Peak, trough, or neither.

    Colouring the extremes is what lets the eye find the rhythm without
    comparing seven bars by length.
    """
    if value == high:
        return ChartColors.TEAL
    if value == low:
        return ChartColors.VIOLET
    return ft.Colors.with_opacity(0.55, ChartColors.TEAL)


def axis_tick_labels(low: int, high: int, step: int) -> list[ft.ChartAxisLabel]:
    """Y-axis ticks from the first multiple of ``step`` at or above
    ``low``.

    Rendered explicitly rather than left to Flet, whose auto-labels are
    larger and use the default text colour, so an axis styled this way
    would not match the one below it.
    """
    if step <= 0:
        return []
    remainder = low % step
    tick = low + (step - remainder if remainder else 0)
    labels: list[ft.ChartAxisLabel] = []
    while tick <= high:
        labels.append(
            ft.ChartAxisLabel(
                value=tick,
                label=ft.Text(
                    f"{int(tick):,}", size=9, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            )
        )
        tick += step
    return labels


def trim_leading_zeros(daily: list[dict], *keys: str) -> list[dict]:
    """Drop the run of days before a series has anything to show.

    A repository with no clones for its first month should not open on a
    month of flat zero; the line starts where the data does. Days are
    kept from the first one where any of ``keys`` is non-zero.
    """
    for index, day in enumerate(daily):
        if any(day.get(key) for key in keys):
            return daily[index:]
    return daily
