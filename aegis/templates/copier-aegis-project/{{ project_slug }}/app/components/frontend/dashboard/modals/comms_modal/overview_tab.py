"""The Overview tab: which channels are wired, and what they can do."""

from typing import Any

import flet as ft
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import MetricCard


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
