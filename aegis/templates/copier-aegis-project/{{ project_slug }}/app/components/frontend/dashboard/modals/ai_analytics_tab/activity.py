"""The last few calls, newest first."""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    H3Text,
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
                    Tag(text=status_text, color=status_color),
                ]
            )

        # Build table
        table = DataTable(
            columns=columns,
            rows=rows,
            empty_message="No recent activity",
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
