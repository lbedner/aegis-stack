"""The pieces every chart card is built from: palette, series, axis maths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import flet as ft
from app.components.frontend.theme import AegisTheme as Theme


class ChartColors:
    """Aegis chart palette.

    The cool ramp (teal -> sky) is the data palette - primary series gets
    teal, the second series picks the next ramp color that gives the most
    perceptual separation. Warm signals (amber, success, error) stay
    sparing, reserved for highlight / delta semantics.
    """

    # Brand / primary
    TEAL = "#17CCBF"

    # Cool ramp - used in this order for multi-series charts
    CYAN = "#06B6D4"
    BLUE = "#3B82F6"
    INDIGO = "#6366F1"
    VIOLET = "#8B5CF6"
    PURPLE = "#A855F7"
    SKY = "#0EA5E9"

    # Warm signals - highlight / delta only, never the default series color
    AMBER = "#F59E0B"
    SUCCESS = "#22C55E"
    ERROR = "#EF4444"

    # Legacy aliases - kept so any code that referenced the older pink
    # accent for releases keeps rendering
    PINK = "#EC4899"

    # Muted fallback (also used as the secondary surface text token in
    # the htmx side; reused here as the palette's "neutral" slot)
    MUTED = "#7E8A9A"


def chart_tooltip_kwargs() -> dict[str, Any]:
    """Shared tooltip styling for any chart control (LineChart, BarChart).

    Filled SURFACE_1 panel with the same outline-variant border used by
    every card surface in the modal. Use as ``**kwargs`` on the chart
    constructor; chart-specific extras (e.g. LineChart's
    ``tooltip_show_on_top_of_chart_box_area``) layer in alongside.
    """
    # NB: Flet's constructor kwarg is `tooltip_tooltip_border_side` even
    # though the runtime attribute is `tooltip_border_side`. Passing the
    # short form raises `TypeError: ... got an unexpected keyword argument
    # 'tooltip_border_side'` on Flet 0.28. Keep the doubled prefix.
    return {
        "tooltip_bgcolor": Theme.Colors.SURFACE_1,
        "tooltip_tooltip_border_side": ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        "tooltip_rounded_radius": 8,
        "tooltip_padding": 10,
        "tooltip_max_content_width": 200,
        "tooltip_fit_inside_vertically": True,
        "tooltip_fit_inside_horizontally": True,
    }


class ChartPoint:
    """Standard chart-point shapes used by every chart in the modal.

    ``ft.ChartCirclePoint`` is a Flet value type, not a Control - it can't
    be subclassed via the component model - so this class is a namespace
    of factory methods rather than a real custom control. Compose them
    directly into ``ft.LineChartData(point=...)`` or
    ``ft.LineChartDataPoint(point=...)`` so every chart in the project
    uses the same point geometry without re-defining radii/strokes inline.
    """

    @staticmethod
    def dot(color: str = ft.Colors.ON_SURFACE) -> ft.ChartCirclePoint:
        """Small marker drawn at every data point on a visible series.

        Default color is the on-surface foreground so the dots read on
        any line color. Pass the line color (or any other) to bias the
        dot toward / away from the curve.
        """
        return ft.ChartCirclePoint(radius=3, color=color, stroke_width=0)

    @staticmethod
    def highlight(
        color: str = ChartColors.AMBER,
    ) -> ft.ChartCirclePoint:
        """Larger marker for points that match a selected event chip on
        the parent tab. Stroked in the on-surface color so it pops on
        any series color underneath."""
        return ft.ChartCirclePoint(
            radius=7,
            color=color,
            stroke_width=2,
            stroke_color=ft.Colors.ON_SURFACE,
        )


@dataclass(frozen=True)
class LineSeries:
    """One line on a `LineChartCard`.

    `points` is a list of (x_index, y_value) pairs - x is the position
    on the shared date axis owned by the parent card, y is whatever the
    metric is. `tooltips` is parallel to `points`; ``None`` means no
    per-point tooltip.

    `fill=True` paints a 15%-opacity area under the line - the
    star-history / hero-trend treatment. `stroke_width` defaults to 2;
    bump to 3 for headline series that should read above the others.
    `show_in_legend=False` hides the series from the legend (used for
    annotation overlays like release markers that aren't real data).

    `highlighted_indices` marks specific data points (by their index in
    `points`) for emphasis - typically driven by event-chip selection on
    the parent tab. Each marked point renders as a 7-px circle in
    `highlight_color` so the viewer's eye is drawn to dates that
    correspond to the currently selected event chip on the parent tab.
    """

    label: str
    color: str
    points: list[tuple[int, float]]
    fill: bool = False
    stroke_width: int = 2
    tooltips: list[str] | None = None
    show_in_legend: bool = True
    # Polarity split: colour the stroke ``color`` above this y and
    # ``split_below_color`` below it (hard stop, no blend), with the fill
    # tinting the area between the line and the split on each side. One
    # series, so tooltips and hover are untouched. ``None`` = plain line.
    split_y: float | None = None
    split_below_color: str = "#EF4444"  # ChartColors.ERROR - self-contained
    highlighted_indices: frozenset[int] = field(default_factory=frozenset)
    highlight_color: str = (
        "#F59E0B"  # ChartColors.AMBER - keep dataclass self-contained
    )


@dataclass
class BarSeries:
    """One measure across the grouped bars (e.g. income, or spend)."""

    label: str
    color: str
    values: list[float]


@dataclass
class RankedBar:
    """One row of a ranked bar list: what, how much, and an aside."""

    label: str
    value: float
    display: str
    meta: str = ""


def diverging_stop(*, floor: float, ceiling: float, split: float) -> float:
    """How far DOWN the plot (0=top, 1=bottom) a split line sits.

    The fraction feeds a vertical gradient's hard stop, so the stroke
    changes colour exactly where it crosses ``split``. Clamped results
    carry meaning: >= 1 means the whole range is above the split (no
    gradient needed), <= 0 means all of it is below.
    """
    span = ceiling - floor
    if span <= 0:
        return 1.0
    return (ceiling - split) / span


def chart_floor(values: list[float]) -> float:
    """A y-axis floor that lets a trend read as a trend.

    Anchoring at zero is only right when zero is near the data. A series that
    lives in a tight band far above it - net worth wandering between $287k and
    $300k - gets squashed into the top few percent of the plot, and a filled
    series then draws the remaining 96% as a solid block. Sit the floor just
    under the low point instead.

    Clamped at zero for an all-positive series, so padding below a small low
    never draws a chart implying the balance went into the red.
    """
    if not values:
        return 0.0
    low, high = min(values), max(values)
    span = high - low
    # A dead-flat series has no span to take a fraction of, but still needs a
    # band, or the line is drawn along the axis itself.
    pad = span * 0.1 if span else max(abs(high) * 0.05, 1.0)
    floor = low - pad
    return max(0.0, floor) if low >= 0 else floor


def axis_label_positions(count: int, ticks: int = 8) -> list[int]:
    """Evenly spaced x-positions to label, always including the last one.

    The final date is the one people look for, so it is always labelled. The
    tick before it is dropped when the two would land on top of each other:
    90 days on an 8-tick grid puts a tick at index 88 and the last at 89, which
    renders as two dates overprinted on each other.
    """
    if count <= 0:
        return []
    step = max(1, count // ticks)
    positions = list(range(0, count, step))
    last = count - 1
    if positions and last - positions[-1] < step:
        positions.pop()
    if not positions or positions[-1] != last:
        positions.append(last)
    return positions
