"""
Core styling system for Aegis Stack dashboard.

Centralized design system inspired by modern dev tools (ee-toolset, Supabase, Vercel).
Based on dataclass architecture for type-safe, maintainable styling.
"""

from dataclasses import asdict, dataclass

import flet as ft


@dataclass(frozen=True)
class BrandPalette:
    """Canonical Aegis brand accents — the single source for teal/amber/red.

    Everything that renders a brand accent derives from here: ``PulseColors``
    below, and ``DarkColorPalette`` in ``theme.py`` (which imports this — the
    dependency runs theme -> styles, so the source has to live here). The tool
    CLI (``aegis/cli/brand.py``) mirrors these literals because a generated app
    can't import the aegis tool; ``tests/cli/test_brand_palette_parity.py`` fails
    if the two ever drift.
    """

    TEAL: str = "#17CCBF"  # Primary teal/cyan accent (and success state)
    TEAL_DARK: str = "#248F87"  # Secondary/darker teal
    AMBER: str = "#F5A623"  # Warning amber
    RED: str = "#E23E3E"  # Destructive/error red


@dataclass(frozen=True)
class ColorPalette:
    """
    Dark mode color palette for modern, sleek UI.

    Pure black base with vibrant accents for professional appearance.
    """

    BG_PRIMARY: str = "#000000"  # Pure black base
    BG_SECONDARY: str = "#1A1A1A"  # Slightly elevated surfaces
    BG_SELECTED: str = "#2E2E2E"  # Selected/active states
    BG_HOVER: str = "#2A2A2A"  # Hover states
    TEXT_PRIMARY_DEFAULT: str = "#E5E5E5"  # Main content text
    TEXT_SECONDARY_DEFAULT: str = "#B0B0B0"  # Supporting text
    ACCENT: str = "#1A73E8"  # Primary action color (blue)
    ACCENT_SUCCESS: str = "#52D869"  # Success states (green)
    ACCENT_STOP: str = "#E94E77"  # Destructive actions (red)
    ERROR: str = "#FF6B6B"  # Error states
    BORDER_PRIMARY: str = "#444444"  # Default borders
    DISABLED_COLOR: str = "#7F7F7F"  # Disabled states
    FOCUS_COLOR: str = "#FF6347"  # Focus indicators


@dataclass(frozen=True)
class ButtonColors:
    """Button color constants for different action types."""

    ADD_DEFAULT: str = "#1A73E8"
    ADD_BORDER_HOVERED: str = "#1558C0"
    DELETE_DEFAULT: str = "#E94E77"
    DELETE_BORDER_HOVERED: str = "#FF5A85"
    CANCEL_DEFAULT: str = "#282828"
    CANCEL_BORDER_HOVERED: str = "#444444"
    UPDATE_DEFAULT: str = ADD_DEFAULT
    UPDATE_BORDER_HOVERED: str = ADD_BORDER_HOVERED
    REFRESH_DEFAULT: str = "#1E8E3E"
    REFRESH_BORDER_HOVERED: str = "#137333"


@dataclass(frozen=True)
class PulseColors:
    """Aegis Pulse palette — shared with the server-rendered web frontend.

    Kept distinct from ``ColorPalette`` because Pulse is a deliberate
    restyle (flat, monochrome-first, teal-accented) rather than a drop-in
    replacement. New visuals that match the Pulse look should pull from
    here; legacy styles keep using ``ColorPalette``.
    """

    BG: str = "#090B0D"
    CARD: str = "#111418"
    BORDER: str = "#272C36"
    TEXT: str = "#EEF1F4"
    MUTED: str = "#7E8A9A"
    TEAL: str = BrandPalette.TEAL
    AMBER: str = BrandPalette.AMBER  # brand amber (was drifted to #F59E0B)
    STOP: str = BrandPalette.RED


@dataclass(frozen=True)
class FontConfig:
    """Typography configuration for consistent text styling."""

    FAMILY_PRIMARY: str = "Roboto"
    # Figures only: money, counts, percentages, axis ticks.
    #
    # Roboto's digits are proportional, so a "1" is narrower than a "0" and a
    # right-aligned column of amounts shifts as the digits change. A tabular
    # (monospaced) face gives every digit the same advance width, which is
    # what makes a column of numbers sit still and read as a column.
    #
    # Flet 0.28 exposes only ``font_family`` on Text, with no access to the
    # OpenType ``tnum`` feature, so tabular figures have to come from the
    # typeface itself rather than from a font-feature setting. ``monospace``
    # resolves to the platform's default fixed-width face with no bundled
    # asset and no network. To pin a specific typeface instead, drop the file
    # in ``assets/fonts/`` and register it on the page with
    # ``page.fonts = {"Aegis Numeric": "/fonts/<file>.ttf"}``, then set this
    # to that name.
    FAMILY_NUMERIC: str = "monospace"
    SIZE_PRIMARY: int = 16
    SIZE_SECONDARY: int = 14
    SIZE_TERTIARY: int = 12
    HEADER_SIZE: int = 24
    HEADING_SIZE: int = 18


@dataclass(frozen=True)
class ButtonTextStyle:
    """Text styling for buttons."""

    weight: str = ft.FontWeight.W_400  # type: ignore[assignment]
    size: int = 16
    font_family: str = FontConfig.FAMILY_PRIMARY


# Create instances for each button type
AddButtonTextStyle = ButtonTextStyle()
UpdateButtonTextStyle = ButtonTextStyle()
DeleteButtonTextStyle = ButtonTextStyle()
CancelButtonTextStyle = ButtonTextStyle()
RefreshButtonTextStyle = ButtonTextStyle()


@dataclass(frozen=True)
class Style:
    """Base style class with dict conversion support."""

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True)
class TextStyle(Style):
    """Base text style with common properties."""

    color: str
    font_family: str
    size: int
    weight: str


@dataclass(frozen=True)
class PrimaryTextStyle(TextStyle):
    """Primary text style for main content."""

    color: str = ColorPalette.TEXT_PRIMARY_DEFAULT
    font_family: str = FontConfig.FAMILY_PRIMARY
    size: int = FontConfig.SIZE_PRIMARY
    weight: str = ft.FontWeight.W_400  # type: ignore[assignment]


@dataclass(frozen=True)
class SecondaryTextStyle(TextStyle):
    """Secondary text style for supporting content."""

    color: str = ColorPalette.TEXT_SECONDARY_DEFAULT
    font_family: str = FontConfig.FAMILY_PRIMARY
    size: int = FontConfig.SIZE_SECONDARY
    weight: str = ft.FontWeight.W_400  # type: ignore[assignment]


@dataclass(frozen=True)
class ConfirmationTextStyle(TextStyle):
    """Text style for confirmation/warning messages."""

    color: str = ColorPalette.ERROR
    font_family: str = FontConfig.FAMILY_PRIMARY
    size: int = FontConfig.SIZE_SECONDARY
    weight: str = ft.FontWeight.W_400  # type: ignore[assignment]


@dataclass(frozen=True)
class TitleTextStyle(TextStyle):
    """Text style for titles and headers."""

    color: str = ColorPalette.TEXT_PRIMARY_DEFAULT
    font_family: str = FontConfig.FAMILY_PRIMARY
    size: int = FontConfig.HEADER_SIZE
    weight: str = ft.FontWeight.W_700  # type: ignore[assignment]


@dataclass(frozen=True)
class ModalTitle(PrimaryTextStyle):
    """Text style for modal titles."""

    weight: str = ft.FontWeight.W_700  # type: ignore[assignment]


@dataclass(frozen=True)
class ModalSubtitle(SecondaryTextStyle):
    """Text style for modal subtitles."""

    weight: str = ft.FontWeight.W_400  # type: ignore[assignment]


@dataclass(frozen=True)
class TertiaryLabel(PrimaryTextStyle):
    """Small label text style."""

    weight: str = ft.FontWeight.W_600  # type: ignore[assignment]
    size: int = FontConfig.SIZE_TERTIARY


@dataclass(frozen=True)
class SidebarLabelHeadingStyle(PrimaryTextStyle):
    """Text style for sidebar headings."""

    weight: str = ft.FontWeight.W_700  # type: ignore[assignment]


@dataclass(frozen=True)
class SidebarLabelStyle(SecondaryTextStyle):
    """Text style for sidebar labels."""

    weight: str = ft.FontWeight.W_400  # type: ignore[assignment]


@dataclass(frozen=True)
class SliderLabelStyle(SecondaryTextStyle):
    """Text style for slider labels."""

    weight: str = ft.FontWeight.W_700  # type: ignore[assignment]


@dataclass(frozen=True)
class SliderValueStyle(SecondaryTextStyle):
    """Text style for slider values."""

    pass


def create_button_style(
    text_color: str,
    default_bgcolor: str,
    hover_bgcolor: str,
    focus_bgcolor: str,
    active_bgcolor: str,
    disabled_bgcolor: str = "#3A3A3A",  # Gray for disabled state
) -> ft.ButtonStyle:
    """
    Create a ButtonStyle with consistent hover, focus, and pressed states.

    Features:
    - Dramatic elevation changes on hover (4→8)
    - Fast animations (100ms) for responsive feel
    - Subtle shadows for depth
    - Theme-aware disabled states
    """
    return ft.ButtonStyle(
        color={
            ft.ControlState.DEFAULT: text_color,
            ft.ControlState.HOVERED: text_color,
            ft.ControlState.FOCUSED: text_color,
            ft.ControlState.PRESSED: text_color,
            ft.ControlState.DISABLED: "#7F7F7F",  # Gray disabled text
        },
        bgcolor={
            ft.ControlState.DEFAULT: default_bgcolor,
            ft.ControlState.HOVERED: hover_bgcolor,
            ft.ControlState.FOCUSED: focus_bgcolor,
            ft.ControlState.PRESSED: active_bgcolor,
            ft.ControlState.DISABLED: disabled_bgcolor,
        },
        shape=ft.RoundedRectangleBorder(radius=10),
        overlay_color={
            ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
            ft.ControlState.HOVERED: ft.Colors.TRANSPARENT,
            ft.ControlState.FOCUSED: ft.Colors.TRANSPARENT,
            ft.ControlState.PRESSED: ft.Colors.with_opacity(0.1, ft.Colors.WHITE),
            ft.ControlState.DISABLED: ft.Colors.TRANSPARENT,
        },
        shadow_color=ft.Colors.with_opacity(0.25, ft.Colors.BLACK),
        elevation={
            ft.ControlState.DEFAULT: 4,
            ft.ControlState.HOVERED: 8,  # Dramatic hover effect
            ft.ControlState.FOCUSED: 6,
            ft.ControlState.PRESSED: 2,
            ft.ControlState.DISABLED: 0,
        },
        animation_duration=100,  # Fast animation for responsive feel
    )


# Button style presets
ELEVATED_BUTTON_ADD_STYLE = create_button_style(
    text_color=ft.Colors.WHITE,
    default_bgcolor=ButtonColors.ADD_DEFAULT,
    hover_bgcolor=ButtonColors.ADD_BORDER_HOVERED,
    focus_bgcolor=ButtonColors.ADD_DEFAULT,
    active_bgcolor=ft.Colors.with_opacity(0.8, ButtonColors.ADD_DEFAULT),
)

ELEVATED_BUTTON_UPDATE_STYLE = create_button_style(
    text_color=ft.Colors.WHITE,
    default_bgcolor=ButtonColors.UPDATE_DEFAULT,
    hover_bgcolor=ButtonColors.UPDATE_BORDER_HOVERED,
    focus_bgcolor=ButtonColors.UPDATE_DEFAULT,
    active_bgcolor=ft.Colors.with_opacity(0.8, ButtonColors.UPDATE_DEFAULT),
)

ELEVATED_BUTTON_DELETE_STYLE = create_button_style(
    text_color=ft.Colors.WHITE,
    default_bgcolor=ButtonColors.DELETE_DEFAULT,
    hover_bgcolor=ButtonColors.DELETE_BORDER_HOVERED,
    focus_bgcolor=ButtonColors.DELETE_DEFAULT,
    active_bgcolor=ft.Colors.with_opacity(0.8, ButtonColors.DELETE_DEFAULT),
)

ELEVATED_BUTTON_CANCEL_STYLE = create_button_style(
    text_color=ColorPalette.TEXT_PRIMARY_DEFAULT,
    default_bgcolor=ButtonColors.CANCEL_DEFAULT,
    hover_bgcolor=ButtonColors.CANCEL_BORDER_HOVERED,
    focus_bgcolor=ButtonColors.CANCEL_DEFAULT,
    active_bgcolor=ft.Colors.with_opacity(0.8, ButtonColors.CANCEL_DEFAULT),
)

ELEVATED_BUTTON_REFRESH_STYLE = create_button_style(
    text_color=ft.Colors.WHITE,
    default_bgcolor=ButtonColors.REFRESH_DEFAULT,
    hover_bgcolor=ButtonColors.REFRESH_BORDER_HOVERED,
    focus_bgcolor=ButtonColors.REFRESH_DEFAULT,
    active_bgcolor=ft.Colors.with_opacity(0.8, ButtonColors.REFRESH_DEFAULT),
)

ELEVATED_BUTTON_LOGOUT_STYLE = create_button_style(
    text_color=ft.Colors.WHITE,
    default_bgcolor=ButtonColors.DELETE_DEFAULT,
    hover_bgcolor=ButtonColors.DELETE_BORDER_HOVERED,
    focus_bgcolor=ButtonColors.DELETE_DEFAULT,
    active_bgcolor=ft.Colors.with_opacity(0.8, ButtonColors.DELETE_DEFAULT),
)


# -- Pulse buttons -----------------------------------------------------------
# Flat, outlined, tinted-fill buttons matching the Aegis Pulse web frontend.
# Differ from ``create_button_style`` above: no drop-shadow / elevation,
# visible border, translucent accent fill. Use for new surfaces that should
# feel "intentional and modern" rather than Material-elevated.


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
            ft.ControlState.DEFAULT: PulseColors.TEXT,
            ft.ControlState.HOVERED: ft.Colors.WHITE,
            ft.ControlState.FOCUSED: ft.Colors.WHITE,
            ft.ControlState.PRESSED: ft.Colors.WHITE,
            ft.ControlState.DISABLED: PulseColors.MUTED,
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


PULSE_BUTTON_TEAL_STYLE = create_pulse_button_style(PulseColors.TEAL)
PULSE_BUTTON_AMBER_STYLE = create_pulse_button_style(PulseColors.AMBER)
PULSE_BUTTON_STOP_STYLE = create_pulse_button_style(PulseColors.STOP)


PULSE_BUTTON_MUTED_STYLE = ft.ButtonStyle(
    # Matches the "Dashboard" header link in Pulse's base.html:
    # ``text-aegis-muted border border-aegis-border hover:text-white
    # hover:border-aegis-muted`` — a subtle neutral button for secondary
    # actions (Cancel, Copy) that shouldn't compete with the primary CTA.
    color={
        ft.ControlState.DEFAULT: PulseColors.MUTED,
        ft.ControlState.HOVERED: ft.Colors.WHITE,
        ft.ControlState.FOCUSED: ft.Colors.WHITE,
        ft.ControlState.PRESSED: ft.Colors.WHITE,
        ft.ControlState.DISABLED: ft.Colors.with_opacity(0.4, PulseColors.MUTED),
    },
    bgcolor=ft.Colors.TRANSPARENT,
    side={
        ft.ControlState.DEFAULT: ft.BorderSide(1, PulseColors.BORDER),
        ft.ControlState.HOVERED: ft.BorderSide(1, PulseColors.MUTED),
        ft.ControlState.DISABLED: ft.BorderSide(
            1, ft.Colors.with_opacity(0.4, PulseColors.BORDER)
        ),
    },
    shape=ft.RoundedRectangleBorder(radius=8),
    padding=ft.padding.symmetric(horizontal=20, vertical=10),
    elevation=0,
    overlay_color=ft.Colors.TRANSPARENT,
    animation_duration=150,
)
