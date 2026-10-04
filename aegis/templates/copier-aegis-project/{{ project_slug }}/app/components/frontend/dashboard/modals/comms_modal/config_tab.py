"""What the two configuration tabs do the same way.

Email and SMS/Voice each show what a provider is configured with and
let it be edited: through the secrets store when the stack has one (the
secrets API, behind ``get_admin_actor``: checked with the provider, audited, live), else
by writing ``.env`` in dev mode. That part was written twice - the same
constructor preamble, the same rebuild-on-mode-change, the same cancel
- and two copies of a contract is two places for it to drift.

This owns the contract: which mode the tab is in, and that changing it
rebuilds. What goes in each mode stays with the tab that knows its own
fields.
"""

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.state.session_state import get_session_state
from app.core import secrets
from app.core.client import error_detail
from app.core.config import reload_settings
from app.services.system.env_config import EnvConfigService

SECRETS_API = "/api/v1/secrets"


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
        self._page_ref: ft.Page | None = None

        # The secrets store takes writes anywhere; ``.env`` in dev mode only.
        self._can_edit = secrets.writable() or self._env_service.is_dev_mode()

    @property
    def _host(self) -> ft.Page:
        return self._page_ref or self.page

    async def _save_credentials(self, updates: dict[str, str]) -> bool:
        """Save provider settings where this stack keeps them; False when
        one is refused (the reason is shown)."""
        if not secrets.writable():
            self._env_service.write_env(updates)
            reload_settings()
            return True
        api = get_session_state(self._host).api_client
        for name, value in updates.items():
            if value:
                status, body = await api.request_with_status(
                    "PUT", f"{SECRETS_API}/{name}", json={"value": value}
                )
            else:
                status, body = await api.request_with_status(
                    "DELETE", f"{SECRETS_API}/{name}"
                )
            if status not in (200, 204):
                ErrorSnackBar(
                    f"{name} was not saved: {error_detail(body, status)}"
                ).launch(self._host)
                return False
        return True

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
