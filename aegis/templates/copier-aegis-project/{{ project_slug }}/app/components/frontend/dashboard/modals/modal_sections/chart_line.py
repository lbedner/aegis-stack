"""The line chart card."""

from __future__ import annotations

from typing import Any

import flet as ft
from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    ChartPoint,
    LineSeries,
    axis_label_positions,
    chart_tooltip_kwargs,
    diverging_stop,
)
from app.components.frontend.theme import AegisTheme as Theme


class LineChartCard(ft.Container):
    """Card-styled line chart with a title, optional subtitle, the chart
    body, and a legend. Owns its own surface treatment (matches
    `MetricCard`: SURFACE_CONTAINER_HIGHEST, 0.5px OUTLINE border, the
    standard CARD_RADIUS) so a tab composing this control doesn't have
    to wrap it again.

    Example:
        LineChartCard(
            title="Daily Cloners",
            subtitle="unique people / clones per day",
            x_labels=[d.date for d in daily],
            series=[
                LineSeries(
                    label="Clones",
                    color="#2563eb",
                    points=[(i, d.clones) for i, d in enumerate(daily)],
                    tooltips=[f"Clones: {d.clones:,}" for d in daily],
                ),
                LineSeries(
                    label="Unique Cloners",
                    color="#7c3aed",
                    points=[(i, d.unique_cloners) for i, d in enumerate(daily)],
                ),
            ],
        )
    """

    def __init__(
        self,
        *,
        title: str,
        series: list[LineSeries],
        x_labels: list[str],
        subtitle: str = "",
        # 214 + the 24px bottom-label band = the same plot area the old
        # 240 gave when the band was 50px of mostly dead space.
        height: int = 214,
        min_y: float = 0,
        event_annotations: list[list[str]] | None = None,
    ) -> None:
        super().__init__()

        # The y-ceiling every series shares: fl_chart's auto max is the
        # data max, and the diverging split needs the same number to place
        # its gradient stop.
        ceiling = max((y for s in series for _x, y in s.points), default=0.0)
        chart_data: list[ft.LineChartData] = [
            self._make_series(s, floor=min_y, ceiling=ceiling) for s in series
        ]

        # Event-annotation overlay. When the parent tab passes a list of
        # event labels per x-position, we render a transparent series at
        # ``min_y`` whose only job is to surface a muted-grey tooltip
        # entry on dates that have events. Each event-bearing point gets
        # an invisible (transparent) ChartCirclePoint so Flet has a real
        # hover target - without it, a stroke_width=0 series sometimes
        # gets dropped from the multi-series tooltip stack on hover.
        if event_annotations is not None:
            overlay_points: list[ft.LineChartDataPoint] = []
            muted_style = ft.TextStyle(
                color=ft.Colors.ON_SURFACE_VARIANT,
                size=Theme.Typography.BODY_SMALL,
            )
            for i, evs in enumerate(event_annotations):
                if evs:
                    overlay_points.append(
                        ft.LineChartDataPoint(
                            i,
                            min_y,
                            tooltip="\n".join(evs),
                            show_tooltip=True,
                            tooltip_style=muted_style,
                            point=ft.ChartCirclePoint(
                                radius=2,
                                color=ft.Colors.TRANSPARENT,
                                stroke_width=0,
                            ),
                        )
                    )
                else:
                    overlay_points.append(
                        ft.LineChartDataPoint(i, min_y, show_tooltip=False)
                    )
            chart_data.append(
                ft.LineChartData(
                    data_points=overlay_points,
                    stroke_width=0,
                    color=ft.Colors.TRANSPARENT,
                )
            )

        # Y-axis range - driven by the visible (legend-shown) series so
        # annotation overlays at y=0 don't squash the scale.
        visible_values = [y for s in series if s.show_in_legend for _, y in s.points]
        max_val = max(visible_values) if visible_values else 1
        step = self._smart_step(max_val - min_y)
        max_y = int((max_val // step + 1) * step) if step else int(max_val + 1)

        # Bottom-axis labels: reuse just the date strings; the parent
        # owns the x-coordinate semantics.
        labelled = set(axis_label_positions(len(x_labels)))
        bottom_labels = [
            ft.ChartAxisLabel(
                value=i,
                label=NumericText(
                    label[-5:], size=9, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            )
            for i, label in enumerate(x_labels)
            if i in labelled
        ]

        # Y-axis ticks rendered explicitly so they pick up the same
        # small + muted styling as the bottom axis. Without this, Flet
        # falls back to its default-styled auto-labels which are larger
        # and use the default text color.
        left_labels = []
        if step > 0:
            tick = int(min_y) + (step - (int(min_y) % step) if int(min_y) % step else 0)
            while tick <= max_y:
                left_labels.append(
                    ft.ChartAxisLabel(
                        value=tick,
                        label=NumericText(
                            f"{int(tick):,}",
                            size=9,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    )
                )
                tick += step

        # A polarity-split chart must not run fl_chart's implicit data
        # animation: on an in-place update the lerp interpolates the axis
        # bounds and the gradient stops out of sync, and for ~150ms the
        # red below-zero band paints across the top of the plot before
        # settling (confirmed live on the Projected tab). Plain charts
        # have a single colour, so their lerp has nothing to mis-blend
        # and they keep the default animation.
        has_split = any(s.split_y is not None for s in series)
        chart = ft.LineChart(
            animate=ft.Animation(duration=0) if has_split else None,
            data_series=chart_data,
            left_axis=ft.ChartAxis(labels_size=50, labels=left_labels),
            # 24px hugs the 9px date labels; 50 left a dead band between
            # the labels and whatever sits under the chart.
            bottom_axis=ft.ChartAxis(labels_size=24, labels=bottom_labels),
            horizontal_grid_lines=ft.ChartGridLines(
                interval=step,
                color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                width=1,
            ),
            **chart_tooltip_kwargs(),
            tooltip_show_on_top_of_chart_box_area=True,
            point_line_start=0,
            point_line_end=float("inf"),
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
            interactive=True,
            min_y=min_y,
            max_y=max_y,
            min_x=0,
            max_x=max(0, len(x_labels) - 1),
            height=height,
            expand=True,
        )

        legend_items = [(s.color, s.label) for s in series if s.show_in_legend]
        legend = ft.Row(
            [
                ft.Row(
                    [
                        ft.Container(
                            width=10, height=10, bgcolor=color, border_radius=5
                        ),
                        SecondaryText(label, size=Theme.Typography.BODY_SMALL),
                    ],
                    spacing=4,
                )
                for color, label in legend_items
            ],
            spacing=16,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # Title row dropped - chart cards now lead with the chart
        # itself; the legend underneath labels each series. ``title``
        # / ``subtitle`` parameters stay on the constructor so callers
        # don't have to change, but they're not rendered.
        self.content = ft.Column(
            [chart, legend],
            spacing=Theme.Spacing.SM,
        )
        self.padding = Theme.Spacing.MD
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)
        self.border_radius = Theme.Components.CARD_RADIUS

    @staticmethod
    def _make_series(
        s: LineSeries, *, floor: float = 0.0, ceiling: float = 0.0
    ) -> ft.LineChartData:
        """Build a `LineChartData` with the project's standard line
        styling - curved, radius-3 circle points, rounded stroke caps -
        plus an optional 15%-opacity below-line fill.

        Indices in ``s.highlighted_indices`` get a per-point ChartCirclePoint
        override (radius 7, ``s.highlight_color``, white stroke) so the
        viewer's eye is drawn to dates that correspond to the currently
        selected event chip on the parent tab.

        Two subtle behaviors that matter for annotation overlays (e.g. a
        release marker series rendered at y=0 with no visible line):
          * Per-point tooltips that are empty/None pass ``show_tooltip=False``
            so non-event dates don't surface a blank entry next to the
            real metric tooltip.
          * Series with ``stroke_width=0`` skip the series-level point dot
            so the overlay series stays truly invisible - only its
            tooltips matter.
        """
        highlight_point = ChartPoint.highlight(s.highlight_color)

        def _point_kwargs(i: int) -> dict[str, Any]:
            """Per-point overrides. ``show_tooltip`` is set explicitly in
            both branches because Flet treats the absence of a tooltip
            string differently from an opt-in `show_tooltip=True`; the
            OLD chart code relied on the explicit form and tooltips
            stopped surfacing when the refactor leaned on the default."""
            kw: dict[str, Any] = {}
            if i in s.highlighted_indices:
                kw["point"] = highlight_point
            tip = s.tooltips[i] if s.tooltips else None
            if tip:
                kw["tooltip"] = tip
                kw["show_tooltip"] = True
            else:
                kw["show_tooltip"] = False
            return kw

        data_points = [
            ft.LineChartDataPoint(x, y, **_point_kwargs(i))
            for i, (x, y) in enumerate(s.points)
        ]
        kwargs: dict[str, Any] = {
            "data_points": data_points,
            "stroke_width": s.stroke_width,
            "color": s.color,
        }
        # Polarity split: a hard-stop vertical gradient on the stroke at
        # the split's fraction of the y-range, so the line is one colour
        # above it and another below - one series, tooltips intact. A
        # window entirely on one side degrades to the plain line (the 7d
        # view of a healthy week must look exactly like it always has).
        split_fraction = None
        if s.split_y is not None:
            fraction = diverging_stop(floor=floor, ceiling=ceiling, split=s.split_y)
            if fraction <= 0.0:
                kwargs["color"] = s.split_below_color
            elif fraction < 1.0:
                split_fraction = fraction
                kwargs.pop("color")
                kwargs["gradient"] = ft.LinearGradient(
                    begin=ft.alignment.top_center,
                    end=ft.alignment.bottom_center,
                    colors=[s.color, s.color, s.split_below_color, s.split_below_color],
                    stops=[0.0, fraction, fraction, 1.0],
                )
        # Visible-line styling only applies when the series actually
        # draws a stroke. For annotation overlays (stroke_width=0) this
        # block is intentionally skipped - they're invisible tooltip
        # carriers, and applying line styling can change how Flet
        # registers their points in the tooltip stack.
        if s.stroke_width > 0:
            kwargs["curved"] = True
            kwargs["stroke_cap_round"] = True
            kwargs["point"] = ChartPoint.dot(
                s.color if s.fill else ft.Colors.ON_SURFACE
            )
            if s.fill and split_fraction is not None:
                # Two-sided fill meeting at the split: below-line down to
                # the split tints the positive area, above-line up to the
                # split tints the negative one - so the tint always sits
                # between the line and the axis, the area that IS the
                # money.
                kwargs["below_line_bgcolor"] = ft.Colors.with_opacity(0.15, s.color)
                kwargs["below_line_cutoff_y"] = s.split_y
                kwargs["above_line_bgcolor"] = ft.Colors.with_opacity(
                    0.15, s.split_below_color
                )
                kwargs["above_line_cutoff_y"] = s.split_y
            elif s.fill:
                kwargs["below_line_bgcolor"] = ft.Colors.with_opacity(0.15, s.color)
        return ft.LineChartData(**kwargs)

    @staticmethod
    def _smart_step(value_range: float) -> int:
        """Pick a round y-axis interval that scales with the data magnitude.

        Above the fixed rungs the interval climbs 1/2/5 per decade, aiming for
        about five gridlines. A flat ceiling here is what turned a $300,000
        range into a 100-unit step: three thousand tick labels, and a top value
        of 299,800 instead of 300,000.
        """
        if value_range <= 20:
            return 5
        if value_range <= 100:
            return 10
        if value_range <= 500:
            return 50

        target = value_range / 5
        magnitude = 1
        while magnitude * 10 <= target:
            magnitude *= 10
        for multiple in (1, 2, 5):
            step = multiple * magnitude
            if step >= target:
                return step
        return 10 * magnitude
