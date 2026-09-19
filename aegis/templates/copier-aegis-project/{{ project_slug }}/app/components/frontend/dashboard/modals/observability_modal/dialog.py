"""The dialog that hangs the tabs together."""

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    DataTable,
    DataTableColumn,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.expandable_data_table import (
    ExpandableDataTable,
    ExpandableRow,
)
from app.components.frontend.controls.markdown import copyable_markdown
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from ..modal_sections import PIE_CHART_COLORS, EmptyStatePlaceholder, MetricCard
from app.components.frontend.dashboard.modals.observability_modal.configuration import ConfigTab, ConfigurationSection
from app.components.frontend.dashboard.modals.observability_modal.exceptions import ExceptionsTab
from app.components.frontend.dashboard.modals.observability_modal.overview import OverviewTab
from app.components.frontend.dashboard.modals.observability_modal.spans import SlowestSpansTab


class ObservabilityDetailDialog(BaseDetailPopup):
    """
    Logfire observability detail popup dialog.

    Displays comprehensive trace analytics with tabs for
    Overview (metrics + slowest spans + config) and Exceptions (24h).
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the observability details popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
            page: Flet page instance
        """
        metadata = component_data.metadata or {}
        query_available = metadata.get("query_api_available", False)
        version = metadata.get("logfire_version", "")
        subtitle = (
            f"Pydantic Logfire {version}".strip() if version else "Pydantic Logfire"
        )

        if not query_available:
            # No read token - single scrollable view with empty state + config
            sections: list[ft.Control] = [
                EmptyStatePlaceholder(
                    "Add LOGFIRE_READ_TOKEN to enable trace analytics"
                ),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ConfigurationSection(component_data, page),
            ]

            super().__init__(
                page=page,
                component_data=component_data,
                title_text=get_component_title("observability"),
                subtitle_text=subtitle,
                sections=sections,
                scrollable=True,
                width=1100,
                height=750,
                status_detail=get_status_detail(component_data),
            )
            return

        # Query API available - show tabs
        exceptions = metadata.get("recent_exceptions", [])
        exc_count = len(exceptions)
        exc_tab_label = f"Exceptions ({exc_count})" if exc_count > 0 else "Exceptions"

        spans = metadata.get("slowest_spans", [])
        spans_count = len(spans)
        spans_tab_label = (
            f"Slowest Spans ({spans_count})" if spans_count > 0 else "Slowest Spans"
        )

        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(
                    text="Overview",
                    content=OverviewTab(component_data),
                ),
                ft.Tab(
                    text=spans_tab_label,
                    content=SlowestSpansTab(component_data),
                ),
                ft.Tab(
                    text=exc_tab_label,
                    content=ExceptionsTab(component_data, page),
                ),
                ft.Tab(
                    text="Config",
                    content=ConfigTab(component_data, page),
                ),
            ],
            expand=True,
        )

        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("observability"),
            subtitle_text=subtitle,
            sections=[tabs],
            scrollable=False,
            width=1100,
            height=750,
            status_detail=get_status_detail(component_data),
        )

