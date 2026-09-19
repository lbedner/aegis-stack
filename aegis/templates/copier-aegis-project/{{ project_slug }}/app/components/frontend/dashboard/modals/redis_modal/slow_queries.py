"""Slow queries: the commands that took long enough to notice."""

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
from app.components.frontend.dashboard.modals.redis_modal.constants import COL_WIDTH_DURATION, COL_WIDTH_SLOWLOG_CMD, COL_WIDTH_TIMESTAMP, SLOWLOG_CRITICAL_MS, SLOWLOG_WARNING_MS


def _format_slow_command(command: str) -> tuple[str, str]:
    """Format a raw SLOWLOG command into a readable (summary, detail) pair.

    Returns:
        Tuple of (formatted command, tooltip detail).
    """
    parts = command.split()
    if not parts:
        return command, command

    cmd = parts[0].upper()

    # EVALSHA: show script context instead of raw hash + args
    if cmd == "EVALSHA" and len(parts) >= 4:
        # parts: EVALSHA <sha> <numkeys> <key1> ...
        keys = parts[3 : 3 + int(parts[2])] if parts[2].isdigit() else []
        key_str = " ".join(keys) if keys else "unknown"
        return f"EVALSHA (Lua) on {key_str}", command

    # For key-based commands, shorten UUIDs in keys for readability
    if len(parts) >= 2:
        formatted_parts = [cmd]
        for part in parts[1:]:
            # Shorten UUID segments (8-4-4-4-12 hex pattern)
            if len(part) > 24 and "-" in part:
                # Shorten embedded UUIDs but keep prefix
                segments = part.split(":")
                shortened = []
                for seg in segments:
                    if len(seg) == 36 and seg.count("-") == 4:
                        shortened.append(f"{seg[:8]}...")
                    else:
                        shortened.append(seg)
                formatted_parts.append(":".join(shortened))
            else:
                formatted_parts.append(part)
        return " ".join(formatted_parts), command

    return command, command


class SlowQueryRow(ft.Container):
    """Single slow query display row."""

    def __init__(self, entry: dict) -> None:
        """
        Initialize slow query row.

        Args:
            entry: Slow query entry from SLOWLOG
        """
        super().__init__()

        timestamp = entry.get("timestamp", 0)
        duration_ms = entry.get("duration_ms", 0)
        command = entry.get("command", "")

        # Format timestamp
        try:
            dt = datetime.fromtimestamp(timestamp)
            timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError, TypeError):
            timestamp_str = str(timestamp)

        # Color code by duration
        if duration_ms >= SLOWLOG_CRITICAL_MS:
            duration_color = Theme.Colors.ERROR
        elif duration_ms >= SLOWLOG_WARNING_MS:
            duration_color = Theme.Colors.WARNING
        else:
            duration_color = Theme.Colors.SUCCESS

        display_cmd, tooltip_cmd = _format_slow_command(command)

        self.content = ft.Row(
            [
                ft.Container(
                    content=BodyText(timestamp_str),
                    width=COL_WIDTH_TIMESTAMP,
                ),
                ft.Container(
                    content=SecondaryText(
                        f"{duration_ms:.2f}ms",
                        color=duration_color,
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                    ),
                    width=COL_WIDTH_DURATION,
                ),
                ft.Container(
                    content=ft.Text(
                        display_cmd,
                        size=Theme.Typography.BODY,
                        color=ft.Colors.ON_SURFACE,
                        font_family="monospace",
                        tooltip=tooltip_cmd,
                    ),
                    width=COL_WIDTH_SLOWLOG_CMD,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.padding = ft.padding.symmetric(vertical=Theme.Spacing.XS)


class SlowQueriesSection(ft.Container):
    """Slow queries log section displaying recent slow commands from Redis SLOWLOG."""

    def __init__(self, redis_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize slow queries section.

        Args:
            redis_component: Redis ComponentStatus with slowlog_entries
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = redis_component.metadata or {}
        slowlog_entries = metadata.get("slowlog_entries", [])

        # Sort by duration descending
        sorted_entries = sorted(
            slowlog_entries, key=lambda x: x.get("duration_ms", 0), reverse=True
        )

        # Column headers
        header_row = ft.Row(
            [
                ft.Container(
                    content=SecondaryText(
                        "Timestamp", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_TIMESTAMP,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Duration",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_DURATION,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Command", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_SLOWLOG_CMD,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

        # Query rows
        query_rows = [SlowQueryRow(entry) for entry in sorted_entries]

        if query_rows:
            self.content = ft.Column(
                [
                    header_row,
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    ft.Column(query_rows, spacing=0),
                ],
                spacing=0,
            )
        else:
            self.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(
                            ft.Icons.SPEED,
                            size=48,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        SecondaryText("No slow queries recorded"),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.SM,
                ),
                alignment=ft.alignment.center,
                expand=True,
            )
            self.expand = True


class SlowQueriesTab(ft.Container):
    """Slow queries tab."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        metadata = component_data.metadata or {}
        slowlog_entries = metadata.get("slowlog_entries", [])

        if slowlog_entries:
            self.content = ft.Column(
                [SlowQueriesSection(component_data, page)],
                scroll=ft.ScrollMode.AUTO,
            )
            self.padding = ft.padding.all(Theme.Spacing.SM)
        else:
            self.content = ft.Column(
                [
                    ft.Icon(
                        ft.Icons.SPEED,
                        size=48,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    SecondaryText("No slow queries recorded"),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
                expand=True,
            )
        self.expand = True

