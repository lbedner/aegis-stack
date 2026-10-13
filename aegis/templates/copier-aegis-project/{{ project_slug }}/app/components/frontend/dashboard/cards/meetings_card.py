"""Meetings service card: how many meetings, and how many the bot is in."""

import flet as ft

from app.services.meetings.health import MEETINGS_MODAL_ID
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle

from .card_container import CardContainer
from .card_metadata import metadata_number
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


class MeetingsCard:
    """Every owner's meetings, and the calls the bot is in now."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_metrics_section(self) -> ft.Container:
        meetings = int(metadata_number(self.metadata, "meetings"))
        in_call = int(metadata_number(self.metadata, "in_call"))
        return ft.Container(
            content=ft.Row(
                [
                    create_metric_container("Meetings", str(meetings)),
                    create_metric_container("In a call", str(in_call)),
                ],
                expand=True,
            ),
            expand=True,
        )

    def _create_card_content(self) -> ft.Container:
        subtitle = get_component_subtitle(MEETINGS_MODAL_ID, self.metadata)
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row("Meetings", subtitle, self.component_data),
                    self._create_metrics_section(),
                ],
                spacing=0,
            ),
            padding=ft.padding.all(16),
            expand=True,
        )

    def build(self) -> ft.Container:
        """Build the meetings card."""
        _, _, border_color = get_status_colors(self.component_data)
        return CardContainer(
            content=self._create_card_content(),
            component_name=MEETINGS_MODAL_ID,
            component_data=self.component_data,
            border_color=border_color,
        )
