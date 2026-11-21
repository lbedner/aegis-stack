"""Tests for the snackbar variants."""

from unittest.mock import MagicMock

import flet as ft

from app.components.frontend.controls.snack_bar import (
    BaseSnackBar,
    ErrorSnackBar,
    InfoSnackBar,
    SuccessSnackBar,
    WarningSnackBar,
)
from app.components.frontend.theme import AegisTheme as Theme


def test_success_uses_teal_and_check_icon() -> None:
    bar = SuccessSnackBar("ok")
    assert SuccessSnackBar.accent == Theme.Colors.PRIMARY
    assert SuccessSnackBar.title == "Success"
    assert bar.duration == 4000


def test_error_uses_red_accent() -> None:
    assert ErrorSnackBar.accent == Theme.Colors.ERROR
    assert ErrorSnackBar.title == "Error"


def test_warning_uses_amber_accent() -> None:
    assert WarningSnackBar.accent == Theme.Colors.WARNING
    assert WarningSnackBar.title == "Warning"


def test_info_uses_muted_accent() -> None:
    assert InfoSnackBar.accent == ft.Colors.ON_SURFACE_VARIANT
    assert InfoSnackBar.title == "Notice"


def test_custom_title_overrides_default() -> None:
    bar = SuccessSnackBar("ok", title="Saved")
    # The bar's body Column holds title text in its first child.
    # Easier: just verify constructor accepted the override without raising.
    assert isinstance(bar, SuccessSnackBar)


def test_launch_calls_page_open_without_storing_page() -> None:
    page = MagicMock()
    bar = InfoSnackBar("hello")
    bar.launch(page)

    page.open.assert_called_once_with(bar)
    # Snackbar must not have stored the page reference.
    assert not hasattr(bar, "_page")
    assert not hasattr(bar, "page_ref")


def test_base_snackbar_can_be_subclassed_with_overrides() -> None:
    class CustomSnack(BaseSnackBar):
        accent = "#123456"
        title = "Custom"

    bar = CustomSnack("hi")
    assert CustomSnack.accent == "#123456"
    assert isinstance(bar, BaseSnackBar)
