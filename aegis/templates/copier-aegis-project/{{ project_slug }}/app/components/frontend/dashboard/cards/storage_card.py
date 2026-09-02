"""Storage component card: where the bytes live and whether they answer."""

import flet as ft
from app.core.formatting import format_bytes
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)

STORAGE_COMPONENT_NAME = "storage"


class StorageCard:
    """Backend, bucket, and the object count when documents can supply it."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_metrics_section(self) -> ft.Container:
        metrics = [
            create_metric_container("Bucket", str(self.metadata.get("bucket") or "-")),
            create_metric_container("Endpoint", str(self.metadata.get("endpoint") or "-")),
        ]
        if "objects" in self.metadata:
            metrics.append(
                create_metric_container("Objects", str(self.metadata.get("objects", 0)))
            )
            metrics.append(
                create_metric_container(
                    "Stored", format_bytes(int(self.metadata.get("bytes") or 0))
                )
            )
        return ft.Container(content=ft.Row(metrics, expand=True), expand=True)

    def _create_card_content(self) -> ft.Container:
        subtitle = get_component_subtitle(STORAGE_COMPONENT_NAME, self.metadata)
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row("Storage", subtitle, self.component_data),
                    self._create_metrics_section(),
                ],
                spacing=0,
            ),
            padding=ft.padding.all(16),
            expand=True,
        )

    def build(self) -> ft.Container:
        """Build the storage card."""
        _, _, border_color = get_status_colors(self.component_data)
        return CardContainer(
            content=self._create_card_content(),
            component_name=STORAGE_COMPONENT_NAME,
            component_data=self.component_data,
            border_color=border_color,
        )
