"""Overseer's theme: one palette, two colour schemes, tokens that follow the mode.

The palette is ``app/core/palette.json``, the same file the htmx build
reads (``tailwind.config.js``), so the two frontends never disagree on a
colour. ``AegisTheme.build`` turns one mode of it into a Material 3 theme;
the page carries both (``page.theme`` light, ``page.dark_theme`` dark) and
``page.theme_mode`` picks.

Every colour token below names a ROLE of those schemes, never a value, so
Flutter resolves it per mode on the client: flipping the mode repaints
every control without rebuilding one. A hex value or a Material swatch in
a control is one mode's colour (``tests/components/frontend/
test_theme_modes.py`` refuses them).
"""

from dataclasses import dataclass

import flet as ft

from app.core.appearance import PALETTE

# Categorical colours (chart series, method badges, metric tiles): the
# palette's chart sequence.
# ponytail: one mode's series; Flet names no theme role for an eleventh
# colour, so the series stays the dark set in both modes (mid-tones that
# read on either background). Mode-aware needs a repaint on toggle.
SERIES: tuple[str, ...] = tuple(
    PALETTE["dark"][f"--aegis-chart-{n}"] for n in range(1, 12)
)


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


def _ink_on(fill: str) -> str:
    """Black or white, whichever reads better on ``fill`` (a hex colour):
    what DaisyUI derives as a colour's ``-content`` for the htmx side."""

    def channel(hex_pair: str) -> float:
        c = int(hex_pair, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(fill[i : i + 2]) for i in (1, 3, 5))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (
        "#000000"
        if (luminance + 0.05) / 0.05 > 1.05 / (luminance + 0.05)
        else "#FFFFFF"
    )


class _PopupMenuTheme(ft.PopupMenuTheme):
    """Constructible ``PopupMenuTheme`` for flet 0.28.3.

    Upstream's ``__post_init__`` was copy-pasted from ``SliderTheme`` and
    references fields this class does not have (``thumb_size``,
    ``year_2023``), so constructing the stock class always raises. This
    override keeps the one line that belongs here - normalizing
    ``mouse_cursor`` into the control-state dict the serializer expects.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.mouse_cursor, dict):
            self.mouse_cursor = {ft.ControlState.DEFAULT: self.mouse_cursor}


class AegisTheme:
    """Overseer's design tokens, and the Material 3 theme for each mode."""

    class Colors:
        """What a colour means, for the colours that carry meaning.

        Each names a scheme role, so Flutter resolves it per mode. Anything
        structural names its role directly: ``ft.Colors.SURFACE`` (the page,
        palette ``base-200``), ``SURFACE_CONTAINER_HIGHEST`` (a card,
        ``base-100``), ``ON_SURFACE`` (text), ``ON_SURFACE_VARIANT`` (muted
        text), ``OUTLINE`` (a border or divider), ``SHADOW``, ``SCRIM``,
        ``ON_PRIMARY``/``ON_ERROR`` (ink on a fill). The tones live here
        because their roles do not say what they mean: warning is
        ``TERTIARY``, info is ``SECONDARY``.
        """

        # Washes over a surface, in the text colour so they read in either mode.
        SURFACE_2 = ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE)  # hover
        SURFACE_3 = ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)  # selected

        PRIMARY = ft.Colors.PRIMARY
        SUCCESS = ft.Colors.PRIMARY
        ERROR = ft.Colors.ERROR
        WARNING = ft.Colors.TERTIARY
        INFO = ft.Colors.SECONDARY

        @classmethod
        def semantic(cls, name: str) -> str:
            """A shared semantic colour name (green, blue, yellow, red, grey, as
            ``get_status_color_name`` and ``ui_auth`` return) in this theme."""
            tone = {"green": "ok", "yellow": "warn", "red": "error", "grey": "muted"}
            if name == "blue":
                return cls.INFO
            return TONE_COLORS[tone.get(name, "warn")]

    class Typography:
        """Typography scale and weights."""

        # Size Scale (px)
        DISPLAY = 32
        H1 = 28
        H2 = 24
        H3 = 18
        BODY_LARGE = 16
        BODY = 14
        BODY_SMALL = 12
        CAPTION = 10

        # Font Weights
        WEIGHT_REGULAR = ft.FontWeight.W_400
        WEIGHT_MEDIUM = ft.FontWeight.W_500
        WEIGHT_SEMIBOLD = ft.FontWeight.W_600
        WEIGHT_BOLD = ft.FontWeight.W_700

    class Spacing:
        """Spacing system based on 8px grid."""

        XS = 4
        SM = 8
        MD = 16
        LG = 24
        XL = 32
        XXL = 48

    class Components:
        """Component-specific styling constants."""

        # Border Radius
        CARD_RADIUS = 12
        BADGE_RADIUS = 8
        BUTTON_RADIUS = 6
        INPUT_RADIUS = 6

        # Under every floating panel: dialogs, popups, dropdown menus.
        POPUP_SHADOW = ft.BoxShadow(
            spread_radius=0,
            blur_radius=20,
            color=ft.Colors.with_opacity(0.3, ft.Colors.SHADOW),
            offset=ft.Offset(0, 4),
        )

    @staticmethod
    def build(mode: str) -> ft.Theme:
        """The Material 3 theme for one mode (``dark`` or ``light``) of the palette."""
        p = PALETTE[mode]
        other = PALETTE["light" if mode == "dark" else "dark"]
        ink, muted, card = p["base-content"], p["neutral"], p["base-100"]
        color_scheme = ft.ColorScheme(
            primary=p["primary"],
            on_primary=_ink_on(p["primary"]),
            primary_container=p["base-200"],
            on_primary_container=ink,
            secondary=p["info"],
            on_secondary=_ink_on(p["info"]),
            secondary_container=p["base-300"],
            on_secondary_container=ink,
            tertiary=p["warning"],
            on_tertiary=_ink_on(p["warning"]),
            tertiary_container=card,
            on_tertiary_container=ink,
            error=p["error"],
            on_error=_ink_on(p["error"]),
            error_container=card,
            on_error_container=ink,
            surface=p["base-200"],
            on_surface=ink,
            # Flutter reads ``surfaceContainerHighest`` from this: the card.
            surface_variant=card,
            on_surface_variant=muted,
            surface_container=card,
            surface_container_low=card,
            surface_container_high=card,
            surface_container_lowest=p["base-200"],
            outline=p["base-300"],
            outline_variant=p["base-300"],
            shadow="#000000",
            scrim="#000000",
            surface_tint=ft.Colors.TRANSPARENT,
            inverse_surface=other["base-100"],
            on_inverse_surface=other["base-content"],
            inverse_primary=other["primary"],
        )

        def face(size: int, weight: ft.FontWeight, color: str) -> ft.TextStyle:
            return ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=size,
                weight=weight,
                color=color,
            )

        theme = ft.Theme(
            color_scheme=color_scheme,
            text_theme=ft.TextTheme(
                display_large=face(32, ft.FontWeight.W_300, ink),
                headline_large=face(24, ft.FontWeight.W_700, ink),
                headline_medium=face(18, ft.FontWeight.W_600, ink),
                body_large=face(16, ft.FontWeight.W_400, ink),
                body_medium=face(14, ft.FontWeight.W_400, ink),
                body_small=face(12, ft.FontWeight.W_400, muted),
            ),
            use_material3=True,
        )

        # Popup menus (kebab menus, the account filter) style from the THEME,
        # not from the button that opened them - per-call styling never
        # sticks, which is why they kept rendering as stock Material. This
        # gives every popup the card treatment: card surface, no Material
        # tint wash, the card corner radius, primary-face text.
        theme.popup_menu_theme = _PopupMenuTheme(
            color=card,
            surface_tint_color=ft.Colors.TRANSPARENT,
            shape=ft.RoundedRectangleBorder(radius=12),
            elevation=4,
            text_style=face(13, ft.FontWeight.W_400, ink),
        )

        # Every divider is a border line, without each one saying so.
        theme.divider_theme = ft.DividerTheme(color=p["base-300"])

        # Instant transitions
        theme.page_transitions = ft.PageTransitionsTheme(
            android=ft.PageTransitionTheme.NONE,
            ios=ft.PageTransitionTheme.NONE,
            linux=ft.PageTransitionTheme.NONE,
            macos=ft.PageTransitionTheme.NONE,
            windows=ft.PageTransitionTheme.NONE,
        )

        return theme


# A tone's colour (ok, warn, error, muted): what htmx's ``data-tone`` CSS
# reads, for Flet's badges, log lines and chart guides alike.
TONE_COLORS = {
    "ok": AegisTheme.Colors.SUCCESS,
    "warn": AegisTheme.Colors.WARNING,
    "error": AegisTheme.Colors.ERROR,
    "muted": ft.Colors.ON_SURFACE_VARIANT,
}
