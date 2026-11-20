"""
Snackbar variants for the Overseer.

Four variants — Success, Error, Warning, Info — share a single shape and
differ only in accent color, icon, and default title. Use ``.launch(page)``
to fire one; the snackbar object itself is reusable and never stores a
``page`` reference.

Pulse aesthetic: dark card background, accent-colored icon-circle and
left border, white title, muted subtitle. Floating, top-right.

Example::

    SuccessSnackBar("Signed in").launch(page)
    ErrorSnackBar("Could not reach the server.").launch(page)
"""

from __future__ import annotations

from typing import ClassVar

import flet as ft

from app.components.frontend.controls.text import BodyText, SecondaryText
from app.components.frontend.theme import AegisTheme as Theme


class BaseSnackBar(ft.SnackBar):
    """Base for Pulse-styled snackbars. Subclass to set accent + icon + title."""

    accent: ClassVar[str] = ft.Colors.ON_SURFACE_VARIANT
    icon: ClassVar[str] = ft.Icons.INFO_OUTLINE
    title: ClassVar[str] = "Notice"

    def __init__(
        self,
        message: str,
        *,
        title: str | None = None,
        duration: int = 4000,
        width: int = 380,
    ) -> None:
        title = title or self.title
        accent = self.accent

        icon_circle = ft.Container(
            content=ft.Icon(self.icon, color=ft.Colors.SURFACE, size=16),
            width=28,
            height=28,
            border_radius=14,
            bgcolor=accent,
            alignment=ft.alignment.center,
        )

        body = ft.Column(
            controls=[
                BodyText(title, color=ft.Colors.ON_SURFACE, weight=ft.FontWeight.W_600),
                SecondaryText(message, color=ft.Colors.ON_SURFACE_VARIANT, size=12),
            ],
            spacing=2,
            tight=True,
        )

        card = ft.Container(
            content=ft.Row(
                controls=[
                    icon_circle,
                    ft.Container(content=body, expand=True),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.only(
                left=ft.BorderSide(width=2, color=accent),
                top=ft.BorderSide(width=1, color=ft.Colors.OUTLINE),
                right=ft.BorderSide(width=1, color=ft.Colors.OUTLINE),
                bottom=ft.BorderSide(width=1, color=ft.Colors.OUTLINE),
            ),
            border_radius=8,
        )

        super().__init__(
            content=card,
            duration=duration,
            show_close_icon=True,
            close_icon_color=ft.Colors.ON_SURFACE_VARIANT,
            bgcolor=ft.Colors.TRANSPARENT,
            elevation=0,
            padding=0,
            width=width,
            margin=ft.margin.only(top=16, right=16),
            behavior=ft.SnackBarBehavior.FLOATING,
        )

    def launch(self, page: ft.Page) -> None:
        """Open the snackbar on ``page``. The snackbar does not retain ``page``."""
        page.open(self)


class SuccessSnackBar(BaseSnackBar):
    """Teal accent, check icon. Confirmations and successful actions."""

    accent = Theme.Colors.PRIMARY
    icon = ft.Icons.CHECK_CIRCLE_OUTLINE
    title = "Success"


class ErrorSnackBar(BaseSnackBar):
    """Red accent, error icon. Failures the user should notice."""

    accent = Theme.Colors.ERROR
    icon = ft.Icons.ERROR_OUTLINE
    title = "Error"


class WarningSnackBar(BaseSnackBar):
    """Amber accent, warning icon. Recoverable issues / cautions."""

    accent = Theme.Colors.WARNING
    icon = ft.Icons.WARNING_AMBER_OUTLINED
    title = "Warning"


class InfoSnackBar(BaseSnackBar):
    """Muted accent, info icon. Non-critical notices."""

    accent = ft.Colors.ON_SURFACE_VARIANT
    icon = ft.Icons.INFO_OUTLINE
    title = "Notice"
