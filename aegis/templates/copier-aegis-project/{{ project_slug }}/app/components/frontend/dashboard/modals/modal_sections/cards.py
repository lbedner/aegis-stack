"""The cards a modal puts a number or a fact on."""

from __future__ import annotations

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    LabelText,
    NumericText,
    SecondaryText,
    Tag,
)
from app.components.frontend.theme import AegisTheme as Theme


class InfoCard(ft.Container):
    """Info card displaying a label and value with consistent card styling."""

    def __init__(
        self,
        label: str,
        value: str = "",
        tags: list[tuple[str, str]] | None = None,
    ) -> None:
        """
        Initialize info card.

        Args:
            label: Card label text (shown at top)
            value: Value to display (used if no tags provided)
            tags: Optional list of (text, color) tuples to show as tags
        """
        super().__init__()

        content_items: list[ft.Control] = [
            LabelText(label),
            ft.Container(height=Theme.Spacing.XS),
        ]

        if tags:
            # Show tags (e.g., provider badges)
            tag_controls = [Tag(text=t, color=c) for t, c in tags]
            content_items.append(
                ft.Row(
                    tag_controls,
                    spacing=4,
                    wrap=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                )
            )
        else:
            # Show value as body text
            content_items.append(BodyText(value))

        self.content = ft.Column(
            content_items,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        )
        self.padding = Theme.Spacing.MD
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)
        self.expand = True


class MetricCard(ft.Container):
    """Reusable metric display card with icon, label, and colored value."""

    def __init__(
        self,
        label: str,
        value: str,
        color: str,
        icon: str | None = None,
        change_pct: float | None = None,
        invert: bool = False,
        prev_value: str | None = None,
        tooltip: str | None = None,
    ) -> None:
        """
        Initialize metric card.

        Args:
            label: Metric label text
            value: Metric value to display
            color: Color for the value text
            icon: Optional icon name (e.g., ft.Icons.TOKEN)
            change_pct: Optional period-over-period change percentage
            invert: If True, down is good (green) and up is bad (red) — e.g., bounce rate
            prev_value: Optional previous period value to display (e.g., "prev: 3,080")
        """  # noqa: E501
        super().__init__()

        # Header row with icon and label
        header_items: list[ft.Control] = []
        if icon:
            header_items.append(ft.Icon(icon, size=16, color=color))
        header_items.append(SecondaryText(label))

        header_row = ft.Row(
            header_items,
            spacing=6,
        )

        # Value text — stored as instance attribute for live updates.
        # Deliberately NOT tinted by ``color``: that argument colours the
        # icon and is a per-card accent, and applying it to the number
        # turned every metric across the dashboard into coloured text.
        # A card that wants a coloured value calls ``set_value(v, color)``.
        self.value_text = NumericText(
            value,
            size=24,
            weight=ft.FontWeight.W_600,
        )

        # Value row: number + optional change arrow inline
        value_items: list[ft.Control] = [self.value_text]
        if change_pct is not None:
            # When invert=True, up is bad (red) and down is good (green)
            if change_pct > 0:
                arrow_icon = ft.Icons.NORTH_EAST
                arrow_color = Theme.Colors.ERROR if invert else Theme.Colors.SUCCESS
            elif change_pct < 0:
                arrow_icon = ft.Icons.SOUTH_EAST
                arrow_color = Theme.Colors.SUCCESS if invert else Theme.Colors.ERROR
            else:
                arrow_icon = ft.Icons.EAST
                arrow_color = ft.Colors.ON_SURFACE_VARIANT
            value_items.append(
                ft.Row(
                    [
                        ft.Icon(arrow_icon, size=14, color=arrow_color),
                        ft.Text(
                            f"{abs(change_pct):.0f}%",
                            size=14,
                            color=arrow_color,
                            weight=ft.FontWeight.W_600,
                        ),
                    ],
                    spacing=2,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )

        value_row = ft.Row(
            value_items, spacing=6, vertical_alignment=ft.CrossAxisAlignment.END
        )

        column_items = [header_row, value_row]
        if prev_value is not None:
            column_items.append(
                SecondaryText(prev_value, size=Theme.Typography.BODY_SMALL)
            )

        self.content = ft.Column(
            column_items,
            spacing=Theme.Spacing.XS,
        )
        self.padding = Theme.Spacing.MD
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)
        self.expand = True
        if tooltip:
            self.tooltip = tooltip

    def set_value(self, value: str, color: str | None = None) -> None:
        """Update the displayed value (and optionally its color) in place."""
        self.value_text.value = value
        if color is not None:
            self.value_text.color = color


class MilestoneCard(ft.Container):
    """Trophy-style card for key milestones with hero number."""

    def __init__(
        self,
        label: str,
        value: str,
        date: str,
        accent_color: str = "#9CA3AF",
    ) -> None:
        super().__init__()

        items: list[ft.Control] = [SecondaryText(label)]
        if value and value != "\u2014":
            items.append(
                ft.Text(
                    value,
                    size=28,
                    weight=ft.FontWeight.W_700,
                    color=accent_color,
                )
            )
        items.append(SecondaryText(date, size=Theme.Typography.BODY_SMALL))

        self.content = ft.Column(
            items,
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        self.padding = Theme.Spacing.MD
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)
        self.height = 130
        self.expand = True


def headline_stat(label: str, value: str, color: str) -> ft.Control:
    """A bare headline figure: small label over a big number, no card.

    The card-shaped ``MetricCard`` is for a grid of metrics that IS the
    content. When the figures ride along a tab's header - beside a title,
    above a chart that owns the space - the chrome costs a card's height
    and adds a second box competing with the chart's own. This is the
    header form: right-aligned so a row of them ends on a clean edge.
    """
    return ft.Column(
        [
            SecondaryText(label),
            NumericText(value, size=24, weight=ft.FontWeight.W_600, color=color),
        ],
        spacing=2,
        horizontal_alignment=ft.CrossAxisAlignment.END,
    )
