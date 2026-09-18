"""The comms modal itself: three tabs, and what a save refreshes."""

from typing import Any

import flet as ft
from app.components.frontend.controls.tabs import PulseTabs
from app.services.system.models import ComponentStatus, ComponentStatusType
from app.services.system.ui import get_component_subtitle, get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from .email_tab import EmailTab
from .overview_tab import OverviewTab
from .twilio_tab import TwilioTab


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
