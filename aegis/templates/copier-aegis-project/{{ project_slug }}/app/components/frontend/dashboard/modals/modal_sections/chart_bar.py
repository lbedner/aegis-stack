"""The bar chart cards, grouped and ranked."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_line import (
    LineChartCard,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    BarSeries,
    ChartColors,
    RankedBar,
    chart_tooltip_kwargs,
)
from app.components.frontend.dashboard.modals.modal_sections.sections import (
    EmptyStatePlaceholder,
)
from app.components.frontend.theme import AegisTheme as Theme


class BarChartCard(ft.Container):
    """Grouped bars over a shared category axis, styled like the line card.

    ONE y-axis, always: two measures at different scales belong in two
    charts, never on twin axes. A legend is present whenever there are two
    or more series, so identity never rests on colour alone.

    Example::

        BarChartCard(
            x_labels=["Feb", "Mar"],
            series=[
                BarSeries("Income", ChartColors.TEAL, [30948.0, 17089.0]),
                BarSeries("Spending", ChartColors.VIOLET, [25910.0, 32760.0]),
            ],
            value_format=lambda v: f"${v:,.0f}",
        )
    """

    _BAR_RADIUS = 4  # rounded data-end, anchored square to the baseline

    @staticmethod
    def _bar_width(groups: int, rods_per_group: int) -> int:
        """Rod width scaled to how much of the axis each group owns.

        The chart is fluid, so there are no pixels to measure against; this
        divides a fixed width budget by the bar count. One month of cashflow
        gets substantial bars instead of two toothpicks on an empty axis,
        while a year keeps a slim profile that fits twelve groups.
        """
        budget = 220 // max(groups, 1) // max(rods_per_group, 1)
        return max(10, min(48, budget))

    def __init__(
        self,
        *,
        x_labels: list[str],
        series: list[BarSeries],
        height: int = 214,
        value_format: Callable[[float], str] | None = None,
    ) -> None:
        super().__init__()
        fmt = value_format or (lambda v: f"{v:,.0f}")

        bar_width = self._bar_width(len(x_labels), len(series))
        groups: list[ft.BarChartGroup] = []
        for index, label in enumerate(x_labels):
            rods = [
                ft.BarChartRod(
                    from_y=0,
                    to_y=s.values[index] if index < len(s.values) else 0,
                    width=bar_width,
                    color=s.color,
                    border_radius=ft.border_radius.vertical(top=self._BAR_RADIUS),
                    tooltip=f"{label}\n{s.label}: {fmt(s.values[index])}"
                    if index < len(s.values)
                    else None,
                )
                for s in series
            ]
            groups.append(
                ft.BarChartGroup(x=index, bar_rods=rods, group_vertically=False)
            )

        peak = max(
            (value for s in series for value in s.values),
            default=0.0,
        )
        step = LineChartCard._smart_step(peak) if peak else 1
        max_y = int((peak // step + 1) * step) if step else int(peak + 1)

        chart = ft.BarChart(
            bar_groups=groups,
            left_axis=ft.ChartAxis(
                labels_size=50,
                labels=[
                    ft.ChartAxisLabel(
                        value=tick,
                        label=NumericText(
                            f"{int(tick):,}",
                            size=9,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    )
                    for tick in range(0, max_y + 1, step or 1)
                ],
            ),
            bottom_axis=ft.ChartAxis(
                labels_size=24,
                labels=[
                    ft.ChartAxisLabel(
                        value=index,
                        label=NumericText(
                            label, size=9, color=ft.Colors.ON_SURFACE_VARIANT
                        ),
                    )
                    for index, label in enumerate(x_labels)
                ],
            ),
            horizontal_grid_lines=ft.ChartGridLines(
                interval=step,
                color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                width=1,
            ),
            **chart_tooltip_kwargs(),
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
            interactive=True,
            max_y=max_y,
            # A 2px surface gap between adjacent bars so two fills never
            # touch and read as one block.
            groups_space=2,
            height=height,
            expand=True,
        )

        controls: list[ft.Control] = [chart]
        if len(series) > 1:
            controls.append(
                ft.Row(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    width=10,
                                    height=10,
                                    bgcolor=s.color,
                                    border_radius=5,
                                ),
                                SecondaryText(
                                    s.label, size=Theme.Typography.BODY_SMALL
                                ),
                            ],
                            spacing=4,
                        )
                        for s in series
                    ],
                    spacing=16,
                    alignment=ft.MainAxisAlignment.CENTER,
                )
            )
        self.content = ft.Column(controls, spacing=Theme.Spacing.SM)
        self.padding = Theme.Spacing.MD
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)
        self.border_radius = Theme.Components.CARD_RADIUS


class RankedBarCard(ft.Container):
    """Horizontal bars for a ranked list - "who took the most".

    Horizontal, not vertical, because the labels are names: a payee or a
    bill reads along the bar instead of being rotated under a column.
    Built from Containers rather than a chart widget - there is no axis to
    speak of, every bar is directly labelled with its own value, and the
    ranking IS the axis.

    One hue for every bar: this compares magnitude, and magnitude is a
    sequential job. Giving each row its own colour would imply the rows
    are different KINDS of thing, which they are not.
    """

    _BAR_HEIGHT = 8
    _MIN_FRACTION = 0.02  # a bar that rounds to nothing still shows a sliver

    def __init__(
        self,
        *,
        title: str,
        rows: list[RankedBar],
        color: str | None = None,
        empty_message: str = "Nothing to show yet.",
    ) -> None:
        super().__init__()
        bar_color = color or ChartColors.TEAL
        peak = max((row.value for row in rows), default=0.0)

        controls: list[ft.Control] = [
            SecondaryText(title, size=Theme.Typography.BODY_SMALL)
        ]
        if not rows:
            controls.append(EmptyStatePlaceholder(message=empty_message))
        for row in rows:
            fraction = (row.value / peak) if peak > 0 else 0.0
            controls.append(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    content=ft.Text(
                                        row.label,
                                        size=Theme.Typography.BODY_SMALL,
                                        color=Theme.Colors.TEXT_PRIMARY,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        tooltip=row.label,  # clipped is still readable
                                    ),
                                    expand=True,
                                ),
                                *(
                                    [
                                        SecondaryText(
                                            row.meta, size=Theme.Typography.BODY_SMALL
                                        )
                                    ]
                                    if row.meta
                                    else []
                                ),
                                NumericText(
                                    row.display,
                                    size=Theme.Typography.BODY_SMALL,
                                    color=Theme.Colors.TEXT_PRIMARY,
                                ),
                            ],
                            spacing=Theme.Spacing.SM,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        # The track shows what "full" means, so a short bar
                        # reads as a small share rather than a rendering gap.
                        # Fill and remainder are flex weights: the bar cannot
                        # be a width, the card's is known only at layout time.
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Container(
                                        bgcolor=bar_color,
                                        border_radius=self._BAR_HEIGHT / 2,
                                        expand=max(
                                            1,
                                            int(
                                                max(fraction, self._MIN_FRACTION) * 1000
                                            ),
                                        ),
                                    ),
                                    ft.Container(
                                        expand=max(
                                            1,
                                            int(
                                                (1 - max(fraction, self._MIN_FRACTION))
                                                * 1000
                                            ),
                                        ),
                                    ),
                                ],
                                spacing=0,
                            ),
                            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE),
                            border_radius=self._BAR_HEIGHT / 2,
                            height=self._BAR_HEIGHT,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                )
            )
        self.content = ft.Column(
            controls, spacing=Theme.Spacing.SM, scroll=ft.ScrollMode.AUTO
        )
        self.padding = Theme.Spacing.MD
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)
        self.border_radius = Theme.Components.CARD_RADIUS
