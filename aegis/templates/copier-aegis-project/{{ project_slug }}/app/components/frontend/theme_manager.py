"""Applying a theme to a page, and switching between them.

The palettes and the token surface live in ``theme``; this is the
part that holds a page and mutates it.
"""

import flet as ft

from app.components.frontend.theme import AegisTheme


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
