"""The anchored Dropdown's panel geometry.

Position and size derive only from the tap event's own coordinates and
the content - never from page dimensions (see the module docstring in
``dropdown.py`` for the zoom-space reason). This pins the failure mode
the stat popup shipped with: a right-aligned panel pushed past the left
screen edge by a leftmost trigger. (The popup's content-hugging height
is covered with the stat popup itself, in ``test_stat_details.py``.)
"""

import flet as ft

from app.components.frontend.controls.dropdown import Dropdown
from app.components.frontend.theme import AegisTheme as Theme
from tests.components.frontend._fakes import tap as _tap


def _dropdown() -> Dropdown:
    return Dropdown(
        trigger=ft.Container(),
        panel=ft.Container(),
        trigger_width=200,
        min_width=300,
        max_width=340,
    )


class TestPanelStaysOnScreen:
    """align="right" hangs the panel left of the trigger's right edge;
    for a trigger near the screen's left edge that lands at negative x
    and the panel opens half off-screen."""

    def test_a_right_aligned_panel_never_crosses_the_left_edge(self) -> None:
        dd = _dropdown()
        # Trigger at x=40: right-aligned left would be 40 + 200 - 340 = -100.
        dd._toggle(_tap(global_x=40.0))

        assert dd._panel_frame.left is not None
        assert dd._panel_frame.left >= Theme.Spacing.MD

    def test_a_panel_clear_of_the_edge_keeps_its_anchor(self) -> None:
        dd = _dropdown()
        dd._toggle(_tap(global_x=600.0))

        assert dd._panel_frame.left == 600 + 200 - 340
