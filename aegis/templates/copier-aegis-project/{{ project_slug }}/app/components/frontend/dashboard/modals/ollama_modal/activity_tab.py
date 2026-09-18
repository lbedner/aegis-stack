"""The Activity tab: what the server has been asked to do lately.

Reads the activity log rather than the health check, so it is the one
tab whose contents change without the poll. The labels and colours are
here because nothing else names these event types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import flet as ft
from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.data_table import (
    DataTable,
)
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.theme import AegisTheme as Theme
from app.services.ai.domains.llm.ollama_activity import get_ollama_activity

from ...activity_feed import format_relative_time
from .columns import ACTIVITY_COLUMNS

ACTIVITY_EVENT_LABELS = {
    "loaded": "Loaded",
    "unloaded": "Unloaded",
    "evicted": "Evicted",
}


ACTIVITY_EVENT_COLORS = {
    "loaded": Theme.Colors.SUCCESS,
    "unloaded": Theme.Colors.WARNING,
    "evicted": Theme.Colors.TEXT_SECONDARY,
}


class ActivitySection(ft.Container):
    """Recent model activity as a table, newest first.

    Reads the process-wide tracker directly (the dashboard runs in the
    same process as the API), so no round trip and no persistence: the
    log is ephemeral by design.
    """

    def __init__(self) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD
        # (control, timestamp) pairs so relative times can be re-rendered
        # in place on each poll tick without rebuilding the table.
        self._time_cells: list[tuple[SecondaryText, datetime]] = []

        events = get_ollama_activity().events()
        if not events:
            self.content = ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(
                                    ft.Icons.HISTORY,
                                    size=48,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                                SecondaryText("No model activity yet"),
                                SecondaryText(
                                    "Loads, unloads, and evictions appear "
                                    "here as they happen",
                                    size=Theme.Typography.CAPTION,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=Theme.Spacing.SM,
                        ),
                        alignment=ft.alignment.center,
                        expand=True,
                        padding=Theme.Spacing.LG,
                    ),
                ],
                spacing=0,
            )
            return

        rows: list[list[Any]] = []
        for event in events:
            when_text = SecondaryText(format_relative_time(event.timestamp))
            self._time_cells.append((when_text, event.timestamp))
            vram_display = f"{event.vram_gb:.1f}G" if event.vram_gb else "—"
            rows.append(
                [
                    TableNameText(event.model),
                    Tag(
                        ACTIVITY_EVENT_LABELS[event.action],
                        color=ACTIVITY_EVENT_COLORS[event.action],
                    ),
                    NumericText(vram_display, color=Theme.Colors.TEXT_SECONDARY),
                    SecondaryText("Ollama" if event.detected else "App"),
                    when_text,
                ]
            )

        self.content = ft.Column(
            [
                DataTable(
                    columns=ACTIVITY_COLUMNS,
                    rows=rows,
                    row_padding=6,
                    show_header_border=True,
                    show_row_borders=True,
                ),
            ],
            spacing=0,
        )

    def refresh_times(self) -> None:
        """Re-render the relative timestamps so they age while the modal is open."""
        for text, timestamp in self._time_cells:
            text.value = format_relative_time(timestamp)


class ActivityTab(ft.Container):
    """Activity tab showing recent model loads, unloads, and evictions."""

    def __init__(self) -> None:
        super().__init__()
        self.section = ActivitySection()
        self.content = ft.Column(
            [self.section],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True
