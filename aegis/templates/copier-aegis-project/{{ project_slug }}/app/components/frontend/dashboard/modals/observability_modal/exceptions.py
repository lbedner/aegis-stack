"""Exceptions, grouped by fingerprint and expandable."""

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
from app.components.frontend.dashboard.modals.observability_modal.shared import _EXC_COLUMNS


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
        content.append(
            copyable_markdown(
                f"```python\n{stacktrace}\n```",
                copy_text=stacktrace,
                dark=is_dark_mode,
            )
        )

    if not content:
        content.append(SecondaryText("No additional details available"))

    return ft.Column(content, spacing=Theme.Spacing.XS)


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

