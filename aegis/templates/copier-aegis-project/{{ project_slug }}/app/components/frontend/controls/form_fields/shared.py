"""The two pieces every field shares: its label, and the keyword
arguments that give every input the same look.
"""

from typing import Any, Literal

import flet as ft

from app.components.frontend.controls.text import LabelText
from app.components.frontend.styles import PulseColors
from app.components.frontend.theme import AegisTheme as Theme

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


# Public alias: the one input recipe. Prefer ``StyledTextField``
# (controls/inputs.py); the alias remains for surfaces that must splice
# the recipe into an existing ft.TextField construction.
input_field_kwargs = _input_kwargs
