"""
Tag component for badges and labels.

Modern tag UI control based on ee-toolset design.
"""

import flet as ft

from app.components.frontend.styles import FontConfig
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatusType


class Tag(ft.Container):
    """
    Tag component for displaying badges, labels, and categories.

    Features bordered design with colored text and border, sized for compact display.
    """

    def __init__(
        self, text: str, color: str = ft.Colors.AMBER, *, compact: bool = False
    ) -> None:
        # Compact is for dense table cells: tighter padding and a smaller
        # face, so the pill hugs a short word instead of overflowing it.
        super().__init__(
            border=ft.border.all(1, color),
            border_radius=ft.border_radius.all(5),
            padding=ft.Padding(5, 1, 5, 1)
            if compact
            else ft.Padding(7.5, 2.5, 7.5, 2.5),
            alignment=ft.alignment.center,
            content=ft.Text(
                text,
                weight=ft.FontWeight.W_700,
                color=color,
                font_family=FontConfig.FAMILY_PRIMARY,
                size=10 if compact else FontConfig.SIZE_TERTIARY,
                text_align=ft.TextAlign.CENTER,
                no_wrap=True,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
        )


class StatusTag(ft.Container):
    """
    Exception-based status indicator.

    "Quiet when Good, Loud when Bad" - escalating visual weight with severity:
    - HEALTHY: Subtle dot + text, no background
    - INFO: Dot + text with light blue tint
    - WARNING: Dot + text with light amber tint
    - UNHEALTHY: Filled red background, white text (alarm state)

    Optionally shows a detail line below the status (e.g., "2/3 queues online").
    ``text`` overrides the default severity label (e.g. "Connected" or
    "Login required" on a finance connection) while keeping the severity's
    dot-and-weight styling.
    """

    def __init__(
        self,
        status: ComponentStatusType,
        detail: str | None = None,
        text: str | None = None,
    ) -> None:
        # Determine styling based on status severity
        if status == ComponentStatusType.UNHEALTHY:
            # CRITICAL: Filled background, white text - maximum attention
            dot_color = ft.Colors.WHITE
            text_color = ft.Colors.WHITE
            detail_color = ft.Colors.with_opacity(0.8, ft.Colors.WHITE)
            bg_color = Theme.Colors.ERROR
            text = text or "UNHEALTHY"
            font_weight = ft.FontWeight.W_700
        elif status == ComponentStatusType.WARNING:
            # WARNING: Amber tint background
            dot_color = Theme.Colors.WARNING
            text_color = Theme.Colors.WARNING
            detail_color = ft.Colors.with_opacity(0.7, Theme.Colors.WARNING)
            bg_color = ft.Colors.with_opacity(0.15, Theme.Colors.WARNING)
            text = text or "Warning"
            font_weight = ft.FontWeight.W_600
        elif status == ComponentStatusType.INFO:
            # INFO: Blue tint background
            dot_color = Theme.Colors.INFO
            text_color = Theme.Colors.INFO
            detail_color = ft.Colors.with_opacity(0.7, Theme.Colors.INFO)
            bg_color = ft.Colors.with_opacity(0.15, Theme.Colors.INFO)
            text = text or "Info"
            font_weight = ft.FontWeight.W_600
        else:
            # HEALTHY: Minimal - just dot and text, no background
            dot_color = Theme.Colors.SUCCESS
            text_color = Theme.Colors.SUCCESS
            detail_color = ft.Colors.with_opacity(0.7, Theme.Colors.SUCCESS)
            bg_color = None
            text = text or "Healthy"
            font_weight = ft.FontWeight.W_500

        # Build the status row: dot + text
        status_row = ft.Row(
            [
                # Status dot
                ft.Container(
                    width=8,
                    height=8,
                    bgcolor=dot_color,
                    border_radius=4,
                ),
                # Status text
                ft.Text(
                    text,
                    weight=font_weight,
                    color=text_color,
                    font_family=FontConfig.FAMILY_PRIMARY,
                    size=FontConfig.SIZE_TERTIARY,
                ),
            ],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Build content - with or without detail line
        if detail:
            content = ft.Column(
                [
                    status_row,
                    ft.Text(
                        detail,
                        size=10,
                        color=detail_color,
                        font_family=FontConfig.FAMILY_PRIMARY,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
        else:
            content = status_row

        super().__init__(
            content=content,
            bgcolor=bg_color,
            border_radius=ft.border_radius.all(12),
            padding=ft.Padding(10, 4, 10, 4),
            alignment=ft.alignment.center,
        )
