"""What the two configuration tabs do the same way.

Email and SMS/Voice each show what a provider is configured with and,
in dev mode, let it be edited. That part was written twice - the same
constructor preamble, the same rebuild-on-mode-change, the same cancel
- and two copies of a contract is two places for it to drift.

This owns the contract: which mode the tab is in, and that changing it
rebuilds. What goes in each mode stays with the tab that knows its own
fields.
"""

from collections.abc import Callable
from typing import Any

import flet as ft
from app.services.system.env_config import EnvConfigService


class EditableConfigTab(ft.Container):
    """A provider configuration tab that can be edited in dev mode."""

    def __init__(
        self,
        metadata: dict[str, Any],
        on_config_saved: Callable[[], Any] | None = None,
    ) -> None:
        """
        Args:
            metadata: Component metadata containing the provider configuration
            on_config_saved: Callback when configuration is saved (for refresh)
        """
        super().__init__()

        self._metadata = metadata
        self._on_config_saved = on_config_saved
        self._edit_mode = False
        self._saving = False
        self._env_service = EnvConfigService()

        # Editing writes .env, so it is offered in dev mode only.
        self._can_edit = self._env_service.is_dev_mode()

    def _build_content(self) -> None:
        """Build the tab content based on current mode."""
        if self._edit_mode:
            self._build_edit_mode()
        else:
            self._build_view_mode()

        if self.page:
            self.update()

    def _toggle_edit_mode(self, e: ft.ControlEvent | None = None) -> None:
        """Toggle between view and edit modes."""
        self._edit_mode = not self._edit_mode
        self._build_content()
        if self.page:
            self.update()

    async def _cancel_edit(self) -> None:
        """Cancel edit mode and return to view mode.

        Not a toggle: from either mode this lands in view mode.
        """
        self._edit_mode = False
        self._build_content()
        if self.page:
            self.update()

    def _build_view_mode(self) -> None:
        """Render what the provider is configured with."""
        raise NotImplementedError

    def _build_edit_mode(self) -> None:
        """Render the form that changes it."""
        raise NotImplementedError
