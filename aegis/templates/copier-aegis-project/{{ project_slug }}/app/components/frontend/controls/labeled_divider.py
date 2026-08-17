"""
Horizontal divider with a centered label.

Used between sections, most notably the "OR" between sign-in
credentials and OAuth providers on the login form.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls.text import LabelText
from app.components.frontend.styles import PulseColors


class LabeledDivider(ft.Container):
    """A horizontal hairline broken in the middle by a label."""

    def __init__(
        self,
        label: str,
        *,
        line_color: str = PulseColors.BORDER,
        label_color: str = PulseColors.MUTED,
        letter_spacing: float = 2,
        width: int | None = None,
    ) -> None:
        super().__init__()

        line_left = ft.Container(height=1, bgcolor=line_color, expand=True)
        line_right = ft.Container(height=1, bgcolor=line_color, expand=True)
        label_widget = ft.Container(
            content=LabelText(
                label,
                color=label_color,
                size=10,
                style=ft.TextStyle(letter_spacing=letter_spacing),
            ),
            padding=ft.padding.symmetric(horizontal=12),
        )

        self.content = ft.Row(
            controls=[line_left, label_widget, line_right],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.width = width
