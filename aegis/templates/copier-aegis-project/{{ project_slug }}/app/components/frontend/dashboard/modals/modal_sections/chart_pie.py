"""The pie chart card."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.components.frontend.theme import DarkColorPalette

PIE_CHART_COLORS = [
    DarkColorPalette.ACCENT,  # Teal
    "#22C55E",  # Green
    "#F5A623",  # Orange/Amber
    "#A855F7",  # Purple
    "#3B82F6",  # Blue
    "#EC4899",  # Pink
    "#6366F1",  # Indigo
    "#14B8A6",  # Cyan
    "#84CC16",  # Lime
    "#F97316",  # Deep orange
]


PIE_CHART_TAIL_COLOR = "#64748B"


class PieChartCard(ft.Container):
    """
    Reusable pie chart card with title, donut chart, and legend.

    Provides consistent styling matching the React reference design.
    Features interactive hover effects with segment expansion and tooltips.
    """

    # Segment radius constants at the DEFAULT 130px chart_size - scaled
    # proportionally in __init__ for any other size (see _normal_radius/
    # _hover_radius), so a caller asking for a bigger chart doesn't also
    # have to work out matching radii by hand.
    NORMAL_RADIUS = 45
    HOVER_RADIUS = 52
    _DEFAULT_CHART_SIZE = 130
    _DEFAULT_CENTER_SPACE_RADIUS = 28

    def __init__(
        self,
        title: str,
        sections: list[dict[str, Any]],
        value_formatter: Callable[[float], str] | None = None,
        on_slice_click: Callable[[int], None] | None = None,
        chart_size: int = _DEFAULT_CHART_SIZE,
    ) -> None:
        """
        Initialize pie chart card.

        Args:
            title: Card title
            sections: List of dicts with keys: value, label (color is auto-assigned)
                      Example: [{"value": 100, "label": "Input (50%)"}]
            value_formatter: Renders a section's value in the hover readout
                             (e.g. as dollars). Default: thousands-separated.
            on_slice_click: Called with a section's index when its LEGEND
                entry is clicked - not the pie wedge itself (see
                ``_legend_item``'s docstring: PieChart's own touch
                handling fully owns pointer events over the chart area in
                this Flet/fl_chart build, confirmed by testing three
                different ways to intercept a click there, none of which
                ever reached Python). The section's own data (what it
                represents beyond a label) isn't this control's business -
                the caller already built ``sections`` and can look its
                own index back up.
            chart_size: Pixel diameter of the donut (default 130, this
                control's original fixed size - AI Analytics' pies keep
                that unless they opt into a change). The Finance Overview
                spending pie passes a larger value: its card is stretched
                to ``_OVERVIEW_CARD_HEIGHT`` (320px) by the Row it sits in
                (``vertical_alignment=STRETCH``) regardless of this card's
                own declared ``height`` below, which left a small 130px
                donut floating in a much taller card with dead space above
                and below it.
        """
        super().__init__()

        self._section_labels: list[str] = []
        self._section_values: list[float] = []
        self._hovered_index: int | None = None
        self._value_formatter = value_formatter or (lambda value: f"{value:,.2f}")
        self._on_slice_click = on_slice_click
        self._chart_size = chart_size
        # Proportional to the 130px baseline the constants above were
        # tuned at, not a second set of magic numbers.
        scale = chart_size / self._DEFAULT_CHART_SIZE
        self._normal_radius = self.NORMAL_RADIUS * scale
        self._hover_radius = self.HOVER_RADIUS * scale
        self._center_space_radius = self._DEFAULT_CENTER_SPACE_RADIUS * scale
        # Hover readout: the hovered slice's label, value, and share, in the
        # card's title row so nothing jumps when it appears. Primary (white)
        # text, not secondary gray - it is the answer being asked for, not a
        # caption.
        self._readout = PrimaryText("", size=Theme.Typography.BODY_SMALL)

        if not sections:
            self.content = ft.Column(
                [
                    SecondaryText(title),
                    ft.Container(
                        content=SecondaryText("No data", size=13),
                        expand=True,
                        alignment=ft.alignment.center,
                    ),
                ],
                spacing=0,
                expand=True,
            )
            self._setup_card_style()
            return

        # Build pie chart sections with auto-assigned colors
        self._pie_sections: list[ft.PieChartSection] = []
        legend_items: list[ft.Control] = []

        for i, section in enumerate(sections):
            value = float(section.get("value", 0))
            # Use provided color or auto-assign from palette
            color = section.get("color") or PIE_CHART_COLORS[i % len(PIE_CHART_COLORS)]
            label = str(section.get("label", ""))

            # Store for tooltips
            self._section_labels.append(label)
            self._section_values.append(value)

            self._pie_sections.append(
                ft.PieChartSection(
                    value=value,
                    title="",
                    color=color,
                    radius=self._normal_radius,
                )
            )
            legend_items.append(self._legend_item(label, color, i))

        # Donut chart with hover interaction
        self._pie_chart = ft.PieChart(
            sections=self._pie_sections,
            sections_space=2,
            center_space_radius=self._center_space_radius,
            on_chart_event=self._on_chart_event,
        )

        # Legend: always ONE vertical column - a second column steals width
        # from labels that are already long ("Food & Dining:Groceries") and
        # clips them at the card edge. Bounded to the chart's own height and
        # scrollable rather than left to grow unbounded: the card itself
        # has a FIXED height (_setup_card_style) with HARD_EDGE clipping,
        # so an unbounded legend on a caller with many sections (the
        # finance spending pie, once its "Other" slice fix meant more
        # named categories) would silently clip rows off the bottom
        # instead of visibly failing - scroll makes every entry reachable
        # instead.
        legend = ft.Container(
            content=ft.Column(
                legend_items,
                spacing=Theme.Spacing.XS,
                alignment=ft.MainAxisAlignment.CENTER,
                scroll=ft.ScrollMode.AUTO,
            ),
            height=self._chart_size,
        )

        # Layout: chart + legend horizontal, centered
        chart_row = ft.Row(
            [
                ft.Container(
                    content=self._pie_chart,
                    width=self._chart_size,
                    height=self._chart_size,
                ),
                legend,
            ],
            spacing=Theme.Spacing.LG,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Column layout with chart pushed down to avoid overlap
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        SecondaryText(title),
                        ft.Container(expand=True),
                        self._readout,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    content=chart_row,
                    expand=True,
                    alignment=ft.alignment.center,
                    margin=ft.margin.only(top=Theme.Spacing.MD),
                ),
            ],
            spacing=0,
            expand=True,
        )
        self._setup_card_style()

    def _setup_card_style(self) -> None:
        """Apply consistent card styling."""
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)
        self.border_radius = Theme.Components.CARD_RADIUS
        self.padding = ft.padding.only(
            left=Theme.Spacing.MD,
            right=Theme.Spacing.MD,
            top=Theme.Spacing.SM,
            bottom=Theme.Spacing.SM,
        )
        # 80px of title/margin/padding around the chart itself at any size
        # (the original 210 = 130 + 80) - not just the DEFAULT size, so a
        # caller asking for a bigger chart_size gets a card sized to fit
        # it instead of one that clips or floats the chart in dead space.
        self.height = self._chart_size + 80
        self.expand = True
        self.clip_behavior = ft.ClipBehavior.HARD_EDGE

    def _on_chart_event(self, e: ft.PieChartEvent) -> None:
        """Handle hover - expand the segment and show its value."""
        idx = e.section_index

        # Reset all sections to normal radius
        for section in self._pie_sections:
            section.radius = self._normal_radius

        # Check if hovering over a section (section_index is -1 when not hovering)
        if idx is not None and idx >= 0 and idx < len(self._pie_sections):
            self._pie_sections[idx].radius = self._hover_radius
            self._hovered_index = idx
            value = self._section_values[idx]
            total = sum(self._section_values)
            share = f" · {value / total * 100:.0f}%" if total else ""
            self._readout.value = (
                f"{self._section_labels[idx]} · {self._value_formatter(value)}{share}"
            )
        else:
            self._hovered_index = None
            self._readout.value = ""

        self._pie_chart.update()
        if self._readout.page is not None:
            self._readout.update()

    def _legend_item(self, label: str, color: str, index: int) -> ft.Control:
        """Create a legend item with color dot and label.

        Clickable when ``on_slice_click`` is set - NOT the pie wedge
        itself. Three different ways of detecting a click ON the chart
        (PieChartEvent's own ``type`` field, a wrapping GestureDetector,
        an opaque ``ink`` Container around it) all failed to reach Python
        at all when tested live: PieChart's own internal touch handling
        for hover fully owns pointer events in its bounds in this
        Flet/fl_chart build, with no exposed way to disable that or let
        events fall through. A legend row has no such competing pointer
        owner - same plain ``Container(ink=True, on_click=...)`` already
        proven reliable elsewhere in this codebase (e.g. the account
        filter menu's own row entries).
        """
        row = ft.Row(
            [
                ft.Container(width=10, height=10, bgcolor=color, border_radius=5),
                SecondaryText(label, size=Theme.Typography.BODY_SMALL),
            ],
            spacing=8,
        )
        on_click = self._on_slice_click
        if on_click is None:
            return row
        return ft.Container(
            content=row,
            on_click=lambda _e, i=index: on_click(i),
            ink=True,
            border_radius=4,
            padding=ft.padding.symmetric(horizontal=2),
            tooltip="View transactions",
        )
