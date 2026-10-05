"""A card that is a header and a row of counts, read from the component's
health metadata: the shape the Secrets and MCP cards share."""

import flet as ft

from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle

from .card_container import CardContainer
from .card_utils import create_header_row, create_metric_container, get_status_colors


def counts_card(
    component_data: ComponentStatus,
    name: str,
    title: str,
    counts: list[tuple[str, str]],
) -> ft.Container:
    """``name``'s card: ``title``, its subtitle, and ``counts`` as metrics."""
    subtitle = get_component_subtitle(name, component_data.metadata or {})
    metrics = ft.Row(
        [create_metric_container(label, value) for label, value in counts], expand=True
    )
    content = ft.Container(
        content=ft.Column(
            [
                create_header_row(title, subtitle, component_data),
                ft.Container(content=metrics, expand=True),
            ],
            spacing=0,
        ),
        padding=ft.padding.all(16),
        expand=True,
    )
    _, _, border_color = get_status_colors(component_data)
    return CardContainer(
        content=content,
        component_name=name,
        component_data=component_data,
        border_color=border_color,
    )
