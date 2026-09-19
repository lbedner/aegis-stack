"""Overview: traces, exceptions and latency at a glance."""

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
from app.components.frontend.dashboard.modals.observability_modal.spans import LatencyBarChart
from app.components.frontend.dashboard.modals.observability_modal.shared import _format_latency, STAT_LABEL_WIDTH




class OverviewSection(ft.Container):
    """Overview section showing key Logfire trace metrics."""

    def __init__(self, component_data: ComponentStatus) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = component_data.metadata or {}

        total_traces = metadata.get("total_traces", 0)
        total_spans = metadata.get("total_spans", 0)
        exceptions = metadata.get("exceptions", 0)
        avg_ms = metadata.get("avg_duration_ms", 0)
        max_ms = metadata.get("max_duration_ms", 0)

        exc_color = Theme.Colors.ERROR if exceptions > 0 else Theme.Colors.SUCCESS

        self.content = ft.Row(
            [
                MetricCard("Traces", str(total_traces), Theme.Colors.INFO),
                MetricCard("Spans", str(total_spans), Theme.Colors.INFO),
                MetricCard("Exceptions", str(exceptions), exc_color),
                MetricCard("Avg Latency", _format_latency(avg_ms), Theme.Colors.INFO),
                MetricCard(
                    "Max Latency", _format_latency(max_ms), Theme.Colors.WARNING
                ),
            ],
            spacing=Theme.Spacing.MD,
        )


class OverviewTab(ft.Container):
    """Overview tab combining metrics and slowest spans bar chart."""

    def __init__(self, component_data: ComponentStatus) -> None:
        super().__init__()
        metadata = component_data.metadata or {}
        spans = metadata.get("slowest_spans", [])

        self.content = ft.Column(
            [
                OverviewSection(component_data),
                ft.Container(
                    content=H3Text("Slowest Spans"),
                    padding=ft.padding.only(
                        left=Theme.Spacing.MD, top=Theme.Spacing.MD
                    ),
                ),
                LatencyBarChart(spans),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True

