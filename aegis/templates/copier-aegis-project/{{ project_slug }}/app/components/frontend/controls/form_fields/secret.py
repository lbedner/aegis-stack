"""A text field that hides what it holds, and offers to reveal it."""

from collections.abc import Awaitable, Callable

import flet as ft

from app.components.frontend.controls.form_fields.shared import (
    _PULSE_ERROR_BORDER,
    FormVariant,
    _build_label,
    _input_kwargs,
)
from app.components.frontend.controls.text import LabelText
from app.components.frontend.styles import PulseColors
from app.components.frontend.theme import AegisTheme as Theme


class FormSecretField(ft.Container):
    """
    Text input for secrets with show/hide toggle.

    Features:
    - Password field with visibility toggle (eye icon)
    - Theme-aware styling consistent with FormTextField
    - Never shows full value in view mode (always masked)
    - Label and error state support
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        hint: str = "Enter value...",
        on_change: Callable[[ft.ControlEvent], None] | None = None,
        error: str | None = None,
        disabled: bool = False,
        width: int | None = None,
    ) -> None:
        """Initialize form secret field (same arguments as FormTextField)."""
        super().__init__()

        self._label = label
        self._error = error
        self._on_change = on_change
        self._password_visible = False

        # Create the text field
        self._text_field = ft.TextField(
            value=value,
            hint_text=hint,
            password=True,
            can_reveal_password=False,  # We use our own toggle
            on_change=self._handle_change,
            disabled=disabled,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=Theme.Colors.ERROR if error else ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=10),
            expand=True,
        )

        # Create visibility toggle button
        self._toggle_button = ft.IconButton(
            icon=ft.Icons.VISIBILITY_OFF,
            icon_color=Theme.Colors.TEXT_SECONDARY,
            icon_size=18,
            tooltip="Show/hide value",
            on_click=self._toggle_visibility,
            disabled=disabled,
        )

        # Build content
        self._build_content(width)

    def _build_content(self, width: int | None = None) -> None:
        """Build the form field content with label, field, toggle, and error."""
        # Field with toggle button
        field_row = ft.Row(
            [
                self._text_field,
                self._toggle_button,
            ],
            spacing=4,
            expand=width is None,
            width=width,
        )

        children: list[ft.Control] = [
            LabelText(self._label),
            ft.Container(height=4),
            field_row,
        ]

        # Add error text if present
        if self._error:
            children.append(ft.Container(height=4))
            children.append(
                ft.Text(
                    self._error,
                    size=Theme.Typography.BODY_SMALL,
                    color=Theme.Colors.ERROR,
                )
            )

        self.content = ft.Column(
            children,
            spacing=0,
            tight=True,
        )

    def _handle_change(self, e: ft.ControlEvent) -> None:
        """Handle text field change events."""
        if self._on_change:
            self._on_change(e)

    def _toggle_visibility(self, e: ft.ControlEvent) -> None:
        """Toggle password visibility."""
        self._password_visible = not self._password_visible
        self._text_field.password = not self._password_visible
        self._toggle_button.icon = (
            ft.Icons.VISIBILITY if self._password_visible else ft.Icons.VISIBILITY_OFF
        )
        if self.page:
            self._text_field.update()
            self._toggle_button.update()

    @property
    def value(self) -> str:
        """Get the current field value."""
        return self._text_field.value or ""

    @value.setter
    def value(self, new_value: str) -> None:
        """Set the field value."""
        self._text_field.value = new_value
        if self.page:
            self._text_field.update()

    def set_error(self, error: str | None) -> None:
        """Set or clear the error message."""
        self._error = error
        # Update border color based on error state
        self._text_field.border_color = (
            Theme.Colors.ERROR if error else ft.Colors.OUTLINE
        )
        self._build_content()
        if self.page:
            self.update()

    def focus(self) -> None:
        """Focus the text field."""
        self._text_field.focus()

