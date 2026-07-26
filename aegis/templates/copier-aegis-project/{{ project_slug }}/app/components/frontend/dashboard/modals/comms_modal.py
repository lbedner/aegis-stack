"""
Communications Service Detail Modal

Displays comprehensive comms service information including provider configuration,
channel status, and message capabilities in a tabbed interface.
Supports edit mode for configuration updates in development mode.
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
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import reload_settings
from app.services.system.env_config import EnvConfigService
from app.services.system.models import ComponentStatus, ComponentStatusType
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard


class OverviewSection(ft.Container):
    """Overview section showing key comms service metrics."""

    def __init__(self, metadata: dict[str, Any]) -> None:
        """
        Initialize overview section.

        Args:
            metadata: Component metadata containing comms statistics
        """
        super().__init__()

        channels_configured = metadata.get("channels_configured", 0)
        channels_total = metadata.get("channels_total", 3)
        capabilities = metadata.get("capabilities", [])

        # Determine overall status color
        if channels_configured == channels_total:
            status_color = Theme.Colors.SUCCESS
            status_text = "Fully Configured"
        elif channels_configured > 0:
            status_color = Theme.Colors.WARNING
            status_text = "Partially Configured"
        else:
            status_color = Theme.Colors.ERROR
            status_text = "Not Configured"

        self.content = ft.Row(
            [
                MetricCard(
                    "Channels",
                    f"{channels_configured}/{channels_total}",
                    status_color,
                ),
                MetricCard(
                    "Status",
                    status_text,
                    status_color,
                ),
                MetricCard(
                    "Capabilities",
                    ", ".join(capabilities) if capabilities else "None",
                    Theme.Colors.PRIMARY,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )
        self.padding = Theme.Spacing.MD


class OverviewTab(ft.Container):
    """Overview tab showing key metrics."""

    def __init__(self, component_data: ComponentStatus) -> None:
        """
        Initialize overview tab.

        Args:
            component_data: ComponentStatus containing component health and metrics
        """
        super().__init__()

        metadata = component_data.metadata or {}

        self.content = ft.Column(
            [OverviewSection(metadata)],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.expand = True


class EmailTab(ft.Container):
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
        super().__init__()

        self._metadata = metadata
        self._on_config_saved = on_config_saved
        self._edit_mode = False
        self._saving = False
        self._env_service = EnvConfigService()

        # Check if editing is allowed (dev mode only)
        self._can_edit = self._env_service.is_dev_mode()

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

    def _build_content(self) -> None:
        """Build the tab content based on current mode."""
        if self._edit_mode:
            self._build_edit_mode()
        else:
            self._build_view_mode()

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

    def _toggle_edit_mode(self, e: ft.ControlEvent | None = None) -> None:
        """Toggle between view and edit modes."""
        self._edit_mode = not self._edit_mode
        self._build_content()
        if self.page:
            self.update()

    async def _cancel_edit(self) -> None:
        """Cancel edit mode and return to view mode."""
        self._edit_mode = False
        self._build_content()
        if self.page:
            self.update()

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


class TwilioTab(ft.Container):
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
        super().__init__()

        self._metadata = metadata
        self._on_config_saved = on_config_saved
        self._edit_mode = False
        self._saving = False
        self._env_service = EnvConfigService()

        # Check if editing is allowed (dev mode only)
        self._can_edit = self._env_service.is_dev_mode()

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

    def _build_content(self) -> None:
        """Build the tab content based on current mode."""
        if self._edit_mode:
            self._build_edit_mode()
        else:
            self._build_view_mode()

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

    def _toggle_edit_mode(self, e: ft.ControlEvent | None = None) -> None:
        """Toggle between view and edit modes."""
        self._edit_mode = not self._edit_mode
        self._build_content()
        if self.page:
            self.update()

    async def _cancel_edit(self) -> None:
        """Cancel edit mode and return to view mode."""
        self._edit_mode = False
        self._build_content()
        if self.page:
            self.update()

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


class CommsDetailDialog(BaseDetailPopup):
    """
    Communications service detail popup dialog with tabbed interface.

    Displays comprehensive comms service information including provider
    configuration, channel status, and message capabilities.
    Supports configuration editing in development mode.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the comms service details popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
            page: Flet page instance
        """
        self._component_data = component_data
        self._page = page
        metadata: dict[str, Any] = component_data.metadata or {}

        # Build tabs list with config save callbacks
        tabs_list = [
            ft.Tab(text="Overview", content=OverviewTab(component_data)),
            ft.Tab(
                text="Email",
                content=EmailTab(metadata, on_config_saved=self._on_config_saved),
            ),
            ft.Tab(
                text="SMS/Voice",
                content=TwilioTab(metadata, on_config_saved=self._on_config_saved),
            ),
        ]

        # Create tabbed interface
        tabs = PulseTabs(
            selected_index=0,
            tabs=tabs_list,
            expand=True,
        )

        # Initialize base popup with tabs
        # (non-scrollable - tabs handle their own scrolling)
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_comms"),
            subtitle_text=get_component_subtitle("service_comms", metadata),
            sections=[tabs],
            scrollable=False,
            status_detail=get_status_detail(component_data),
        )

    def _on_config_saved(self) -> None:
        """
        Handle configuration save events.

        This is called when either EmailTab or TwilioTab saves config.
        Updates the modal status immediately and triggers dashboard refresh.
        """
        # Recalculate channels configured from metadata
        metadata = self._component_data.metadata or {}
        channels_configured = sum(
            [
                1 if metadata.get("email_configured") else 0,
                1 if metadata.get("sms_configured") else 0,
                1 if metadata.get("voice_configured") else 0,
            ]
        )
        channels_total = metadata.get("channels_total", 3)

        # Update metadata with new count
        metadata["channels_configured"] = channels_configured

        # Determine new status based on configuration
        if channels_configured == channels_total:
            new_status = ComponentStatusType.HEALTHY
            status_detail = None
        elif channels_configured > 0:
            new_status = ComponentStatusType.WARNING
            status_detail = f"{channels_configured}/{channels_total} channels"
        else:
            new_status = ComponentStatusType.UNHEALTHY
            status_detail = "No channels configured"

        # Update the modal's status tag
        self.update_status(new_status, status_detail)

        if self._page:
            from ..cards.card_utils import trigger_dashboard_refresh

            # Update the modal UI
            self.update()

            # Trigger dashboard refresh for the cards
            self._page.run_task(trigger_dashboard_refresh, self._page)
