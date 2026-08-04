"""
Redis Detail Modal

Displays comprehensive Redis cache information including performance metrics,
slow query log, active client connections, and infrastructure details.
Each section is a self-contained Flet control for reusability and testing.
"""

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

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard

# Slow query thresholds
SLOWLOG_CRITICAL_MS = 1000  # 1 second - Critical (red)
SLOWLOG_WARNING_MS = 100  # 100ms - Warning (yellow)

# Client connection table column widths (pixels)
COL_WIDTH_CLIENT_ID = 100
COL_WIDTH_ADDRESS = 150
COL_WIDTH_AGE = 80
COL_WIDTH_IDLE = 80
COL_WIDTH_DB = 60
COL_WIDTH_COMMAND = 200

# Slow query table column widths (pixels)
COL_WIDTH_TIMESTAMP = 180
COL_WIDTH_DURATION = 100
COL_WIDTH_SLOWLOG_CMD = 400

# Statistics section layout
STAT_LABEL_WIDTH = 200


class OverviewSection(ft.Container):
    """Overview section showing key Redis metrics."""

    def __init__(self, redis_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize overview section.

        Args:
            redis_component: Redis ComponentStatus with metadata
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = redis_component.metadata or {}

        total_keys = metadata.get("total_keys", 0)
        connected_clients = metadata.get("connected_clients", 0)
        hit_rate = metadata.get("hit_rate_percent", 0.0)

        # Format uptime
        uptime_seconds = metadata.get("uptime_in_seconds", 0)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        uptime_str = f"{days}d {hours}h {minutes}m"

        # Determine hit rate color
        if hit_rate >= 90:
            hit_rate_color = Theme.Colors.SUCCESS
        elif hit_rate >= 70:
            hit_rate_color = Theme.Colors.WARNING
        else:
            hit_rate_color = Theme.Colors.ERROR

        self.content = ft.Row(
            [
                MetricCard(
                    "Total Keys",
                    str(total_keys),
                    Theme.Colors.INFO,
                ),
                MetricCard(
                    "Connected Clients",
                    str(connected_clients),
                    Theme.Colors.SUCCESS,
                ),
                MetricCard(
                    "Cache Hit Rate",
                    f"{hit_rate:.1f}%",
                    hit_rate_color,
                ),
                MetricCard(
                    "Server Uptime",
                    uptime_str,
                    Theme.Colors.INFO,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )


class PerformanceSection(ft.Container):
    """Performance metrics section showing memory, ops, and cache stats."""

    def __init__(self, redis_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize performance section.

        Args:
            redis_component: Redis ComponentStatus with metadata
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = redis_component.metadata or {}
        response_time = redis_component.response_time_ms or 0

        # Memory metrics
        used_memory_human = metadata.get("used_memory_human", "0B")
        maxmemory_human = metadata.get("maxmemory_human", "0B")
        mem_fragmentation = metadata.get("mem_fragmentation_ratio", 1.0)

        # Performance metrics
        ops_per_sec = metadata.get("instantaneous_ops_per_sec", 0)
        keyspace_hits = metadata.get("keyspace_hits", 0)
        keyspace_misses = metadata.get("keyspace_misses", 0)
        evicted_keys = metadata.get("evicted_keys", 0)
        expired_keys = metadata.get("expired_keys", 0)

        def metric_row(label: str, value: str) -> ft.Row:
            """Create a performance metric row."""
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

        self.content = ft.Column(
            [
                H3Text("Performance Metrics"),
                ft.Container(height=Theme.Spacing.SM),
                metric_row("Response Time", f"{response_time}ms"),
                metric_row("Memory Usage", f"{used_memory_human} / {maxmemory_human}"),
                metric_row("Memory Fragmentation", f"{mem_fragmentation:.2f}"),
                metric_row("Operations/Sec", str(ops_per_sec)),
                ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
                metric_row("Cache Hits", str(keyspace_hits)),
                metric_row("Cache Misses", str(keyspace_misses)),
                metric_row("Evicted Keys", str(evicted_keys)),
                metric_row("Expired Keys", str(expired_keys)),
            ],
            spacing=Theme.Spacing.XS,
        )


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


class ClientConnectionRow(ft.Container):
    """Single client connection display row."""

    def __init__(self, client: dict) -> None:
        """
        Initialize client connection row.

        Args:
            client: Client info from CLIENT LIST
        """
        super().__init__()

        client_id = client.get("id", "")
        addr = client.get("addr", "")
        age = client.get("age", "0")
        idle = client.get("idle", "0")
        db = client.get("db", "0")
        cmd = client.get("cmd", "")

        self.content = ft.Row(
            [
                ft.Container(
                    content=BodyText(client_id, text_align=ft.TextAlign.CENTER),
                    width=COL_WIDTH_CLIENT_ID,
                ),
                ft.Container(
                    content=BodyText(addr),
                    width=COL_WIDTH_ADDRESS,
                ),
                ft.Container(
                    content=BodyText(age, text_align=ft.TextAlign.CENTER),
                    width=COL_WIDTH_AGE,
                ),
                ft.Container(
                    content=BodyText(idle, text_align=ft.TextAlign.CENTER),
                    width=COL_WIDTH_IDLE,
                ),
                ft.Container(
                    content=BodyText(db, text_align=ft.TextAlign.CENTER),
                    width=COL_WIDTH_DB,
                ),
                ft.Container(
                    content=BodyText(cmd),
                    width=COL_WIDTH_COMMAND,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.padding = ft.padding.symmetric(vertical=Theme.Spacing.XS)


class ActiveConnectionsSection(ft.Container):
    """Active client connections section."""

    def __init__(self, redis_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize active connections section.

        Args:
            redis_component: Redis ComponentStatus with active_clients
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = redis_component.metadata or {}
        active_clients = metadata.get("active_clients", [])

        # Column headers
        header_row = ft.Row(
            [
                ft.Container(
                    content=SecondaryText(
                        "Client ID",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_CLIENT_ID,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Address", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_ADDRESS,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Age (s)",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_AGE,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Idle (s)",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_IDLE,
                ),
                ft.Container(
                    content=SecondaryText(
                        "DB",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_DB,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Command", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_COMMAND,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

        # Client rows
        client_rows = [ClientConnectionRow(client) for client in active_clients]

        self.content = ft.Column(
            [
                H3Text("Active Connections"),
                ft.Container(height=Theme.Spacing.SM),
                header_row,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Column(
                    client_rows if client_rows else [BodyText("No active connections")],
                    spacing=0,
                ),
            ],
            spacing=0,
        )


# =============================================================================
# Tab Containers
# =============================================================================


class OverviewTab(ft.Container):
    """Overview tab combining metrics and performance."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.content = ft.Column(
            [
                OverviewSection(component_data, page),
                PerformanceSection(component_data, page),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
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


class ConnectionsTab(ft.Container):
    """Connections tab showing active client connections and connection info."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}

        # Connection info section
        redis_url = metadata.get("url", "Not configured")
        host = metadata.get("host", "localhost")
        port = metadata.get("port", 6379)
        connected_clients = metadata.get("connected_clients", 0)
        total_connections = metadata.get("total_connections_received", 0)
        blocked_clients = metadata.get("blocked_clients", 0)

        def info_row(label: str, value: str) -> ft.Row:
            """Create an info row."""
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

        connection_info = ft.Column(
            [
                H3Text("Connection Info"),
                ft.Container(height=Theme.Spacing.SM),
                info_row("Host", f"{host}:{port}"),
                info_row("URL", redis_url),
                ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
                info_row("Connected Clients", str(connected_clients)),
                info_row("Blocked Clients", str(blocked_clients)),
                info_row("Total Connections", str(total_connections)),
            ],
            spacing=Theme.Spacing.XS,
        )

        self.content = ft.Column(
            [
                ft.Container(content=connection_info, padding=Theme.Spacing.MD),
                ActiveConnectionsSection(component_data, page),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True


# =============================================================================
# Main Dialog
# =============================================================================


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
