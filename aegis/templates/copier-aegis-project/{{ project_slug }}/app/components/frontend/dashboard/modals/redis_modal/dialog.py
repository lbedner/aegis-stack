"""The dialog that hangs the tabs together."""

from datetime import datetime

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from ..modal_sections import MetricCard
from app.components.frontend.dashboard.modals.redis_modal.connections import ConnectionsTab
from app.components.frontend.dashboard.modals.redis_modal.overview import OverviewTab
from app.components.frontend.dashboard.modals.redis_modal.slow_queries import SlowQueriesTab


class RedisDetailDialog(BaseDetailPopup):
    """
    Redis cache detail popup dialog.

    Displays comprehensive Redis information including performance metrics,
    slow query log, active client connections, and infrastructure details.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the redis details popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
        """
        metadata = component_data.metadata or {}

        # Build tabs
        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Overview", content=OverviewTab(component_data, page)),
                ft.Tab(
                    text="Slow Queries", content=SlowQueriesTab(component_data, page)
                ),
                ft.Tab(
                    text="Connections", content=ConnectionsTab(component_data, page)
                ),
            ],
            expand=True,
        )

        # Initialize base popup with tabs
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("cache"),
            subtitle_text=get_component_subtitle("cache", metadata),
            sections=[tabs],
            scrollable=False,
            width=900,
            height=650,
            status_detail=get_status_detail(component_data),
        )

