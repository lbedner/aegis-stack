"""
Reusable form field components for Aegis Stack dashboard.

Provides theme-aware form inputs with consistent styling for labels,
text fields, secret fields (with visibility toggle), and action buttons.

Variants:
- ``"default"`` — Material-themed inputs (current behavior).
- ``"pulse"`` — Pulse aesthetic: dark CARD bg, teal focus border, caps
  tracked label. Use this on Pulse-styled views like the login form.
"""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, Literal

import flet as ft

from app.components.frontend.controls.buttons import (
    ElevatedCancelButton,
    ElevatedUpdateButton,
)
from app.components.frontend.controls.calendar import CalendarPanel
from app.components.frontend.controls.text import LabelText
from app.components.frontend.styles import PulseColors
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date

FormVariant = Literal["default", "pulse"]

# The clear affordance. Kept under the compact input height (36) so it
# never sets the content row's height, and always mounted so appearing
# cannot reflow it - see FormTextField.__init__.
_CLEAR_ICON_SIZE = 16
_CLEAR_HIT_SIZE = 24

# Error-state border for the pulse variant (matches the web frontend).
_PULSE_ERROR_BORDER = "#E94E77"
_PULSE_LABEL_STYLE = ft.TextStyle(letter_spacing=1.6)


def _build_label(text: str, variant: FormVariant) -> ft.Control:
    """Pick the right label widget for the variant."""
    if variant == "pulse":
        return LabelText(
            text.upper(),
            color=PulseColors.MUTED,
            size=10,
            weight=ft.FontWeight.W_500,
            style=_PULSE_LABEL_STYLE,
        )
    return LabelText(text)


def _input_kwargs(
    variant: FormVariant, error: str | None, compact: bool = False
) -> dict[str, Any]:
    """Per-variant ft.TextField kwargs (border, bg, text colors).

    Pulse variant matches the web frontend's
    ``border border-aegis-border rounded px-3 py-2 text-sm`` recipe —
    14px text, 12px horizontal padding, 4px corner radius. Height pinned
    to 40 so fields visually align with ``PulseButton``.
    """
    if variant == "pulse":
        return {
            "border_color": PulseColors.BORDER if not error else _PULSE_ERROR_BORDER,
            "focused_border_color": PulseColors.TEAL,
            "cursor_color": PulseColors.TEAL,
            "bgcolor": PulseColors.CARD,
            "text_style": ft.TextStyle(color=PulseColors.TEXT, size=14),
            "hint_style": ft.TextStyle(color=PulseColors.MUTED, size=14),
            "border_radius": 4,
            "filled": True,
            "content_padding": ft.padding.symmetric(horizontal=12, vertical=10),
            "height": 40,
        }
    kwargs: dict[str, Any] = {
        "border_radius": Theme.Components.INPUT_RADIUS,
        "bgcolor": ft.Colors.SURFACE,
        "border_color": Theme.Colors.ERROR if error else ft.Colors.OUTLINE,
        "focused_border_color": Theme.Colors.PRIMARY,
        "text_size": 13,
        "content_padding": ft.padding.symmetric(horizontal=12, vertical=10),
    }
    if compact:
        # Material auto-sizes the default field to ~48px, which towers over
        # the chips and compact buttons it sits beside in a toolbar. Pin a
        # shorter box and tighten the padding to match.
        kwargs["height"] = 36
        kwargs["content_padding"] = ft.padding.symmetric(horizontal=10, vertical=6)
    return kwargs


# Public alias: the one input recipe, importable by non-form surfaces
# (e.g. the chat composer) so every text input shares the same border,
# background, and focus colors instead of re-deriving them.
input_field_kwargs = _input_kwargs


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


class FormDateField(ft.Container):
    """A date input backed by a calendar, not a typed string.

    Every date in this app used to be a ``FormTextField`` labelled
    "(YYYY-MM-DD)", parsed on save and rejected with a snackbar if you
    mistyped it - which puts the format rule in a label and the
    enforcement in an error message, neither of which is where you are
    looking.

    The calendar is the house ``CalendarPanel``, NOT ``ft.DatePicker``:
    that one is a Flutter dialog themed through
    ``theme.date_picker_theme``, and setting that property at all crashes
    the page render on Flet 0.28.3 (bisected to a single plain
    ``bgcolor``). Ours is ordinary Containers wearing ``AegisTheme``.

    It expands INLINE, under the field, rather than floating in a
    ``Dropdown`` like the account filter and payee pickers. Those live on
    a page; this one lives in a dialog, and Flet renders ``page.overlay``
    BELOW ``ft.AlertDialog`` - so a floating panel opened from inside a
    dialog draws behind it and the dialog's own scrim swallows the
    clicks. Confirmed live. Growing the dialog is the trade for being
    reachable at all.

    The field shows the date the way the rest of the product shows dates
    ("Aug 19, 2026", ``core.formatting.format_date``) while ``value``
    stays ISO, so callers that already do
    ``date.fromisoformat(field.value)`` keep working unchanged.
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        hint: str = "Pick a date",
        width: int | None = None,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        if width is not None:
            self.width = width
        self._iso = (value or "").strip()
        self._on_change = on_change
        self._field = FormTextField(
            label=label,
            value=format_date(self._iso) if self._iso else "",
            hint=hint,
            width=width,
        )
        # Read-only: a calendar that also takes free text has two sources
        # of truth and one of them can be "Augsut 19".
        self._field._text_field.read_only = True
        self._field._text_field.suffix_icon = ft.Icons.CALENDAR_MONTH
        self._field._text_field.on_click = self._toggle
        self._panel = CalendarPanel(selected=self._parsed(), on_pick=self._picked)
        # Bordered like the popup it replaces, so it still reads as a
        # surface floating over the form rather than another form row.
        self._holder = ft.Container(
            content=self._panel,
            visible=False,
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            padding=Theme.Spacing.SM,
            margin=ft.margin.only(top=Theme.Spacing.XS),
        )
        self.content = ft.Column([self._field, self._holder], spacing=0, tight=True)

    def _parsed(self) -> date | None:
        if not self._iso:
            return None
        try:
            return date.fromisoformat(self._iso)
        except ValueError:
            return None

    @property
    def value(self) -> str:
        """The ISO date, or "" - what callers parse."""
        return self._iso

    @value.setter
    def value(self, new_value: str) -> None:
        self._iso = (new_value or "").strip()
        self._field.value = format_date(self._iso) if self._iso else ""

    def _toggle(self, _e: ft.ControlEvent) -> None:
        self._holder.visible = not self._holder.visible
        if self._holder.page is not None:
            self._holder.update()

    def _picked(self, day: date) -> None:
        self._iso = day.isoformat()
        self._field.value = format_date(self._iso)
        # Close on pick: the calendar has said all it has to say, and
        # leaving it open keeps the dialog at its tallest for no reason.
        self._holder.visible = False
        if self._field.page is not None:
            self._field.update()
        if self._holder.page is not None:
            self._holder.update()
        if self._on_change is not None:
            self._on_change(self._iso)


class FormActionButtons(ft.Row):
    """
    Save/Cancel button pair for forms.

    Features:
    - Uses existing ElevatedUpdateButton and ElevatedCancelButton
    - Shows loading state when saving=True
    - Consistent right-aligned layout
    """

    def __init__(
        self,
        on_save: Callable[[], Awaitable[None]],
        on_cancel: Callable[[], Awaitable[None]],
        save_text: str = "Save",
        cancel_text: str = "Cancel",
        saving: bool = False,
    ) -> None:
        """
        Initialize form action buttons.

        Args:
            on_save: Async callback when save button is clicked.
            on_cancel: Async callback when cancel button is clicked.
            save_text: Text for the save button.
            cancel_text: Text for the cancel button.
            saving: Whether save operation is in progress (shows loading).
        """
        self._on_save = on_save
        self._on_cancel = on_cancel
        self._save_text = save_text
        self._saving = saving

        # Create buttons
        self._cancel_button = ElevatedCancelButton(
            on_click_callable=on_cancel,
            text=cancel_text,
        )

        self._save_button = ElevatedUpdateButton(
            on_click_callable=self._handle_save,
            text=save_text if not saving else "Saving...",
        )
        self._save_button.disabled = saving

        super().__init__(
            controls=[
                self._cancel_button,
                self._save_button,
            ],
            spacing=Theme.Spacing.SM,
            alignment=ft.MainAxisAlignment.END,
        )

    async def _handle_save(self) -> None:
        """Handle save button click."""
        await self._on_save()

    def set_saving(self, saving: bool) -> None:
        """Update the saving state."""
        self._saving = saving
        self._save_button.disabled = saving
        self._save_button.text = self._save_text if not saving else "Saving..."
        if self.page:
            self._save_button.update()
