"""Reusable card with a styled header bar and a content area.

The visual treatment matches ``DataTable`` and ``ActivityFeed``: 1px
outline border, ``Theme.Components.CARD_RADIUS`` corners, and a header
row tinted with ``ON_SURFACE`` at 5% opacity divided from the body by
a 1px hairline. Use it for any titled section that should feel like a
sibling of the dashboard's data tables.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme

from .text import SecondaryText


class SectionCard(ft.Container):
    """Outlined card with a tinted header bar and a content body.

    Args:
        title: Header label. Pass a string for the standard
            ``SecondaryText`` treatment, or any Flet control when the
            caller needs a custom or mutable label.
        body: Control rendered inside the card's content area.
        actions: Optional controls right-aligned in the header (e.g. a
            toggle button or filter widget).
        body_padding: Inner padding around ``body``. Pass ``0`` (or
            ``ft.padding.all(0)``) when the body owns its own padding,
            for example a ``ListView`` or a nested ``DataTable``.
        expand: Forwarded to the outer container and inner column.
    """

    def __init__(
        self,
        title: str | ft.Control,
        body: ft.Control,
        actions: list[ft.Control] | None = None,
        body_padding: int | ft.Padding = 0,
        header_padding_v: int = 6,
        expand: bool = False,
    ) -> None:
        super().__init__()

        title_control: ft.Control = (
            SecondaryText(title, size=Theme.Typography.BODY_SMALL)
            if isinstance(title, str)
            else title
        )

        header_row_children: list[ft.Control] = [
            title_control,
            ft.Container(expand=True),
        ]
        if actions:
            header_row_children.extend(actions)

        header = ft.Container(
            content=ft.Row(
                header_row_children,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.MD, vertical=header_padding_v
            ),
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE)),
        )

        body_pad = (
            ft.padding.all(body_padding)
            if isinstance(body_padding, int)
            else body_padding
        )
        body_container = ft.Container(content=body, padding=body_pad, expand=expand)

        self.content = ft.Column([header, body_container], spacing=0, expand=expand)
        self.bgcolor = ft.Colors.SURFACE
        self.border = ft.border.all(1, ft.Colors.OUTLINE)
        self.border_radius = Theme.Components.CARD_RADIUS
        self.expand = expand
