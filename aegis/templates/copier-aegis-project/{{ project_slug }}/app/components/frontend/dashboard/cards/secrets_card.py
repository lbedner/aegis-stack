"""Secrets component card: how many needed keys are set, how many declared
keys are set, and how many of those are stored here rather than in
``.env``."""

from typing import Any

import flet as ft

from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle

from .card_container import CardContainer
from .card_utils import create_header_row, create_metric_container, get_status_colors

SECRETS_COMPONENT_NAME = "secrets"


def counts(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    """Needed keys first: unset optional providers are choices, not gaps."""
    return [
        ("Needed", f"{metadata.get('needed_set', 0)} / {metadata.get('needed', 0)}"),
        ("Set", f"{metadata.get('set', 0)} / {metadata.get('declared', 0)}"),
        ("Stored", str(metadata.get("stored", 0))),
    ]


class SecretsCard:
    """Needed, set and stored counts from the health check."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_card_content(self) -> ft.Container:
        metrics = ft.Row(
            [
                create_metric_container(label, value)
                for label, value in counts(self.metadata)
            ],
            expand=True,
        )
        subtitle = get_component_subtitle(SECRETS_COMPONENT_NAME, self.metadata)
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row("Secrets", subtitle, self.component_data),
                    ft.Container(content=metrics, expand=True),
                ],
                spacing=0,
            ),
            padding=ft.padding.all(16),
            expand=True,
        )

    def build(self) -> ft.Container:
        """Build the secrets card."""
        _, _, border_color = get_status_colors(self.component_data)
        return CardContainer(
            content=self._create_card_content(),
            component_name=SECRETS_COMPONENT_NAME,
            component_data=self.component_data,
            border_color=border_color,
        )
