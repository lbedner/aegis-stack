"""A label, one prominent value, and a line of context.

The docs tab builds three of these - most read, most visited, top
country - and built each one by hand, ninety lines apart, differing
only in what went in the three slots.

``MetricCard`` is the house card for this shape and does not fit: it
renders its value as ``NumericText``, which is right for a count and
wrong for a page title or a country name. Rather than put prose in the
numeric typeface, this is the same card for values that are words.
"""

import flet as ft
from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.theme import AegisTheme as Theme


class InsightCard(ft.Container):
    """One headline fact, with what it is and what it means around it."""

    def __init__(
        self,
        label: str,
        value: str,
        caption: str,
        *,
        tooltip: str | None = None,
    ) -> None:
        super().__init__()
        self.content = ft.Column(
            [
                SecondaryText(label),
                ft.Text(value, size=24, weight=ft.FontWeight.W_600),
                SecondaryText(caption, size=Theme.Typography.BODY_SMALL),
            ],
            spacing=Theme.Spacing.XS,
        )
        self.padding = Theme.Spacing.MD
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)
        self.expand = True
        if tooltip is not None:
            self.tooltip = tooltip
