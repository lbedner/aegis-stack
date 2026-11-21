"""Applying a theme to a page, and switching between them.

The palette and the token surface live in ``theme``; this is the part that
holds a page and mutates it. The mode is htmx's: the dashboard page's mode
bridge (``backend/middleware/dashboard_scripts``) copies htmx's stored choice into
``MODE_KEY`` before Flutter boots, and copies a toggle here back.
"""

import flet as ft

from app.components.frontend.theme import AegisTheme
from app.core.appearance import FLET_MODE_KEY as MODE_KEY

__all__ = ["MODE_KEY", "ThemeManager"]


class ThemeManager:
    """Holds a page's light/dark mode: the stored choice, and the toggle."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._mode = ft.ThemeMode.DARK

    async def initialize_themes(self) -> None:
        """Give the page both themes and open it in the stored mode."""
        try:
            stored = await self.page.client_storage.get_async(MODE_KEY)
        except TimeoutError:
            stored = None
        modes = {mode.value: mode for mode in ft.ThemeMode}
        self._mode = modes.get(str(stored), ft.ThemeMode.DARK)
        self.page.theme = AegisTheme.build("light")
        self.page.dark_theme = AegisTheme.build("dark")
        self.page.theme_mode = self._mode
        self.page.update()

    async def toggle_theme(self) -> None:
        """Flip what shows, and store it (the bridge hands it to htmx).
        The caller repaints, once it has also changed what offers the flip."""
        self._mode = ft.ThemeMode.LIGHT if self.is_dark_mode else ft.ThemeMode.DARK
        self.page.theme_mode = self._mode
        await self.page.client_storage.set_async(MODE_KEY, self._mode.value)

    @property
    def is_dark_mode(self) -> bool:
        """Whether the page shows dark now (``system`` asks the platform)."""
        if self._mode == ft.ThemeMode.SYSTEM:
            return self.page.platform_brightness == ft.Brightness.DARK
        return self._mode == ft.ThemeMode.DARK
