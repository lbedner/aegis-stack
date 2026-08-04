"""
Enhanced theme management for Aegis Stack dashboard.

Provides comprehensive theme system with Material3 integration,
full light/dark mode support, and smooth theme transitions.
"""

from dataclasses import dataclass

import flet as ft

from app.components.frontend.styles import BrandPalette, FontConfig


@dataclass(frozen=True)
class DarkColorPalette:
    """Dark mode color palette - official design system colors."""

    # Core colors
    BG_PRIMARY: str = "#090B0D"  # Main page background
    BG_SECONDARY: str = "#111418"  # Card backgrounds
    BG_SELECTED: str = "#212530"  # Secondary/selected states
    BG_HOVER: str = "#1A1D24"  # Muted/hover backgrounds

    # Text colors
    TEXT_PRIMARY_DEFAULT: str = "#EEF1F4"  # Main text (foreground)
    TEXT_SECONDARY_DEFAULT: str = "#7E8A9A"  # Muted/placeholder text

    # Brand colors — derived from the canonical BrandPalette (styles.py)
    ACCENT: str = BrandPalette.TEAL  # Primary teal/cyan
    ACCENT_SECONDARY: str = BrandPalette.TEAL_DARK  # Darker teal (secondary accent)

    # Semantic colors
    ACCENT_SUCCESS: str = BrandPalette.TEAL  # Success teal (brand standard)
    ACCENT_WARNING: str = BrandPalette.AMBER  # Warning orange/amber
    ACCENT_STOP: str = BrandPalette.RED  # Destructive/error red
    ERROR: str = BrandPalette.RED  # Alias for destructive

    # UI elements
    BORDER_PRIMARY: str = "#272C36"  # Borders, dividers
    DISABLED_COLOR: str = "#7E8A9A"  # Same as muted text
    FOCUS_COLOR: str = BrandPalette.TEAL  # Teal focus


@dataclass(frozen=True)
class LightColorPalette:
    """Light mode color palette."""

    BG_PRIMARY: str = "#FFFFFF"
    BG_SECONDARY: str = "#FFFFFF"
    BG_SELECTED: str = "#E3F2FD"
    BG_HOVER: str = "#E8E8E8"
    TEXT_PRIMARY_DEFAULT: str = "#212121"
    TEXT_SECONDARY_DEFAULT: str = "#495057"
    ACCENT: str = "#2563eb"
    ACCENT_SUCCESS: str = BrandPalette.TEAL  # Success teal (brand standard)
    ACCENT_STOP: str = "#EF4444"
    ERROR: str = "#D32F2F"
    BORDER_PRIMARY: str = "#E0E3E7"
    DISABLED_COLOR: str = "#B0B0B0"
    DIVIDER_COLOR: str = (
        "#9E9E9E"  # Darker gray for dividers (better light mode visibility)
    )
    FOCUS_COLOR: str = "#2563eb"


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
    """
    Creates Material3 Theme objects for Aegis Stack.

    Integrates with Flet's native theme system for instant light/dark switching.
    """

    # Nested classes for backward compatibility with existing components
    # Using ee-toolset colors for modern, dark, sleek look
    class Colors:
        """Color palette - pure black base from ee-toolset."""

        # Background colors - PURE BLACK like ee-toolset
        SURFACE_0 = DarkColorPalette.BG_PRIMARY  # #000000
        SURFACE_1 = DarkColorPalette.BG_SECONDARY  # #1A1A1A
        SURFACE_2 = DarkColorPalette.BG_HOVER  # #2A2A2A
        SURFACE_3 = DarkColorPalette.BG_SELECTED  # #2E2E2E

        # Text colors from ee-toolset
        TEXT_PRIMARY = DarkColorPalette.TEXT_PRIMARY_DEFAULT  # #E5E5E5
        TEXT_SECONDARY = DarkColorPalette.TEXT_SECONDARY_DEFAULT  # #B0B0B0
        TEXT_TERTIARY = DarkColorPalette.TEXT_SECONDARY_DEFAULT
        TEXT_DISABLED = DarkColorPalette.DISABLED_COLOR  # #7F7F7F

        # Accent & Action colors
        PRIMARY = DarkColorPalette.ACCENT  # #1A73E8
        ACCENT = DarkColorPalette.ACCENT
        ACCENT_GLOW = DarkColorPalette.ACCENT

        # Status colors
        SUCCESS = DarkColorPalette.ACCENT_SUCCESS  # teal (brand standard)
        ERROR = DarkColorPalette.ERROR  # #FF6B6B
        WARNING = ft.Colors.AMBER_400
        INFO = ft.Colors.BLUE

        # Borders from ee-toolset
        BORDER_SUBTLE = DarkColorPalette.BORDER_PRIMARY
        BORDER_DEFAULT = DarkColorPalette.BORDER_PRIMARY  # #444444
        BORDER_STRONG = DarkColorPalette.BORDER_PRIMARY

        # Other
        BADGE_TEXT = ft.Colors.WHITE
        PRIMARY_DARK = DarkColorPalette.ACCENT
        PRIMARY_LIGHT = DarkColorPalette.ACCENT

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

        # Elevation (shadow depth)
        CARD_ELEVATION = 2
        CARD_ELEVATION_HOVER = 4

        # Animation Durations (ms)
        TRANSITION_FAST = 150
        TRANSITION_NORMAL = 200
        TRANSITION_SLOW = 300

    @staticmethod
    def create_dark_theme() -> ft.Theme:
        """Create a dark theme with Aegis color palette."""
        color_scheme = ft.ColorScheme(
            # Primary colors
            primary=DarkColorPalette.ACCENT,
            on_primary=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            primary_container=DarkColorPalette.BG_PRIMARY,
            on_primary_container=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            # Secondary colors
            secondary=DarkColorPalette.TEXT_SECONDARY_DEFAULT,
            on_secondary=DarkColorPalette.BG_SECONDARY,
            secondary_container=DarkColorPalette.BG_SELECTED,
            on_secondary_container=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            # Tertiary colors
            tertiary=DarkColorPalette.ACCENT_SUCCESS,
            on_tertiary=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            tertiary_container=DarkColorPalette.BG_SECONDARY,
            on_tertiary_container=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            # Error colors
            error=DarkColorPalette.ERROR,
            on_error=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            error_container=DarkColorPalette.BG_SECONDARY,
            on_error_container=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            # Background colors
            background=DarkColorPalette.BG_PRIMARY,
            on_background=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            surface=DarkColorPalette.BG_PRIMARY,
            on_surface=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            surface_variant=DarkColorPalette.BG_SECONDARY,
            on_surface_variant=DarkColorPalette.TEXT_SECONDARY_DEFAULT,
            # Outline colors
            outline=DarkColorPalette.BORDER_PRIMARY,
            outline_variant=DarkColorPalette.DISABLED_COLOR,
            # Other colors
            shadow=ft.Colors.BLACK,
            scrim=ft.Colors.BLACK,
            inverse_surface=LightColorPalette.BG_PRIMARY,
            on_inverse_surface=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            inverse_primary=LightColorPalette.ACCENT,
        )

        text_theme = ft.TextTheme(
            display_large=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=32,
                weight=ft.FontWeight.W_300,
                color=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            headline_large=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=24,
                weight=ft.FontWeight.W_700,
                color=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            headline_medium=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=18,
                weight=ft.FontWeight.W_600,
                color=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            body_large=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=16,
                weight=ft.FontWeight.W_400,
                color=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            body_medium=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=14,
                weight=ft.FontWeight.W_400,
                color=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            body_small=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=12,
                weight=ft.FontWeight.W_400,
                color=DarkColorPalette.TEXT_SECONDARY_DEFAULT,
            ),
        )

        theme = ft.Theme(
            color_scheme=color_scheme,
            text_theme=text_theme,
            use_material3=True,
        )

        # Popup menus (kebab menus, the account filter) style from the THEME,
        # not from the button that opened them - per-call styling never
        # sticks, which is why they kept rendering as stock Material. This
        # gives every popup the card treatment: card surface, no Material
        # tint wash, the card corner radius, primary-face text.
        theme.popup_menu_theme = _PopupMenuTheme(
            color=DarkColorPalette.BG_SECONDARY,
            surface_tint_color=ft.Colors.TRANSPARENT,
            shape=ft.RoundedRectangleBorder(radius=12),
            elevation=4,
            text_style=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=13,
                color=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
        )





        # Instant transitions
        theme.page_transitions = ft.PageTransitionsTheme(
            android=ft.PageTransitionTheme.NONE,
            ios=ft.PageTransitionTheme.NONE,
            linux=ft.PageTransitionTheme.NONE,
            macos=ft.PageTransitionTheme.NONE,
            windows=ft.PageTransitionTheme.NONE,
        )

        return theme

    @staticmethod
    def create_light_theme() -> ft.Theme:
        """Create a light theme with Aegis color palette."""
        color_scheme = ft.ColorScheme(
            # Primary colors
            primary=LightColorPalette.ACCENT,
            on_primary=ft.Colors.WHITE,
            primary_container=LightColorPalette.BG_SECONDARY,
            on_primary_container=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            # Secondary colors
            secondary=LightColorPalette.TEXT_SECONDARY_DEFAULT,
            on_secondary=ft.Colors.WHITE,
            secondary_container=LightColorPalette.BG_SELECTED,
            on_secondary_container=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            # Tertiary colors
            tertiary=LightColorPalette.ACCENT_SUCCESS,
            on_tertiary=ft.Colors.WHITE,
            tertiary_container=LightColorPalette.BG_SECONDARY,
            on_tertiary_container=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            # Error colors
            error=LightColorPalette.ERROR,
            on_error=ft.Colors.WHITE,
            error_container=LightColorPalette.BG_SECONDARY,
            on_error_container=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            # Background colors
            background=LightColorPalette.BG_PRIMARY,
            on_background=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            surface=LightColorPalette.BG_SECONDARY,
            on_surface=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            surface_variant=LightColorPalette.BG_HOVER,
            on_surface_variant=LightColorPalette.TEXT_SECONDARY_DEFAULT,
            # Outline colors
            outline=LightColorPalette.DIVIDER_COLOR,
            outline_variant=LightColorPalette.DIVIDER_COLOR,
            # Other colors
            shadow=ft.Colors.BLACK38,
            scrim=ft.Colors.BLACK54,
            inverse_surface=DarkColorPalette.BG_PRIMARY,
            on_inverse_surface=DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            inverse_primary=DarkColorPalette.ACCENT,
        )

        text_theme = ft.TextTheme(
            display_large=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=32,
                weight=ft.FontWeight.W_300,
                color=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            headline_large=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=24,
                weight=ft.FontWeight.W_700,
                color=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            headline_medium=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=18,
                weight=ft.FontWeight.W_600,
                color=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            body_large=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=16,
                weight=ft.FontWeight.W_400,
                color=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            body_medium=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=14,
                weight=ft.FontWeight.W_400,
                color=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
            body_small=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=12,
                weight=ft.FontWeight.W_400,
                color=LightColorPalette.TEXT_SECONDARY_DEFAULT,
            ),
        )

        theme = ft.Theme(
            color_scheme=color_scheme,
            text_theme=text_theme,
            use_material3=True,
        )

        # Mirrors the dark theme's popup treatment (see create_dark_theme).
        theme.popup_menu_theme = _PopupMenuTheme(
            color=LightColorPalette.BG_SECONDARY,
            surface_tint_color=ft.Colors.TRANSPARENT,
            shape=ft.RoundedRectangleBorder(radius=12),
            elevation=4,
            text_style=ft.TextStyle(
                font_family=FontConfig.FAMILY_PRIMARY,
                size=13,
                color=LightColorPalette.TEXT_PRIMARY_DEFAULT,
            ),
        )



        # Instant transitions
        theme.page_transitions = ft.PageTransitionsTheme(
            android=ft.PageTransitionTheme.NONE,
            ios=ft.PageTransitionTheme.NONE,
            linux=ft.PageTransitionTheme.NONE,
            macos=ft.PageTransitionTheme.NONE,
            windows=ft.PageTransitionTheme.NONE,
        )

        return theme


class ThemeManager:
    """
    Manages theme switching and state for Aegis Stack dashboard.

    Provides instant light/dark mode switching with Material3 themes.
    """

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._current_theme_mode = ft.ThemeMode.DARK  # Default to dark
        self._themes_initialized = False

    async def initialize_themes(self) -> None:
        """Initialize both light and dark themes."""
        if self._themes_initialized:
            return

        # Set both themes
        self.page.theme = AegisTheme.create_light_theme()
        self.page.dark_theme = AegisTheme.create_dark_theme()
        self.page.theme_mode = self._current_theme_mode

        self._themes_initialized = True
        self.page.update()

    async def toggle_theme(self) -> None:
        """Toggle between light and dark mode."""
        if self._current_theme_mode == ft.ThemeMode.DARK:
            self._current_theme_mode = ft.ThemeMode.LIGHT
        else:
            self._current_theme_mode = ft.ThemeMode.DARK

        self.page.theme_mode = self._current_theme_mode
        self.page.update()

    @property
    def is_dark_mode(self) -> bool:
        """Check if current theme is dark mode."""
        return self._current_theme_mode == ft.ThemeMode.DARK

    @property
    def is_light_mode(self) -> bool:
        """Check if current theme is light mode."""
        return self._current_theme_mode == ft.ThemeMode.LIGHT

    def get_status_colors(self, is_healthy: bool) -> tuple[str, str, str]:
        """Get (background, text, border) colors for status indicators."""
        if is_healthy:
            if self.is_dark_mode:
                return (ft.Colors.TEAL_900, ft.Colors.TEAL_100, ft.Colors.TEAL)
            else:
                return (ft.Colors.TEAL_100, ft.Colors.TEAL_800, ft.Colors.TEAL)
        else:
            if self.is_dark_mode:
                return (ft.Colors.RED_900, ft.Colors.RED_100, ft.Colors.ERROR)
            else:
                return (ft.Colors.RED_100, ft.Colors.RED_800, ft.Colors.ERROR)

    def get_info_colors(self) -> tuple[str, str, str]:
        """Get (background, text, border) colors for info cards."""
        if self.is_dark_mode:
            return (ft.Colors.BLUE_900, ft.Colors.BLUE_100, ft.Colors.PRIMARY)
        else:
            return (ft.Colors.BLUE_100, ft.Colors.BLUE_800, ft.Colors.PRIMARY)

    """
    Centralized design system for Aegis Stack dashboard.

    High-tech dark theme inspired by modern dev tools (Supabase, Vercel).
    Single source of truth for colors, typography, spacing, and component styles.
    """

    class Colors:
        """Color palette - official design system colors."""

        # Primary Brand (Teal/Cyan - official)
        PRIMARY = "#17CCBF"  # Primary teal/cyan
        PRIMARY_DARK = "#248F87"  # Darker teal (secondary accent)
        PRIMARY_LIGHT = "#5eead4"  # Lighter teal

        # Accent (Vibrant highlights for CTAs and emphasis)
        ACCENT = "#17CCBF"  # Same as primary
        ACCENT_GLOW = "#17CCBF"  # Teal glow

        # Status Colors (Semantic feedback)
        SUCCESS = "#17CCBF"  # Success teal (brand standard)
        WARNING = ft.Colors.AMBER_400
        ERROR = ft.Colors.RED_400
        INFO = ft.Colors.BLUE

        # Surface Levels (Semantic - auto-adapt to light/dark mode)
        SURFACE_0 = ft.Colors.SURFACE  # Base background
        SURFACE_1 = ft.Colors.with_opacity(
            0.05, ft.Colors.ON_SURFACE
        )  # Slight elevation
        SURFACE_2 = ft.Colors.with_opacity(
            0.08, ft.Colors.ON_SURFACE
        )  # Medium elevation
        SURFACE_3 = ft.Colors.SURFACE_CONTAINER_HIGHEST  # Highest elevation

        # Text Colors (Semantic - auto-adapt to light/dark mode)
        TEXT_PRIMARY = ft.Colors.ON_SURFACE  # Main content text
        TEXT_SECONDARY = ft.Colors.ON_SURFACE_VARIANT  # Supporting text
        TEXT_TERTIARY = ft.Colors.ON_SURFACE_VARIANT  # De-emphasized text
        TEXT_DISABLED = ft.Colors.with_opacity(
            0.5, ft.Colors.ON_SURFACE_VARIANT
        )  # Disabled state (50% opacity)

        # Borders & Dividers (Semantic - auto-adapt to light/dark mode)
        BORDER_SUBTLE = ft.Colors.with_opacity(
            0.3, ft.Colors.OUTLINE_VARIANT
        )  # Minimal separation (30% opacity)
        BORDER_DEFAULT = ft.Colors.OUTLINE_VARIANT  # Standard borders
        BORDER_STRONG = ft.Colors.OUTLINE  # Emphasized borders

        # Badge & Chip Text (High contrast for colored backgrounds)
        BADGE_TEXT = (
            ft.Colors.WHITE
        )  # White text for status badges with colored backgrounds

    class Typography:
        """Typography scale and weights."""

        # Size Scale (px)
        DISPLAY = 32  # Hero/display text
        H1 = 28  # Page titles
        H2 = 24  # Major section headers
        H3 = 18  # Subsection headers
        BODY_LARGE = 16  # Emphasized body text
        BODY = 14  # Default body text
        BODY_SMALL = 12  # Supporting/secondary text
        CAPTION = 10  # Labels, captions, compact UI

        # Font Weights
        WEIGHT_REGULAR = ft.FontWeight.W_400
        WEIGHT_MEDIUM = ft.FontWeight.W_500
        WEIGHT_SEMIBOLD = ft.FontWeight.W_600
        WEIGHT_BOLD = ft.FontWeight.W_700

    class Spacing:
        """Spacing system based on 8px grid."""

        XS = 4  # Minimal spacing
        SM = 8  # Small spacing
        MD = 16  # Default spacing
        LG = 24  # Large spacing
        XL = 32  # Extra large spacing
        XXL = 48  # Maximum spacing

    class Components:
        """Component-specific styling constants."""

        # Border Radius
        CARD_RADIUS = 12  # Cards, containers
        BADGE_RADIUS = 8  # Badges, pills
        BUTTON_RADIUS = 6  # Buttons, inputs
        INPUT_RADIUS = 6  # Form inputs

        # Elevation (shadow depth)
        CARD_ELEVATION = 2  # Default card shadow
        CARD_ELEVATION_HOVER = 4  # Hover state shadow

        # Animation Durations (ms)
        TRANSITION_FAST = 150  # Quick interactions
        TRANSITION_NORMAL = 200  # Standard transitions
        TRANSITION_SLOW = 300  # Deliberate animations
