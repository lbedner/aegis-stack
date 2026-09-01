"""Documents service card: how much paper the store holds."""

import flet as ft

from app.core.formatting import format_bytes
from app.services.documents.health import DOCUMENTS_MODAL_ID
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


class DocumentsCard:
    """Total, this month's arrivals, and bytes stored."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_metrics_section(self) -> ft.Container:
        total = int(self.metadata.get("total", 0) or 0)
        this_month = int(self.metadata.get("this_month", 0) or 0)
        stored = int(self.metadata.get("bytes", 0) or 0)
        return ft.Container(
            content=ft.Row(
                [
                    create_metric_container("Documents", str(total)),
                    create_metric_container("This month", str(this_month)),
                    create_metric_container("Stored", format_bytes(stored)),
                ],
                expand=True,
            ),
            expand=True,
        )

    def _create_card_content(self) -> ft.Container:
        subtitle = get_component_subtitle(DOCUMENTS_MODAL_ID, self.metadata)
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row("Documents", subtitle, self.component_data),
                    self._create_metrics_section(),
                ],
                spacing=0,
            ),
            padding=ft.padding.all(16),
            expand=True,
        )

    def build(self) -> ft.Container:
        """Build the documents card."""
        _, _, border_color = get_status_colors(self.component_data)
        return CardContainer(
            content=self._create_card_content(),
            component_name=DOCUMENTS_MODAL_ID,
            component_data=self.component_data,
            border_color=border_color,
        )
