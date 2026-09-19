"""Slowest spans, and the bar chart that ranks them."""

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
from app.components.frontend.dashboard.modals.observability_modal.shared import OVERVIEW_BAR_CHART_LIMIT, _format_latency


class LatencyBarChart(ft.Container):
    """Horizontal bar chart showing the top N slowest spans by avg latency."""

    def __init__(
        self, spans: list[dict], limit: int = OVERVIEW_BAR_CHART_LIMIT
    ) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD

        display_spans = spans[:limit]

        if not display_spans:
            self.content = ft.Container(
                content=SecondaryText("No span data available"),
                alignment=ft.alignment.center,
                padding=Theme.Spacing.MD,
            )
            return

        max_ms = max(s.get("avg_ms", 0) for s in display_spans)
        if max_ms == 0:
            max_ms = 1  # Avoid division by zero

        bar_rows: list[ft.Control] = []
        for i, span in enumerate(display_spans):
            name = span.get("name", "unknown")
            avg_ms = span.get("avg_ms", 0)
            count = span.get("count", 0)
            color = PIE_CHART_COLORS[i % len(PIE_CHART_COLORS)]

            # Truncate span name for display
            short_name = name[:40] + "..." if len(name) > 40 else name

            # Bar width as fraction of max
            bar_fraction = avg_ms / max_ms if max_ms > 0 else 0

            bar_rows.append(
                ft.Column(
                    [
                        # Span name + latency label
                        ft.Row(
                            [
                                ft.Container(
                                    content=SecondaryText(
                                        short_name,
                                        tooltip=name if len(name) > 40 else None,
                                    ),
                                    expand=True,
                                ),
                                ft.Container(
                                    content=SecondaryText(
                                        f"{_format_latency(avg_ms)}  ({count}x)",
                                    ),
                                    width=160,
                                    alignment=ft.alignment.center_right,
                                ),
                            ],
                        ),
                        # The bar itself
                        ft.Container(
                            content=ft.Container(
                                bgcolor=color,
                                border_radius=3,
                                height=14,
                                width=bar_fraction * 600,
                            ),
                            height=14,
                        ),
                    ],
                    spacing=2,
                )
            )

        self.content = ft.Column(bar_rows, spacing=Theme.Spacing.SM)


class SlowestSpansSection(ft.Container):
    """Full table of all slowest spans for the dedicated tab."""

    def __init__(self, component_data: ComponentStatus) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = component_data.metadata or {}
        spans = metadata.get("slowest_spans", [])

        columns = [
            DataTableColumn("Span Name", style="primary"),
            DataTableColumn("Avg", width=90, alignment="right", style="body"),
            DataTableColumn("p95", width=90, alignment="right", style="body"),
            DataTableColumn("Max", width=90, alignment="right", style="body"),
            DataTableColumn("Count", width=60, alignment="right", style="body"),
            DataTableColumn("Errors", width=60, alignment="right", style=None),
            DataTableColumn("Total", width=90, alignment="right", style="body"),
        ]

        rows: list[list] = []
        for span in spans:
            name = span.get("name", "unknown")
            avg_ms = span.get("avg_ms", 0)
            p95_ms = span.get("p95_ms", 0)
            max_ms = span.get("max_ms", 0)
            count = span.get("count", 0)
            errors = span.get("errors", 0)
            total_ms = span.get("total_ms", 0)

            # Color errors red if > 0
            error_cell: str | ft.Text = str(errors)
            if errors > 0:
                error_cell = ft.Text(
                    str(errors),
                    color=Theme.Colors.ERROR,
                    weight=ft.FontWeight.W_600,
                    size=13,
                )

            rows.append(
                [
                    name,
                    _format_latency(avg_ms),
                    _format_latency(p95_ms),
                    _format_latency(max_ms),
                    str(count),
                    error_cell,
                    _format_latency(total_ms),
                ]
            )

        self.content = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            empty_message="No span data available",
        )


class SlowestSpansTab(ft.Container):
    """Full table of all slowest spans."""

    def __init__(self, component_data: ComponentStatus) -> None:
        super().__init__()
        self.content = ft.Column(
            [SlowestSpansSection(component_data)],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True

