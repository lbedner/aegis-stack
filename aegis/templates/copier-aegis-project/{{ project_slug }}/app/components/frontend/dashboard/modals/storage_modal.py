"""Storage component detail modal: the bucket as the app sees it.

Same shape as the other component modals: a row of metric cards for the
numbers that matter at a glance, then the connection details as labeled
rows. Nothing here talks to the store; it renders what the health check
already gathered.
"""

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_bytes
from app.services.system.models import ComponentStatus, ComponentStatusType
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard, StatRowsSection, status_dot


class OverviewSection(ft.Container):
    """Backend, bucket and how much it holds, at a glance."""

    def __init__(self, component_data: ComponentStatus) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD
        metadata = component_data.metadata or {}
        reachable = component_data.status == ComponentStatusType.HEALTHY
        cards: list[ft.Control] = [
            MetricCard(
                "Backend",
                str(metadata.get("backend") or "-"),
                Theme.Colors.INFO,
            ),
            MetricCard(
                "Bucket",
                str(metadata.get("bucket") or "-"),
                Theme.Colors.SUCCESS if reachable else Theme.Colors.ERROR,
            ),
        ]
        if "objects" in metadata:
            cards.append(
                MetricCard(
                    "Objects",
                    str(metadata.get("objects", 0)),
                    Theme.Colors.INFO,
                )
            )
            cards.append(
                MetricCard(
                    "Stored",
                    format_bytes(int(metadata.get("bytes") or 0)),
                    Theme.Colors.INFO,
                )
            )
        self.content = ft.Row(cards, spacing=Theme.Spacing.MD)


class StorageDetailDialog(BaseDetailPopup):
    """Where objects live and how the app reaches them."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        metadata = component_data.metadata or {}
        connection = StatRowsSection(
            "Connection",
            {
                "Endpoint": str(metadata.get("endpoint") or "AWS S3"),
                "Bucket": str(metadata.get("bucket") or "-"),
                "Region": str(metadata.get("region") or "-"),
                "Status": status_dot(
                    component_data.message,
                    Theme.Colors.ACCENT
                    if component_data.status == ComponentStatusType.HEALTHY
                    else Theme.Colors.ERROR,
                    str(metadata.get("endpoint") or ""),
                ),
            },
        )
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("storage"),
            subtitle_text=get_component_subtitle("storage", metadata),
            sections=[
                OverviewSection(component_data),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                connection,
            ],
            width=900,
            height=520,
            status_detail=get_status_detail(component_data),
        )
