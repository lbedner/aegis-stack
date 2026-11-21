"""
ServiceCard Control

Reusable Flet control for composing service cards with 2-column layout.
Provides consistent layout with thin vertical divider and vertical centering.
"""

import flet as ft


class ServiceCard(ft.Row):
    """
    Reusable service card layout control.

    Creates a clean 2-column layout with:
    - Left section: Technology badge (vertically centered)
    - Thin vertical divider
    - Right section: Metrics/content (full height)

    Usage:
        ServiceCard(
            left_content=tech_badge,
            right_content=metrics_section,
        )
    """

    def __init__(
        self,
        left_content: ft.Control,
        right_content: ft.Control,
        divider_height: int = 160,
        left_width: int = 200,
        divider_color: str | None = None,
    ):
        """
        Initialize the ServiceCard.

        Args:
            left_content: Control for left section (typically TechBadge)
            right_content: Control for right section (typically metrics)
            divider_height: Height of the vertical divider in pixels
            left_width: Width of the left section in pixels
            divider_color: Color of the vertical divider (defaults to OUTLINE_VARIANT)
        """
        # Build the row controls
        controls = [
            # Left section: Tech badge with vertical centering
            ft.Container(
                content=ft.Column(
                    [left_content],
                    spacing=0,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                width=left_width,
                padding=ft.padding.all(16),
            ),
            # Thin vertical divider
            ft.Container(
                width=1,
                height=divider_height,
                bgcolor=divider_color or ft.Colors.OUTLINE,
                margin=ft.margin.symmetric(horizontal=16),
            ),
            # Right section: Metrics/content
            right_content,
        ]

        # Initialize Row with controls
        super().__init__(controls=controls, expand=True)
