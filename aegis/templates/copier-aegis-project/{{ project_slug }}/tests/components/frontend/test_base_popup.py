"""Tests for BasePopup's backdrop click-to-dismiss behavior."""

from unittest.mock import MagicMock

import flet as ft

from app.components.frontend.dashboard.modals.base_popup import BasePopup


def _make_event(control: ft.Control) -> MagicMock:
    event = MagicMock()
    event.control = control
    event.page = MagicMock()
    return event


def test_backdrop_click_closes_by_default() -> None:
    popup = BasePopup(page=MagicMock(), content=ft.Text("hi"))
    popup.show()

    popup._handle_backdrop_click(_make_event(popup))

    assert popup.visible is False
    assert popup.panel.visible is False


def test_backdrop_click_can_be_opted_out() -> None:
    popup = BasePopup(
        page=MagicMock(), content=ft.Text("hi"), dismiss_on_backdrop=False
    )
    popup.show()

    popup._handle_backdrop_click(_make_event(popup))

    assert popup.visible is True


def test_click_on_panel_never_closes() -> None:
    popup = BasePopup(page=MagicMock(), content=ft.Text("hi"))
    popup.show()

    popup._handle_backdrop_click(_make_event(popup.panel))

    assert popup.visible is True


def test_close_hides_the_popup() -> None:
    """``hide()`` leaves the repaint to the caller, so every popup wrote the
    same two lines - and one of them wrote ``self.open = False``, an
    AlertDialog-ism that silently does nothing on a Container and left the
    popup on screen. ``close()`` is the one way to do it."""
    page = MagicMock()
    popup = BasePopup(page, content=ft.Text("body"))
    popup.show()

    popup.close()

    assert popup.visible is False
    assert popup.overlay.visible is False
    assert popup.panel.visible is False
    assert page.update.called
