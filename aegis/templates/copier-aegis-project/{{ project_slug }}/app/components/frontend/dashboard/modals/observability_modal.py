"""
Observability Detail Modal

Displays comprehensive Logfire trace analytics including
overview metrics, slowest spans, recent exceptions, and configuration.
"""

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
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import PIE_CHART_COLORS, EmptyStatePlaceholder, MetricCard

# Number of spans to show in the overview bar chart
OVERVIEW_BAR_CHART_LIMIT = 10

# Statistics section layout
STAT_LABEL_WIDTH = 150


def _format_latency(ms: float) -> str:
    """Format latency value for display."""
    if ms == 0:
        return "0 ms"
    if ms < 1:
        return f"{ms:.2f} ms"
    if ms < 1000:
        return f"{ms:.1f} ms"
    return f"{ms / 1000:.2f} s"


# ``_format_timestamp`` was replaced with the shared
# ``app.core.formatting.format_relative_time`` helper so the same
# relative-time formatting backs this modal, the Load Tests tab, and any
# future displays.


# =============================================================================
# Sections
# =============================================================================


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


def _build_exception_expanded_content(exc: dict, is_dark_mode: bool) -> ft.Control:
    """Build expanded content for an exception row.

    Shows exception type, full message, and stacktrace.

    Args:
        exc: Exception dict from Logfire query
        is_dark_mode: Whether the page is in dark mode

    Returns:
        Column with exception details
    """
    span_name = exc.get("span_name", "")
    exc_type = exc.get("exception_type", "")
    exc_message = exc.get("exception_message", "")
    full_message = exc.get("message", "")
    stacktrace = exc.get("stacktrace", "")
    trace_id = exc.get("trace_id", "")
    service = exc.get("service_name", "")

    content: list[ft.Control] = []

    # Span name (the operation/URL that failed)
    if span_name:
        content.append(
            ft.Row(
                [
                    SecondaryText("Span:", weight=Theme.Typography.WEIGHT_SEMIBOLD),
                    BodyText(span_name),
                ],
                spacing=Theme.Spacing.SM,
            )
        )

    # Exception type
    if exc_type:
        content.append(
            ft.Row(
                [
                    SecondaryText("Type:", weight=Theme.Typography.WEIGHT_SEMIBOLD),
                    BodyText(exc_type),
                ],
                spacing=Theme.Spacing.SM,
            )
        )

    # Full span message (has host/URL context), fall back to exception_message
    display_message = full_message or exc_message
    if display_message:
        content.append(
            ft.Row(
                [
                    SecondaryText("Message:", weight=Theme.Typography.WEIGHT_SEMIBOLD),
                    BodyText(display_message),
                ],
                spacing=Theme.Spacing.SM,
            )
        )

    # Trace ID and service
    if trace_id:
        content.append(
            ft.Row(
                [
                    SecondaryText("Trace ID:", weight=Theme.Typography.WEIGHT_SEMIBOLD),
                    SecondaryText(trace_id),
                ],
                spacing=Theme.Spacing.SM,
            )
        )

    if service:
        content.append(
            ft.Row(
                [
                    SecondaryText("Service:", weight=Theme.Typography.WEIGHT_SEMIBOLD),
                    SecondaryText(service),
                ],
                spacing=Theme.Spacing.SM,
            )
        )

    # Stacktrace in a markdown code block
    if stacktrace:
        content.append(ft.Container(height=Theme.Spacing.SM))
        content.append(
            SecondaryText("Stacktrace:", weight=Theme.Typography.WEIGHT_SEMIBOLD)
        )
        code_style = ft.TextStyle(
            size=12,
            font_family="Roboto Mono",
            weight=ft.FontWeight.W_400,
            height=1.2,
        )
        codeblock_decoration = ft.BoxDecoration(
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=ft.border_radius.all(8),
        )
        code_theme = "ir-black" if is_dark_mode else "atom-one-light"
        content.append(
            ft.Markdown(
                f"```python\n{stacktrace}\n```",
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                code_theme=code_theme,
                md_style_sheet=ft.MarkdownStyleSheet(
                    code_text_style=code_style,
                    codeblock_decoration=codeblock_decoration,
                ),
            )
        )

    if not content:
        content.append(SecondaryText("No additional details available"))

    return ft.Column(content, spacing=Theme.Spacing.XS)


# Exceptions table columns
_EXC_COLUMNS = [
    DataTableColumn("Exception", style="primary"),
    DataTableColumn("Message", style="body"),
    DataTableColumn("Count", width=80, style="secondary"),
    DataTableColumn("Latest", width=150, style="secondary"),
]


def _group_exceptions(exceptions: list[dict]) -> list[dict]:
    """Group exceptions by (exception_type, span_name).

    Returns the most recent exception per group with an added 'count' field.
    Input is assumed sorted by timestamp descending (most recent first).
    """
    groups: dict[tuple[str, str], dict] = {}
    counts: dict[tuple[str, str], int] = {}

    for exc in exceptions:
        key = (exc.get("exception_type", ""), exc.get("span_name", ""))
        counts[key] = counts.get(key, 0) + 1
        if key not in groups:
            # Keep the most recent (first seen since input is desc)
            groups[key] = exc

    result = []
    for key, exc in groups.items():
        grouped = dict(exc)
        grouped["count"] = counts[key]
        result.append(grouped)

    return result


class ExceptionsSection(ft.Container):
    """Expandable table displaying exceptions from the last 24 hours, grouped."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = component_data.metadata or {}
        exceptions = metadata.get("recent_exceptions", [])
        is_dark_mode = page.theme_mode == ft.ThemeMode.DARK

        grouped = _group_exceptions(exceptions)

        rows: list[ExpandableRow] = []
        for exc in grouped:
            exc_type = exc.get("exception_type", "")
            span_name = exc.get("span_name", "unknown")
            message = exc.get("exception_message") or exc.get("message", "")
            timestamp = format_relative_time(exc.get("timestamp", ""))
            count = exc.get("count", 1)

            # Show exception type if available, otherwise span name
            display_name = exc_type if exc_type else span_name

            # Truncate message for cell display
            short_msg = message[:60] + "..." if len(message) > 60 else message

            rows.append(
                ExpandableRow(
                    cells=[display_name, short_msg, str(count), timestamp],
                    expanded_content=_build_exception_expanded_content(
                        exc, is_dark_mode
                    ),
                )
            )

        self.content = ExpandableDataTable(
            columns=_EXC_COLUMNS,
            rows=rows,
            empty_message="No exceptions in the last 24 hours",
        )


class ConfigurationSection(ft.Container):
    """Configuration section showing observability connection info."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = component_data.metadata or {}

        service_name = metadata.get("service_name", "unknown")
        send_to_logfire = metadata.get("send_to_logfire", False)
        cloud_status = "Active" if send_to_logfire else "Local only"
        query_api = (
            "Available" if metadata.get("query_api_available") else "Not configured"
        )
        project_url = metadata.get("project_url") or ""

        def _make_row(label: str, value: str) -> ft.Row:
            return ft.Row(
                [
                    SecondaryText(
                        f"{label}:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=STAT_LABEL_WIDTH,
                    ),
                    BodyText(value),
                ],
                spacing=Theme.Spacing.MD,
            )

        rows: list[ft.Control] = [
            _make_row("Service Name", service_name),
            _make_row("Cloud Status", cloud_status),
            _make_row("Query API", query_api),
        ]

        # Project URL row - clickable link if configured
        if project_url:
            url = project_url

            def _open_url(e: ft.ControlEvent, target_url: str = url) -> None:
                if e.page:
                    e.page.launch_url(target_url)

            link_text = ft.Text(
                project_url,
                size=Theme.Typography.BODY,
                color=Theme.Colors.INFO,
            )

            rows.append(
                ft.Row(
                    [
                        SecondaryText(
                            "Project URL:",
                            weight=Theme.Typography.WEIGHT_SEMIBOLD,
                            width=STAT_LABEL_WIDTH,
                        ),
                        ft.GestureDetector(
                            content=link_text,
                            on_tap=_open_url,
                            mouse_cursor=ft.MouseCursor.CLICK,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                )
            )
        else:
            rows.append(_make_row("Project URL", "Not configured"))

        self.content = ft.Column(rows, spacing=Theme.Spacing.SM)


# =============================================================================
# Tab Containers
# =============================================================================


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


class ExceptionsTab(ft.Container):
    """Exceptions tab showing exceptions from the last 24 hours."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.content = ft.Column(
            [ExceptionsSection(component_data, page)],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True


class ConfigTab(ft.Container):
    """Configuration tab showing observability connection info."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.content = ft.Column(
            [ConfigurationSection(component_data, page)],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True


# =============================================================================
# Main Dialog
# =============================================================================


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
