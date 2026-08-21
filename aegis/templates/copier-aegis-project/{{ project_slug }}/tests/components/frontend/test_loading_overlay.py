"""The blocking overlay's panel hugs its content.

A Flet ``Column`` defaults to ``tight=False``, which stretches it to all
available height - so the busy panel rendered as a viewport-tall black
box with a title and bar pinned at the top (confirmed live, on "Writing
today's note..."). The error panel already carried ``tight=True``; the
busy panel forgot it.
"""

import flet as ft

from app.components.frontend.controls.loading_overlay import LoadingOverlay


class _FakePage:
    def __init__(self) -> None:
        self.data = None
        self.overlay = []

    def update(self) -> None:
        pass


def _panel_column(overlay: LoadingOverlay) -> ft.Column:
    column = overlay.content.content
    assert isinstance(column, ft.Column)
    return column


class TestThePanelHugsItsContent:
    def test_the_busy_panel_is_tight(self) -> None:
        overlay = LoadingOverlay.of(_FakePage())
        overlay.show("Writing today's note...")
        assert _panel_column(overlay).tight is True

    def test_the_error_panel_stays_tight(self) -> None:
        overlay = LoadingOverlay.of(_FakePage())
        overlay.fail("boom")
        assert _panel_column(overlay).tight is True

    def test_the_panel_never_declares_a_height(self) -> None:
        """Hugging means no fixed height either - the error state sizes
        itself by capping only its message region."""
        overlay = LoadingOverlay.of(_FakePage())
        overlay.show("x")
        assert overlay.content.height is None
