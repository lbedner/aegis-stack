"""A dialog's own buttons can close it without pretending it might not exist.

A dialog's actions are constructed before the dialog is, so seventeen
call sites across eleven files opened with ``dialog: StyledAlertDialog |
None = None`` and then re-checked inside the handler:

    if dialog is not None:
        dialog.open = False

That check can never fail - the button cannot be clicked before the
dialog it lives in has been built - so the ``| None`` is a lie told to
the type checker, and the guard is ceremony around it.

A handle is created first, handed to the dialog, and closed by name.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls.dialog import DialogHandle, StyledAlertDialog


class FakePage:
    def __init__(self) -> None:
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


class TestClosing:
    def test_it_closes_the_dialog_it_was_given(self) -> None:
        handle = DialogHandle()
        dialog = StyledAlertDialog(
            title="Delete?", body=ft.Text("body"), handle=handle
        )
        dialog.open = True

        handle.close()

        assert dialog.open is False

    def test_closing_before_a_dialog_is_bound_is_harmless(self) -> None:
        """The failure the None-check was guarding against. It still
        cannot happen, but it must not explode if a caller builds the
        handle and then bails before constructing the dialog."""
        DialogHandle().close()

    def test_it_can_refresh_the_page_it_is_given(self) -> None:
        """One call site closed and then called page.update(); the rest
        did not. Both stay possible."""
        page = FakePage()
        handle = DialogHandle()
        StyledAlertDialog(title="t", body=ft.Text("b"), handle=handle)

        handle.close(page)

        assert page.updates == 1

    def test_closing_without_a_page_does_not_refresh(self) -> None:
        handle = DialogHandle()
        StyledAlertDialog(title="t", body=ft.Text("b"), handle=handle)

        handle.close()  # no page, no update - the common case


class TestBinding:
    def test_a_dialog_without_a_handle_still_builds(self) -> None:
        """Most dialogs never need to close themselves."""
        assert StyledAlertDialog(title="t", body=ft.Text("b")) is not None

    def test_the_handle_holds_the_dialog_that_took_it(self) -> None:
        handle = DialogHandle()
        dialog = StyledAlertDialog(title="t", body=ft.Text("b"), handle=handle)

        assert handle.dialog is dialog
