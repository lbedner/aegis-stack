"""The furniture around a modal's content: headings, grids, empty states, range chips."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
)
from app.components.frontend.dashboard.modals.modal_sections.cards import (
    MetricCard,
)
from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    ChartColors,
)
from app.components.frontend.theme import AegisTheme as Theme


class SectionHeader(ft.Row):
    """Section header with icon and title."""

    def __init__(
        self,
        title: str,
        icon: str | None = None,
        color: str | None = None,
    ) -> None:
        """
        Initialize section header.

        Args:
            title: Section title text
            icon: Optional icon name
            color: Optional icon color (defaults to secondary text color)
        """
        items: list[ft.Control] = []
        if icon:
            items.append(
                ft.Icon(icon, size=18, color=color or ft.Colors.ON_SURFACE_VARIANT)
            )
        items.append(H3Text(title))

        super().__init__(items, spacing=8)


class MetricCardSection(ft.Container):
    """
    Reusable section for displaying metric cards in a grid.

    Creates a titled section with metric cards displayed in a horizontal row.
    Each metric is rendered using the MetricCard component.
    """

    def __init__(self, title: str, metrics: list[dict[str, str]]) -> None:
        """
        Initialize metric card section.

        Args:
            title: Section title
            metrics: List of metric dicts with keys: label, value, color
                     Example: [{"label": "Total", "value": "42", "color": "#00ff00"}]
        """
        super().__init__()

        cards = []
        for metric in metrics:
            cards.append(
                MetricCard(
                    label=metric["label"],
                    value=metric["value"],
                    color=metric["color"],
                )
            )

        self.content = ft.Column(
            [
                H3Text(title),
                ft.Container(height=Theme.Spacing.SM),
                ft.Row(cards, spacing=Theme.Spacing.MD),
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD


class StatRowsSection(ft.Container):
    """
    Reusable section for displaying label/value pairs.

    Creates a titled section with statistics displayed as label: value rows.
    Common pattern for detailed component information.
    """

    def __init__(
        self,
        title: str,
        stats: dict[str, str | ft.Control],
        label_width: int = 150,
    ) -> None:
        """
        Initialize stat rows section.

        Args:
            title: Section title
            stats: Dictionary of label: value pairs
            label_width: Width for label column (default: 150px)
        """
        super().__init__()

        rows = []
        for label, value in stats.items():
            rows.append(
                ft.Row(
                    [
                        SecondaryText(
                            f"{label}:",
                            weight=Theme.Typography.WEIGHT_SEMIBOLD,
                            width=label_width,
                        ),
                        value if isinstance(value, ft.Control) else BodyText(value),
                    ],
                    spacing=Theme.Spacing.MD,
                )
            )

        self.content = ft.Column(
            [
                H3Text(title),
                ft.Container(height=Theme.Spacing.SM),
                ft.Column(rows, spacing=Theme.Spacing.SM),
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD


class EmptyStatePlaceholder(ft.Container):
    """
    Reusable placeholder for empty states.

    Displays a consistent message when no data is available,
    using theme colors and spacing.
    """

    def __init__(
        self,
        message: str,
    ) -> None:
        """
        Initialize empty state placeholder.

        Args:
            message: Message to display
        """
        super().__init__()

        self.content = ft.Row(
            [
                SecondaryText(
                    message,
                    size=Theme.Typography.BODY_LARGE,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=Theme.Spacing.MD,
        )
        self.padding = Theme.Spacing.XL
        self.bgcolor = (
            ft.Colors.SURFACE_CONTAINER_HIGHEST
        )  # Elevated surface for contrast
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(1, ft.Colors.OUTLINE)


class DateRangeChips(ft.Container):
    """Row of small selectable pills for picking a date-range window.

    Mirrors the aegis-pulse `alpine_date_range` macro: tightly-padded
    chips with a light teal-fill / teal-border on the selected pill and
    the standard MetricCard surface treatment on the others. Owns its
    own selection state so the parent tab only has to wire up an
    ``on_change(days)`` callback - the in-place restyle on click stays
    inside the control.

    Example:
        chips = DateRangeChips(
            options=[("7d", 7), ("14d", 14), ("1m", 30), ("All", 9999)],
            selected_days=14,
            on_change=lambda d: tab._on_range_change(d),
        )
    """

    _BORDER_RADIUS = 4

    def __init__(
        self,
        *,
        options: list[tuple[str, int]],
        selected_days: int,
        on_change: Callable[[int], None],
    ) -> None:
        super().__init__()
        self._options = options
        self._selected_days = selected_days
        self._on_change = on_change

        self._chips: list[ft.Container] = []
        for label, days in options:
            self._chips.append(
                ft.Container(
                    content=ft.Text(
                        label,
                        size=11,
                        weight=self._weight(days == selected_days),
                        color=self._text_color(days == selected_days),
                    ),
                    bgcolor=self._bgcolor(days == selected_days),
                    border=self._border(days == selected_days),
                    border_radius=self._BORDER_RADIUS,
                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                    on_click=lambda _e, d=days: self._handle_click(d),
                    ink=True,
                )
            )

        self.content = ft.Row(self._chips, spacing=6)

    def set_selected(self, days: int) -> None:
        """Update the active pill in place without rebuilding."""
        self._selected_days = days
        for (_label, d), chip in zip(self._options, self._chips, strict=False):
            is_active = d == days
            chip.bgcolor = self._bgcolor(is_active)
            chip.border = self._border(is_active)
            chip.content.weight = self._weight(is_active)
            chip.content.color = self._text_color(is_active)

    def _handle_click(self, days: int) -> None:
        self.set_selected(days)
        # Paint the selection NOW, before the (possibly slow) data reload
        # the callback triggers - otherwise the chip looks frozen until the
        # whole tab repaints and the click feels like it did nothing.
        if self.page is not None:
            self.update()
        self._on_change(days)

    @staticmethod
    def _bgcolor(is_active: bool) -> str:
        # Inactive pills sit on the page background (transparent) so the
        # range strip reads as outlined controls rather than a row of
        # cards - matches the aegis-pulse htmx version. Active pill
        # gets the light teal fill to mark the selection.
        return (
            ft.Colors.with_opacity(0.10, ChartColors.TEAL)
            if is_active
            else ft.Colors.TRANSPARENT
        )

    @staticmethod
    def _border(is_active: bool) -> ft.Border:
        return ft.border.all(0.5, ChartColors.TEAL if is_active else ft.Colors.OUTLINE)

    @staticmethod
    def _weight(is_active: bool) -> ft.FontWeight:
        return ft.FontWeight.W_600 if is_active else ft.FontWeight.W_400

    @staticmethod
    def _text_color(is_active: bool) -> str:
        return ft.Colors.ON_SURFACE if is_active else ft.Colors.ON_SURFACE_VARIANT
