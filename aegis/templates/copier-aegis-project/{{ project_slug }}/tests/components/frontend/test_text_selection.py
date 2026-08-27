"""Selection is a property of regions, not of individual text controls.

Flet controls are not selectable unless a ``SelectionArea`` encloses them.
The alternative - marking each Text ``selectable=True`` - renders a
SelectableText, which owns the pointer and paints an I-beam over whatever
is clickable underneath it. So the rule is: text controls stay plain, and
every surface that shows text wraps its content in one SelectionArea.
"""

from unittest.mock import MagicMock

import flet as ft

from app.components.frontend.controls import PrimaryText, SecondaryText
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.text import BodyText, NumericText
from app.components.frontend.dashboard.modals.base_popup import BasePopup


class TestTextControlsAreNotIndividuallySelectable:
    def test_house_text_controls_default_to_plain_text(self) -> None:
        for control in (
            PrimaryText("x"),
            SecondaryText("x"),
            BodyText("x"),
            NumericText("1"),
        ):
            assert control.selectable is False, type(control).__name__

    def test_an_explicit_override_still_wins(self) -> None:
        """A standalone block with no enclosing area can still opt in."""
        assert PrimaryText("x", selectable=True).selectable is True


class TestSurfacesEncloseTheirContent:
    def test_a_dialog_wraps_its_panel(self) -> None:
        dialog = StyledAlertDialog(title="T", body=ft.Text("body"))

        assert isinstance(dialog.content, ft.SelectionArea)

    def test_a_detail_dialog_wraps_its_body(self) -> None:
        """The component detail modals render through a real AlertDialog,
        which is its own route - the page-level region cannot reach it."""
        from app.components.frontend.dashboard.modals.base_modal import (
            BaseDetailDialog,
        )

        dialog = BaseDetailDialog(
            component_data=MagicMock(),
            title_text="T",
            sections=[ft.Text("body")],
        )

        assert isinstance(dialog.content, ft.SelectionArea)

    def test_a_popup_wraps_its_panel(self) -> None:
        popup = BasePopup(MagicMock(), content=ft.Text("body"))

        assert isinstance(popup.panel.content, ft.SelectionArea)
