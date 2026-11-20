"""
Top-left brand mark used across Overseer surfaces.

A small teal dot followed by ``Overseer · <project_name>``. Used on the
auth shell (Login / Register top-left) and on the dashboard header.
Replaced the heavy 96x96 ``overseer.png`` logo in the dashboard header
once that image started overpowering the surrounding chrome — the same
mark already worked fine on the auth shell, so we hoist it to a shared
control instead of duplicating the geometry.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls.text import BodyText
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings


class BrandMark(ft.Row):
    """``● Overseer · <project_name>`` brand chip."""

    def __init__(
        self,
        *,
        project_name: str | None = None,
        dot_size: int = 8,
        spacing: int = 10,
    ) -> None:
        name = project_name or settings.PROJECT_NAME
        super().__init__(
            controls=[
                ft.Container(
                    width=dot_size,
                    height=dot_size,
                    bgcolor=Theme.Colors.PRIMARY,
                    border_radius=dot_size / 2,
                ),
                BodyText(
                    f"Overseer · {name}",
                    color=ft.Colors.ON_SURFACE,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=spacing,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        )
