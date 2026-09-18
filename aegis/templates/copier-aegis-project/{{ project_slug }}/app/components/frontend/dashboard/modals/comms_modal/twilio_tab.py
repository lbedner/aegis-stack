"""The SMS/Voice tab: what Twilio is configured with, and editing it.

Twilio needs four values where email needs two, and the messaging
service SID is optional, which is why this tab is the longer of the
two despite sharing its edit-mode contract with the other.
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


class TwilioTab(EditableConfigTab):
    """SMS/Voice (Twilio) configuration tab with edit mode support."""

    def __init__(
        self,
        metadata: dict[str, Any],
        on_config_saved: Callable[[], Any] | None = None,
    ) -> None:
        """
        Initialize SMS/Voice tab.

        Args:
            metadata: Component metadata containing Twilio configuration
            on_config_saved: Callback when configuration is saved (for refresh)
        """
        super().__init__(metadata, on_config_saved)

        # Initialize form fields
        self._account_sid_field = FormSecretField(
            label="Account SID",
            value="",
            hint="AC...",
        )
        self._auth_token_field = FormSecretField(
            label="Auth Token",
            value="",
            hint="Your Twilio auth token",
        )
        self._phone_number_field = FormTextField(
            label="Phone Number",
            value=metadata.get("twilio_phone_number") or "",
            hint="+15551234567",
        )
        self._messaging_sid_field = FormTextField(
            label="Messaging Service SID",
            value="",
            hint="MG... (optional)",
        )

        # Build initial view
        self._build_content()

    def _build_view_mode(self) -> None:
        """Build the view mode content (read-only display)."""
        sms_configured = self._metadata.get("sms_configured", False)
        voice_configured = self._metadata.get("voice_configured", False)
        twilio_sid_configured = self._metadata.get(
            "twilio_account_sid_configured", False
        )
        twilio_sid_preview = self._metadata.get(
            "twilio_account_sid_preview", "Not configured"
        )
        twilio_auth_configured = self._metadata.get(
            "twilio_auth_token_configured", False
        )
        twilio_phone = self._metadata.get("twilio_phone_number", "Not configured")
        twilio_messaging = self._metadata.get(
            "twilio_messaging_service_configured", False
        )

        # Header with edit button (dev mode only)
        header_controls: list[ft.Control] = [H3Text("Twilio Configuration")]
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

        # Account SID row (masked)
        if twilio_sid_configured:
            sid_content: ft.Control = BodyText(twilio_sid_preview)
        else:
            sid_content = SecondaryText("—")

        account_sid_row = ft.Row(
            [
                SecondaryText(
                    "Account SID:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                sid_content,
            ],
            spacing=Theme.Spacing.MD,
        )

        # Auth Token row
        if twilio_auth_configured:
            auth_content: ft.Control = Tag(
                text="Configured", color=Theme.Colors.SUCCESS
            )
        else:
            auth_content = SecondaryText("—")

        auth_token_row = ft.Row(
            [
                SecondaryText(
                    "Auth Token:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                auth_content,
            ],
            spacing=Theme.Spacing.MD,
        )

        # Phone Number row
        if twilio_phone and twilio_phone != "Not configured":
            phone_content: ft.Control = BodyText(twilio_phone)
        else:
            phone_content = SecondaryText("—")

        phone_number_row = ft.Row(
            [
                SecondaryText(
                    "Phone Number:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                phone_content,
            ],
            spacing=Theme.Spacing.MD,
        )

        # Messaging Service row
        if twilio_messaging:
            messaging_content: ft.Control = Tag(
                text="Configured", color=Theme.Colors.SUCCESS
            )
        else:
            messaging_content = SecondaryText("—")

        messaging_service_row = ft.Row(
            [
                SecondaryText(
                    "Messaging Service:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                messaging_content,
            ],
            spacing=Theme.Spacing.MD,
        )

        # Capabilities rows
        if sms_configured:
            sms_content: ft.Control = Tag(text="Ready", color=Theme.Colors.SUCCESS)
        else:
            sms_content = SecondaryText("—")

        sms_row = ft.Row(
            [
                SecondaryText(
                    "SMS:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                sms_content,
            ],
            spacing=Theme.Spacing.MD,
        )

        if voice_configured:
            voice_content: ft.Control = Tag(text="Ready", color=Theme.Colors.SUCCESS)
        else:
            voice_content = SecondaryText("—")

        voice_row = ft.Row(
            [
                SecondaryText(
                    "Voice:",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    width=200,
                ),
                voice_content,
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
                            account_sid_row,
                            auth_token_row,
                            phone_number_row,
                            messaging_service_row,
                            ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
                            H3Text("Capabilities"),
                            ft.Container(height=Theme.Spacing.SM),
                            sms_row,
                            voice_row,
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
        # Reset form fields - don't pre-fill secrets
        self._account_sid_field.value = ""
        self._auth_token_field.value = ""
        self._phone_number_field.value = self._metadata.get("twilio_phone_number") or ""
        self._messaging_sid_field.value = ""

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
                            H3Text("Twilio Configuration"),
                            ft.Container(height=Theme.Spacing.MD),
                            self._account_sid_field,
                            ft.Container(height=Theme.Spacing.SM),
                            self._auth_token_field,
                            ft.Container(height=Theme.Spacing.SM),
                            self._phone_number_field,
                            ft.Container(height=Theme.Spacing.SM),
                            self._messaging_sid_field,
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
        # Get field values
        account_sid = self._account_sid_field.value.strip()
        auth_token = self._auth_token_field.value.strip()
        phone_number = self._phone_number_field.value.strip()
        messaging_sid = self._messaging_sid_field.value.strip()

        # Track original values to detect deletions
        original_phone = self._metadata.get("twilio_phone_number") or ""

        # Build updates dict
        updates: dict[str, str] = {}

        # Only update secrets if provided (can't "clear" via empty field)
        if account_sid:
            updates["TWILIO_ACCOUNT_SID"] = account_sid
        if auth_token:
            updates["TWILIO_AUTH_TOKEN"] = auth_token
        if messaging_sid:
            updates["TWILIO_MESSAGING_SERVICE_SID"] = messaging_sid

        # Handle phone_number: save if changed (including clearing it)
        if phone_number != original_phone:
            updates["TWILIO_PHONE_NUMBER"] = phone_number  # May be empty to clear

        if not updates:
            # Nothing changed
            await self._cancel_edit()
            return

        # Write to .env
        self._env_service.write_env(updates)

        # Reload settings so changes take effect
        reload_settings()

        # Update local metadata to reflect changes
        if account_sid:
            self._metadata["twilio_account_sid_configured"] = True
            # Create masked preview (show first 4 chars, mask the rest)
            self._metadata["twilio_account_sid_preview"] = (
                f"{account_sid[:4]}...{account_sid[-4:]}"
                if len(account_sid) > 8
                else account_sid
            )
        if auth_token:
            self._metadata["twilio_auth_token_configured"] = True
        if "TWILIO_PHONE_NUMBER" in updates:
            if phone_number:
                self._metadata["twilio_phone_number"] = phone_number
            else:
                # Cleared the field
                self._metadata["twilio_phone_number"] = None
        if messaging_sid:
            self._metadata["twilio_messaging_service_configured"] = True

        # Update SMS/Voice configured status (requires SID, auth token, and phone)
        has_sid = self._metadata.get("twilio_account_sid_configured", False)
        has_auth = self._metadata.get("twilio_auth_token_configured", False)
        has_phone = bool(self._metadata.get("twilio_phone_number"))
        twilio_ready = has_sid and has_auth and has_phone
        self._metadata["sms_configured"] = twilio_ready
        self._metadata["voice_configured"] = twilio_ready

        # Exit edit mode
        self._edit_mode = False
        self._build_content()

        # Trigger refresh callback if provided
        if self._on_config_saved:
            self._on_config_saved()

        if self.page:
            self.update()
