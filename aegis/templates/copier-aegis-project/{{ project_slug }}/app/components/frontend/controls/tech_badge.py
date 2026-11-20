"""
Technology Badge Component

Reusable badge component for displaying technology information with icon,
title, subtitle, and status tag.
"""

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme

from .tag import Tag
from .text import H3Text, SecondaryText


class TechBadge(ft.Container):
    """
    Technology badge component with title, subtitle, and status tag.

    Displays technology information in a consistent, centered layout with:
    - Technology title
    - Technology subtitle/description
    - Status tag (bordered style)
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        badge_text: str | None = None,
        badge_color: str = Theme.Colors.WARNING,
        primary_color: str = Theme.Colors.PRIMARY,
        width: int | None = 200,
    ) -> None:
        """
        Initialize the TechBadge component.

        Args:
            title: Main technology title (e.g., "FastAPI", "Worker")
            subtitle: Technology subtitle (e.g., "Backend API", "arq + Redis")
            badge_text: Badge label text (e.g., "API", "QUEUES").
                If None, no badge shown.
            badge_color: Border color for the tag
            primary_color: Status color (for potential future use)
            width: Width of the badge container (default 160px)
        """
        controls: list[ft.Control] = [
            H3Text(title),
            SecondaryText(subtitle),
        ]

        if badge_text:
            controls.append(
                ft.Container(
                    content=Tag(text=badge_text, color=badge_color),
                    margin=ft.margin.only(top=4),
                )
            )

        super().__init__(
            content=ft.Column(
                controls,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=ft.padding.all(16),
            width=width,
            alignment=ft.alignment.center,
        )
