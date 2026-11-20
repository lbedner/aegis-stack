"""Button styles for Overseer's controls.

Every colour is a token from ``theme.AegisTheme.Colors``, a scheme role, so
each style follows light and dark mode without being rebuilt.
"""

from dataclasses import dataclass

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme
from app.components.frontend.theme import FontConfig

C = Theme.Colors


@dataclass(frozen=True)
class ButtonTextStyle:
    """Text styling for buttons."""

    weight: str = ft.FontWeight.W_400  # type: ignore[assignment]
    size: int = 16
    font_family: str = FontConfig.FAMILY_PRIMARY


def create_button_style(
    text_color: str, bgcolor: str, hover_bgcolor: str
) -> ft.ButtonStyle:
    """A filled, elevated button: hover lifts it, pressing settles it."""
    return ft.ButtonStyle(
        color={
            ft.ControlState.DEFAULT: text_color,
            ft.ControlState.DISABLED: ft.Colors.ON_SURFACE_VARIANT,
        },
        bgcolor={
            ft.ControlState.DEFAULT: bgcolor,
            ft.ControlState.HOVERED: hover_bgcolor,
            ft.ControlState.FOCUSED: bgcolor,
            ft.ControlState.PRESSED: ft.Colors.with_opacity(0.8, bgcolor),
            ft.ControlState.DISABLED: C.SURFACE_3,
        },
        shape=ft.RoundedRectangleBorder(radius=10),
        overlay_color={
            ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
            ft.ControlState.PRESSED: ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE),
        },
        shadow_color=ft.Colors.with_opacity(0.25, ft.Colors.SHADOW),
        elevation={
            ft.ControlState.DEFAULT: 4,
            ft.ControlState.HOVERED: 8,
            ft.ControlState.FOCUSED: 6,
            ft.ControlState.PRESSED: 2,
            ft.ControlState.DISABLED: 0,
        },
        animation_duration=100,
    )


ELEVATED_BUTTON_UPDATE_STYLE = create_button_style(
    text_color=ft.Colors.ON_PRIMARY,
    bgcolor=C.PRIMARY,
    hover_bgcolor=ft.Colors.with_opacity(0.85, C.PRIMARY),
)

ELEVATED_BUTTON_CANCEL_STYLE = create_button_style(
    text_color=ft.Colors.ON_SURFACE,
    bgcolor=C.SURFACE_3,
    hover_bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.ON_SURFACE),
)


# -- Pulse buttons -----------------------------------------------------------
# Flat, outlined, tinted-fill buttons matching the htmx web frontend: no
# drop-shadow or elevation, a visible border, a translucent accent fill.


PulseButtonTextStyle = ButtonTextStyle(size=13)
"""Pulse uses text-sm (13px); body-weight, not bold."""


def create_pulse_button_style(accent: str) -> ft.ButtonStyle:
    """Build a flat, accent-tinted Pulse button style.

    Mirrors the Tailwind recipe
    ``bg-{accent}/10 border border-{accent} hover:bg-{accent}/20``
    used in the Pulse templates (see ``components/landing/hero.html``).
    """
    return ft.ButtonStyle(
        color={
            ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE,
            ft.ControlState.HOVERED: ft.Colors.ON_SURFACE,
            ft.ControlState.FOCUSED: ft.Colors.ON_SURFACE,
            ft.ControlState.PRESSED: ft.Colors.ON_SURFACE,
            ft.ControlState.DISABLED: ft.Colors.ON_SURFACE_VARIANT,
        },
        bgcolor={
            ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.10, accent),
            ft.ControlState.HOVERED: ft.Colors.with_opacity(0.20, accent),
            ft.ControlState.FOCUSED: ft.Colors.with_opacity(0.15, accent),
            ft.ControlState.PRESSED: ft.Colors.with_opacity(0.25, accent),
            ft.ControlState.DISABLED: ft.Colors.with_opacity(0.05, accent),
        },
        side={
            ft.ControlState.DEFAULT: ft.BorderSide(1, accent),
            ft.ControlState.HOVERED: ft.BorderSide(1, accent),
            ft.ControlState.DISABLED: ft.BorderSide(
                1, ft.Colors.with_opacity(0.4, accent)
            ),
        },
        shape=ft.RoundedRectangleBorder(radius=8),
        padding=ft.padding.symmetric(horizontal=20, vertical=10),
        elevation=0,
        overlay_color=ft.Colors.TRANSPARENT,
        animation_duration=150,
    )


PULSE_BUTTON_TEAL_STYLE = create_pulse_button_style(C.PRIMARY)
PULSE_BUTTON_AMBER_STYLE = create_pulse_button_style(C.WARNING)
PULSE_BUTTON_STOP_STYLE = create_pulse_button_style(C.ERROR)


PULSE_BUTTON_MUTED_STYLE = ft.ButtonStyle(
    # Matches the "Dashboard" header link in Pulse's base.html:
    # ``text-aegis-muted border border-aegis-border hover:text-aegis-text
    # hover:border-aegis-muted`` - a subtle neutral button for secondary
    # actions (Cancel, Copy) that shouldn't compete with the primary CTA.
    color={
        ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE_VARIANT,
        ft.ControlState.HOVERED: ft.Colors.ON_SURFACE,
        ft.ControlState.FOCUSED: ft.Colors.ON_SURFACE,
        ft.ControlState.PRESSED: ft.Colors.ON_SURFACE,
        ft.ControlState.DISABLED: ft.Colors.with_opacity(
            0.4, ft.Colors.ON_SURFACE_VARIANT
        ),
    },
    bgcolor=ft.Colors.TRANSPARENT,
    side={
        ft.ControlState.DEFAULT: ft.BorderSide(1, ft.Colors.OUTLINE),
        ft.ControlState.HOVERED: ft.BorderSide(1, ft.Colors.ON_SURFACE_VARIANT),
        ft.ControlState.DISABLED: ft.BorderSide(
            1, ft.Colors.with_opacity(0.4, ft.Colors.OUTLINE)
        ),
    },
    shape=ft.RoundedRectangleBorder(radius=8),
    padding=ft.padding.symmetric(horizontal=20, vertical=10),
    elevation=0,
    overlay_color=ft.Colors.TRANSPARENT,
    animation_duration=150,
)
