"""Free-text entry: the field every form is mostly made of."""

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

# cannot reflow it - see FormTextField.__init__.
_CLEAR_ICON_SIZE = 16
_CLEAR_HIT_SIZE = 24


class FormTextField(ft.Container):
    """
    Reusable text input with label and error state.

    Features:
    - Theme-aware styling with consistent border radius and colors
    - Label using existing LabelText component
    - Error text display below field (red) when error provided
    - Optional hint text for placeholder guidance
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        hint: str = "",
        on_change: Callable[[ft.ControlEvent], None] | None = None,
        # Flet's TextField accepts both sync and async on_submit at runtime.
        on_submit: (Callable[[ft.ControlEvent], Awaitable[None] | None] | None) = None,
        error: str | None = None,
        disabled: bool = False,
        width: int | None = None,
        variant: FormVariant = "default",
        keyboard_type: str | None = None,
        autofocus: bool = False,
        password: bool = False,
        can_reveal_password: bool = False,
        multiline: bool = False,
        min_lines: int | None = None,
        max_lines: int | None = None,
        input_filter: ft.InputFilter | None = None,
        show_label: bool = True,
        borderless: bool = False,
        compact: bool = False,
        clearable: bool = False,
    ) -> None:
        """
        Initialize form text field.

        Args:
            label: Label text displayed above the field
            value: Initial value for the field
            hint: Placeholder/hint text when field is empty
            on_change: Callback when field value changes
            on_submit: Callback when the user presses enter
            error: Error message to display below field (None = no error)
            disabled: Whether the field is disabled
            width: Optional fixed width for the field
            variant: Style variant (``"default"`` or ``"pulse"``)
            keyboard_type: Optional ``ft.KeyboardType`` (e.g. EMAIL)
            autofocus: Focus this field on mount
            password: Mask the value
            can_reveal_password: Add Flet's built-in reveal toggle
            multiline: Enable multi-line text entry
            min_lines: Minimum visible lines for multi-line fields
            max_lines: Maximum visible lines for multi-line fields
            input_filter: Optional ``ft.InputFilter`` (e.g. numbers only)
            show_label: When False, skip the label widget and the 4px
                gap above the field (use when an outer container, e.g.
                a SectionCard header, already provides the label).
            borderless: When True, drop the field's border and corner
                radius so it blends into a parent container that owns
                the visible frame (e.g. a SectionCard).
        """
        super().__init__()

        self._label = label
        self._error = error
        self._on_change = on_change
        self._variant = variant
        self._show_label = show_label
        self._clearable = clearable

        # Outer Container takes the explicit width so siblings (buttons,
        # dividers) can match it.
        if width is not None:
            self.width = width

        input_kwargs = _input_kwargs(variant, error, compact=compact)
        if multiline:
            # A pinned height collapses multi-line fields; let min/max_lines
            # drive the height instead.
            input_kwargs.pop("height", None)
        if borderless:
            input_kwargs["border"] = ft.InputBorder.NONE
            input_kwargs["border_radius"] = 0
            input_kwargs["filled"] = False
            input_kwargs["bgcolor"] = ft.Colors.TRANSPARENT
        # ALWAYS present, at a fixed size, with only the glyph fading in
        # and out. Toggling the suffix's own ``visible`` is what shifted
        # the typed text: the slot appears and disappears as you type the
        # first character or delete the last, and the input's content row
        # re-lays-out around it. Reported live - the text jumped on one
        # keystroke. Reserving the space permanently costs 24px of gutter
        # and makes the geometry constant.
        self._clear_icon = (
            ft.Icon(
                ft.Icons.CLOSE,
                size=_CLEAR_ICON_SIZE,
                color=ft.Colors.ON_SURFACE_VARIANT,
                opacity=1.0 if value else 0.0,
            )
            if clearable
            else None
        )
        # A Container, not an IconButton: the stock button brings
        # Material's ~48px hit box, taller than the input itself (40, or
        # 36 compact), which sets the row height on its own.
        self._clear_button = (
            ft.Container(
                content=self._clear_icon,
                # top+bottom rather than a fixed height: the input is 40
                # tall, or 36 compact, or unset - stretching to whatever
                # it turns out to be keeps the glyph centred without this
                # having to know which.
                right=6,
                top=0,
                bottom=0,
                width=_CLEAR_HIT_SIZE,
                alignment=ft.alignment.center,
                border_radius=_CLEAR_HIT_SIZE / 2,
                ink=True,
                tooltip="Clear",
                on_click=self._clear,
            )
            if clearable
            else None
        )
        if clearable:
            # Keep the text off the button. The overlay sits ON the field
            # (below), so the input itself has to reserve the gutter or a
            # long query slides underneath the x.
            padding = input_kwargs.get("content_padding")
            if padding is not None:
                padding.right = _CLEAR_HIT_SIZE + 10
        self._text_field = ft.TextField(
            value=value,
            hint_text=hint,
            on_change=self._handle_change,
            on_submit=on_submit,
            disabled=disabled,
            keyboard_type=keyboard_type,
            autofocus=autofocus,
            password=password,
            can_reveal_password=can_reveal_password,
            multiline=multiline,
            min_lines=min_lines,
            max_lines=max_lines,
            input_filter=input_filter,
            expand=width is None,
            width=width,
            **input_kwargs,
        )

        self._build_content()

    def _build_content(self) -> None:
        """Build the form field content with label and optional error."""
        children: list[ft.Control] = []
        if self._show_label:
            children.append(_build_label(self._label, self._variant))
            children.append(ft.Container(height=4))
        children.append(
            # A Stack, not the TextField's ``suffix`` slot. As a suffix the
            # button is part of the input's DECORATION, so its 24px box
            # sets the content row height and the typed text sits low -
            # permanently, whether the button is toggled or always
            # mounted. Overlaying takes it out of that layout entirely:
            # the input measures itself as if the button were not there.
            ft.Stack([self._text_field, self._clear_button])
            if self._clear_button is not None
            else self._text_field
        )

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
        """Handle text field change events."""
        self._sync_clear_button()
        if self._on_change:
            self._on_change(e)

    def _sync_clear_button(self) -> None:
        """Fade the glyph, never move the slot."""
        if self._clear_icon is None:
            return
        wanted = 1.0 if self._text_field.value else 0.0
        if self._clear_icon.opacity == wanted:
            return
        self._clear_icon.opacity = wanted
        if self._clear_icon.page is not None:
            self._clear_icon.update()

    def _clear(self, _e: ft.ControlEvent | None) -> None:
        """Empty the box AND tell the owner.

        A no-op while the box is already empty: the hit target is always
        there (so the layout never shifts), but an invisible glyph should
        not be clickable.

        The panels re-filter off ``on_change``, so clearing without
        firing it would blank the input and leave the results filtered by
        a query no longer on screen - worse than no button at all.
        """
        if not self._text_field.value:
            return
        self._text_field.value = ""
        self._sync_clear_button()
        if self._text_field.page is not None:
            self._text_field.update()
        if self._on_change:
            self._on_change(
                ft.ControlEvent(
                    target="",
                    name="change",
                    data="",
                    control=self._text_field,
                    page=None,
                )
            )

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
        if self._variant == "pulse":
            self._text_field.border_color = (
                _PULSE_ERROR_BORDER if error else PulseColors.BORDER
            )
        else:
            self._text_field.border_color = (
                Theme.Colors.ERROR if error else ft.Colors.OUTLINE
            )
        self._build_content()
        if self.page:
            self.update()

    def focus(self) -> None:
        """Focus the text field."""
        self._text_field.focus()
