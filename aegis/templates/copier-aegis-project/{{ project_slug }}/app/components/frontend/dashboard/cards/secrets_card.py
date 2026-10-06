"""Secrets component card: how many needed keys are set, how many declared
keys are set, and how many of those are stored here rather than in
``.env``."""

from typing import Any

import flet as ft

from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus

from .counts_card import counts_card


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

    def build(self) -> ft.Container:
        """Build the secrets card."""
        return counts_card(
            self.component_data,
            ComponentName.SECRETS,
            "Secrets",
            counts(self.component_data.metadata or {}),
        )
