"""Overview: what the cache is holding and how hard it is working."""

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
from app.components.frontend.dashboard.modals.redis_modal.constants import STAT_LABEL_WIDTH


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

