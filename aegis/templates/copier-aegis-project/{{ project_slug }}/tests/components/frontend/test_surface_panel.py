"""The house panel: one definition of a bordered surface.

Eleven call sites across the dashboard hand-rolled the same three
properties - a 1px OUTLINE border, CARD_RADIUS, and a SURFACE background
- and then varied padding, width and height around them. Six slightly
different signatures for one visual idea, which is how a panel ends up
looking almost-but-not-quite like its neighbour.

``CardContainer`` does not cover this: it is the dashboard's component
card, and takes a ComponentStatus and wires click-to-modal. These are
plain panels inside modals.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls.surface_panel import SurfacePanel
from app.components.frontend.theme import AegisTheme as Theme


class TestTheChrome:
    def test_it_carries_the_house_border_radius_and_surface(self) -> None:
        panel = SurfacePanel(content=ft.Text("body"))

        assert panel.border_radius == Theme.Components.CARD_RADIUS
        assert panel.bgcolor == ft.Colors.SURFACE
        assert panel.border is not None

    def test_the_content_is_passed_through_untouched(self) -> None:
        body = ft.Text("body")

        assert SurfacePanel(content=body).content is body


class TestWhatCallersVary:
    def test_padding_width_and_height_are_optional(self) -> None:
        """The six signatures differed only in these; a panel that could
        not take them would send callers back to a raw Container."""
        panel = SurfacePanel(content=ft.Text("x"), padding=20, width=940, height=760)

        assert panel.padding == 20
        assert panel.width == 940
        assert panel.height == 760

    def test_omitting_them_leaves_them_unset(self) -> None:
        """A panel that forced a default padding would change the layout
        of every site it replaced."""
        panel = SurfacePanel(content=ft.Text("x"))

        assert panel.padding is None
        assert panel.width is None
        assert panel.height is None

    def test_expand_is_available(self) -> None:
        assert SurfacePanel(content=ft.Text("x"), expand=True).expand is True

    def test_a_caller_can_override_the_background(self) -> None:
        """Some panels sit on a tinted ground. Overriding beats dropping
        back to a raw Container and losing the border with it."""
        panel = SurfacePanel(content=ft.Text("x"), bgcolor=ft.Colors.SURFACE_TINT)

        assert panel.bgcolor == ft.Colors.SURFACE_TINT
        assert panel.border_radius == Theme.Components.CARD_RADIUS
