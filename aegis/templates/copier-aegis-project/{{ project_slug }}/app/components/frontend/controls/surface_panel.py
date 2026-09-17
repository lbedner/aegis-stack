"""The house panel: a bordered surface, defined once.

Eleven call sites across the dashboard modals hand-rolled the same three
properties - a 1px OUTLINE border, ``CARD_RADIUS``, and a ``SURFACE``
background - and varied padding, width and height around them. Six
signatures for one visual idea, which is how a panel comes to look
almost-but-not-quite like the one beside it.

``CardContainer`` does not serve this. It is the dashboard's component
card: it takes a ``ComponentStatus``, colours its border by status, and
wires click-to-modal. These are plain panels inside modals, with no
component behind them.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme


class SurfacePanel(ft.Container):
    """A bordered surface panel.

    Everything a caller used to repeat is here; everything they varied
    stays a parameter, and stays unset when not passed - a default
    padding would silently re-lay-out every site this replaced.
    """

    def __init__(
        self,
        *,
        content: ft.Control,
        padding: int | ft.Padding | None = None,
        width: int | None = None,
        height: int | None = None,
        expand: bool | None = None,
        bgcolor: str | None = None,
        border_color: str | None = None,
        visible: bool | None = None,
    ) -> None:
        super().__init__()
        self.content = content
        self.border = ft.border.all(1, border_color or ft.Colors.OUTLINE)
        self.border_radius = Theme.Components.CARD_RADIUS
        self.bgcolor = bgcolor or ft.Colors.SURFACE
        if padding is not None:
            self.padding = padding
        if width is not None:
            self.width = width
        if height is not None:
            self.height = height
        if expand is not None:
            self.expand = expand
        if visible is not None:
            self.visible = visible
