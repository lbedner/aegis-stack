"""The Email tab: what Resend is configured with, and editing it.

The API key field is never pre-filled - a secret that round-trips
through the form is a secret that can be read off the screen - so an
empty key on save means "leave it alone", not "clear it".
"""

from collections.abc import Callable
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.form_fields import (
    FormActionButtons,
    FormSecretField,
    FormTextField,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import reload_settings

from .config_tab import EditableConfigTab


class EmailTab(EditableConfigTab):
    """Email (Resend) configuration tab with edit mode support."""

    def __init__(
        self,
        metadata: dict[str, Any],
        on_config_saved: Callable[[], Any] | None = None,
    ) -> None:
        """
        Initialize email tab.

        Args:
            metadata: Component metadata containing Resend configuration
            on_config_saved: Callback when configuration is saved (for refresh)
        """
        super().__init__(metadata, on_config_saved)

        # Initialize form fields (created once, reused)
        self._api_key_field = FormSecretField(
            label="API Key",
            value="",  # Don't pre-fill secrets for security
            hint="re_...",
        )
        self._from_email_field = FormTextField(
            label="From Email",
            value=metadata.get("resend_from_email") or "",
            hint="noreply@example.com",
        )

        # Build initial view
        self._build_content()

    def _build_view_mode(self) -> None:
        """Build the view mode content (read-only display)."""
        email_configured = self._metadata.get("email_configured", False)
        resend_api_key_configured = self._metadata.get(
            "resend_api_key_configured", False
        )
        resend_from_email = self._metadata.get("resend_from_email", "Not configured")

        # Header with edit button (dev mode only)
        header_controls: list[ft.Control] = [H3Text("Resend Configuration")]
        if self._can_edit:
            header_controls.append(
                ft.IconButton(
                    icon=ft.Icons.EDIT,
                    icon_color=Theme.Colors.TEXT_SECONDARY,
                    icon_size=16,
                    tooltip="Edit configuration",
                    on_click=self._toggle_edit_mode,
                )
            )

        header_row = ft.Row(
            header_controls,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # API Key status row
        if resend_api_key_configured:
            api_key_content: ft.Control = Tag(
                text="Configured", color=Theme.Colors.SUCCESS
            )
        else:
            api_key_content = SecondaryText("—")

        api_key_row = ft.Row(
            [
                SecondaryText(
                    "API Key:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                api_key_content,
            ],
            spacing=Theme.Spacing.MD,
        )

        # From address row
        if resend_from_email and resend_from_email != "Not configured":
            from_content: ft.Control = BodyText(resend_from_email)
        else:
            from_content = SecondaryText("—")

        from_address_row = ft.Row(
            [
                SecondaryText(
                    "From Address:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                from_content,
            ],
            spacing=Theme.Spacing.MD,
        )

        # Status summary row
        if email_configured:
            status_content: ft.Control = Tag(text="Ready", color=Theme.Colors.SUCCESS)
        else:
            status_content = SecondaryText("—")

        status_row = ft.Row(
            [
                SecondaryText(
                    "Status:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                status_content,
            ],
            spacing=Theme.Spacing.MD,
        )

        self.content = ft.Column(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            header_row,
                            ft.Container(height=Theme.Spacing.SM),
                            api_key_row,
                            from_address_row,
                            ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
                            status_row,
                        ],
                        spacing=Theme.Spacing.SM,
                    ),
                    padding=Theme.Spacing.MD,
                ),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.expand = True

    def _build_edit_mode(self) -> None:
        """Build the edit mode content (form fields)."""
        # Reset form fields
        self._api_key_field.value = ""  # Don't pre-fill secrets
        self._from_email_field.value = self._metadata.get("resend_from_email") or ""

        # Action buttons
        action_buttons = FormActionButtons(
            on_save=self._save_config,
            on_cancel=self._cancel_edit,
            save_text="Save",
            saving=self._saving,
        )

        self.content = ft.Column(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            H3Text("Resend Configuration"),
                            ft.Container(height=Theme.Spacing.MD),
                            self._api_key_field,
                            ft.Container(height=Theme.Spacing.SM),
                            self._from_email_field,
                            ft.Container(height=Theme.Spacing.MD),
                            action_buttons,
                        ],
                        spacing=0,
                    ),
                    padding=Theme.Spacing.MD,
                ),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.expand = True

    async def _save_config(self) -> None:
        """Save the configuration to .env and reload settings."""
        # Validate fields
        api_key = self._api_key_field.value.strip()
        from_email = self._from_email_field.value.strip()

        # Track original values to detect deletions
        original_from_email = self._metadata.get("resend_from_email") or ""

        # Build updates dict
        updates: dict[str, str] = {}

        # Only update API key if provided (can't "clear" a secret via empty field)
        if api_key:
            updates["RESEND_API_KEY"] = api_key

        # Handle from_email: save if changed (including clearing it)
        if from_email != original_from_email:
            updates["RESEND_FROM_EMAIL"] = from_email  # May be empty to clear

        if not updates:
            # Nothing changed
            await self._cancel_edit()
            return

        # Write to .env
        self._env_service.write_env(updates)

        # Reload settings so changes take effect
        reload_settings()

        # Update local metadata to reflect changes
        if api_key:
            self._metadata["resend_api_key_configured"] = True
        if "RESEND_FROM_EMAIL" in updates:
            if from_email:
                self._metadata["resend_from_email"] = from_email
            else:
                # Cleared the field
                self._metadata["resend_from_email"] = None
                self._metadata["email_configured"] = False

        # Update email_configured status (requires both API key and from email)
        has_api_key = self._metadata.get("resend_api_key_configured", False)
        has_from_email = bool(self._metadata.get("resend_from_email"))
        self._metadata["email_configured"] = has_api_key and has_from_email

        # Exit edit mode
        self._edit_mode = False
        self._build_content()

        # Trigger refresh callback if provided
        if self._on_config_saved:
            self._on_config_saved()

        if self.page:
            self.update()
