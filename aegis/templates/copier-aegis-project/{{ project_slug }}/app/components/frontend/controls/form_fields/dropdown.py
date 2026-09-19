"""Choosing one of a known set."""

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls.form_fields.shared import (
    _PULSE_ERROR_BORDER,
    FormVariant,
    _build_label,
)
from app.components.frontend.styles import PulseColors
from app.components.frontend.theme import AegisTheme as Theme


class FormDropdown(ft.Container):
    """
    Reusable dropdown with label and error state.

    Mirrors ``FormTextField``'s shape (label above, field below, optional
    error line). Uses Flet's stock ``ft.Dropdown`` directly. Note: the
    focused border colour is not painted in Flet 0.28.x — that's a known
    framework limitation, not something we work around here.
    """

    def __init__(
        self,
        label: str,
        options: list[tuple[str, str]],
        value: str | None = None,
        on_change: Callable[[ft.ControlEvent], None] | None = None,
        error: str | None = None,
        disabled: bool = False,
        width: int | None = None,
        variant: FormVariant = "default",
        max_menu_height: int | None = None,
    ) -> None:
        super().__init__()

        self._label = label
        self._error = error
        self._on_change = on_change
        self._variant = variant

        initial = value if value is not None else (options[0][0] if options else None)

        if variant == "pulse":
            dropdown_kwargs: dict[str, Any] = {
                "border_radius": 4,
                "bgcolor": PulseColors.CARD,
                "border_color": PulseColors.BORDER
                if not error
                else _PULSE_ERROR_BORDER,
                "focused_border_color": PulseColors.TEAL,
                "text_style": ft.TextStyle(color=PulseColors.TEXT, size=14),
                "content_padding": ft.padding.symmetric(horizontal=12, vertical=10),
            }
        else:
            dropdown_kwargs = {
                "border_radius": Theme.Components.INPUT_RADIUS,
                "bgcolor": ft.Colors.SURFACE,
                "border_color": (Theme.Colors.ERROR if error else ft.Colors.OUTLINE),
                "focused_border_color": Theme.Colors.PRIMARY,
                "text_size": 13,
                "content_padding": ft.padding.symmetric(horizontal=12, vertical=10),
            }

        # Width on the outer Container too (as FormTextField does it):
        # without it the control collapses inside a Row.
        if width is not None:
            self.width = width
        self._dropdown = ft.Dropdown(
            value=initial,
            options=[ft.dropdown.Option(key=k, text=t) for k, t in options],
            on_change=self._handle_change,
            disabled=disabled,
            expand=width is None,
            width=width,
            # Caps the open menu so long option lists scroll instead of
            # spilling past the viewport.
            max_menu_height=max_menu_height,
            **dropdown_kwargs,
        )

        self._build_content()

    def _build_content(self) -> None:
        children: list[ft.Control] = [
            _build_label(self._label, self._variant),
            ft.Container(height=4),
            self._dropdown,
        ]
        if self._error:
            children.append(ft.Container(height=4))
            children.append(
                ft.Text(
                    self._error,
                    size=Theme.Typography.BODY_SMALL,
                    color=Theme.Colors.ERROR,
                )
            )
        self.content = ft.Column(children, spacing=0, tight=True)

    def _handle_change(self, e: ft.ControlEvent) -> None:
        if self._on_change:
            self._on_change(e)

    @property
    def value(self) -> str:
        return self._dropdown.value or ""

    @value.setter
    def value(self, new_value: str) -> None:
        self._dropdown.value = new_value
        if self.page:
            self._dropdown.update()

    def set_error(self, error: str | None) -> None:
        self._error = error
        # Mirror the init-time per-variant colors so a pulse dropdown
        # keeps its styling when an error is set or cleared.
        if self._variant == "pulse":
            self._dropdown.border_color = (
                _PULSE_ERROR_BORDER if error else PulseColors.BORDER
            )
        else:
            self._dropdown.border_color = (
                Theme.Colors.ERROR if error else ft.Colors.OUTLINE
            )
        self._build_content()
        if self.page:
            self.update()

    def set_options(
        self,
        options: list[tuple[str, str]],
        *,
        keep_value: bool = True,
    ) -> None:
        """Replace the dropdown's options at runtime.

        ``keep_value`` preserves the current selection if its key is still
        present after the update; otherwise it clears.
        """
        previous = self._dropdown.value if keep_value else None
        self._dropdown.options = [ft.dropdown.Option(key=k, text=t) for k, t in options]
        if previous is not None and any(k == previous for k, _ in options):
            self._dropdown.value = previous
        else:
            self._dropdown.value = None
        if self.page:
            self._dropdown.update()
