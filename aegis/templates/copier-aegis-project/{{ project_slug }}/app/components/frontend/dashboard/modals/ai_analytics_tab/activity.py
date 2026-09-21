"""The last few calls, newest first."""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    DataTable,
    DataTableColumn,
    H3Text,
    NumericText,
    SecondaryText,
    Tag,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_cost, format_number

from .shaping import _format_relative_time


class RecentActivitySection(ft.Container):
    """Recent activity section showing last N requests in a table."""

    def __init__(self, stats: dict[str, Any]) -> None:
        """
        Initialize recent activity section.

        Args:
            stats: Dictionary with recent activity data
        """
        super().__init__()

        recent = stats.get("recent", [])

        # Define columns with styling
        columns = [
            DataTableColumn("Time", width=120, style="secondary"),
            DataTableColumn("Model", width=140, style="primary"),
            DataTableColumn("Action", width=180, style="secondary"),
            DataTableColumn("Input", width=80, alignment="right", style="body"),
            DataTableColumn("Output", width=80, alignment="right", style="body"),
            DataTableColumn("Cost", width=90, alignment="right", style="body"),
            # Latency earns a column rather than a click: on a local
            # model the wall clock IS the story, and it was the one
            # number the dashboard could never show.
            DataTableColumn("Took", width=90, alignment="right", style="body"),
            DataTableColumn("Status", width=80, alignment="right", style=None),
        ]

        # Build row data - strings auto-styled, Tag passed through
        rows: list[list[Any]] = []
        for activity in recent:
            success = activity.get("success", True)
            status_text = "Success" if success else "Failed"
            status_color = Theme.Colors.SUCCESS if success else Theme.Colors.ERROR
            input_tokens = activity.get("input_tokens", 0)
            output_tokens = activity.get("output_tokens", 0)
            relative_time = _format_relative_time(activity.get("timestamp", ""))

            rows.append(
                [
                    relative_time,
                    activity.get("model", ""),
                    activity.get("action", ""),
                    format_number(input_tokens),
                    format_number(output_tokens),
                    format_cost(activity.get("cost", 0)),
                    _format_duration(activity.get("duration_ms")),
                    Tag(text=status_text, color=status_color),
                ]
            )

        # Build table
        table = DataTable(
            columns=columns,
            rows=rows,
            empty_message="No recent activity",
            expandable_content=lambda index: _detail(recent[index]),
        )

        self.content = ft.Column(
            [
                H3Text("Recent Activity"),
                ft.Container(height=Theme.Spacing.SM),
                table,
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD


# A value the ledger never recorded reads as a dash. Never 0, which
# would claim a measurement nobody took.
DASH = "-"


def _format_duration(ms: float | None) -> str:
    """``840 ms`` / ``2.4 s`` / ``-`` when it was never timed."""
    if ms is None:
        return DASH
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def _detail(activity: dict[str, Any]) -> ft.Control:
    """The drawer under one row: what the collapsed table has no room for.

    Everything here is nullable in the ledger, so every line is written
    to survive a None - historical rows predate these columns entirely
    and must still render.
    """

    def line(label: str, value: Any) -> ft.Control:
        return ft.Row(
            [
                ft.Container(content=SecondaryText(label), width=150),
                NumericText(str(value)) if value != DASH else SecondaryText(DASH),
            ],
            spacing=Theme.Spacing.SM,
        )

    cache_read = activity.get("cache_read_tokens")
    cache_write = activity.get("cache_write_tokens")
    tool_calls = activity.get("tool_calls")

    rows: list[ft.Control] = [
        line("Duration", _format_duration(activity.get("duration_ms"))),
        line(
            "Cache read",
            format_number(cache_read) if cache_read is not None else DASH,
        ),
        line(
            "Cache write",
            format_number(cache_write) if cache_write is not None else DASH,
        ),
        line("Tool calls", tool_calls if tool_calls is not None else DASH),
        line("Timestamp", activity.get("timestamp") or DASH),
    ]
    if activity.get("user_id"):
        rows.append(line("User", activity["user_id"]))
    if activity.get("error_message"):
        rows.append(
            ft.Row(
                [
                    ft.Container(content=SecondaryText("Error"), width=150),
                    BodyText(activity["error_message"], color=Theme.Colors.ERROR),
                ],
                spacing=Theme.Spacing.SM,
            )
        )

    return ft.Container(
        content=ft.Column(rows, spacing=Theme.Spacing.XS),
        padding=ft.padding.symmetric(
            vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
        ),
    )
