"""The Settings tab: which provider is wired, and in which mode."""

import flet as ft
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import StatRowsSection


class SettingsTab(ft.Container):
    """Provider configuration and health details."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}

        provider = metadata.get("provider_display_name", "Unknown")
        is_test = metadata.get("is_test_mode", True)
        healthy = metadata.get("healthy", False)
        api_version = metadata.get("api_version") or "Unknown"
        health_msg = metadata.get("health_message", "") or ""
        # ProviderHealth.is_test_mode defaults to True, so when a
        # provider isn't configured (e.g. STRIPE_SECRET_KEY unset →
        # health_check returns early without populating is_test_mode)
        # the modal would render "Test Mode" alongside the "not
        # configured" detail line, which reads as "half working"
        # instead of "nothing wired up." Detect the unconfigured combo
        # from the health message and surface "Not Configured" instead.
        # The proper fix is making is_test_mode tri-state on the schema,
        # but this UI-side guard is the minimal correct read.
        if not healthy and "not configured" in health_msg.lower():
            mode_text = "Not Configured"
        else:
            mode_text = "Test Mode" if is_test else "Live Mode"
        status_text = "Connected" if healthy else "Disconnected"

        provider_stats: dict[str, str] = {
            "Provider": provider,
            "Mode": mode_text,
            "Status": status_text,
            "API Version": str(api_version),
        }
        if health_msg and not healthy:
            provider_stats["Details"] = health_msg

        self.content = ft.Column(
            [
                StatRowsSection(title="Provider Configuration", stats=provider_stats),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
