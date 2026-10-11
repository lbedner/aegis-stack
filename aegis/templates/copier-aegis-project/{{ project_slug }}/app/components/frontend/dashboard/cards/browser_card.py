"""Browser component card: where the Playwright server is and which client
talks to it."""

from typing import Any

import flet as ft

from app.components.browser.health import BrowserFact
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from .counts_card import counts_card


def counts(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("Endpoint", str(metadata.get(BrowserFact.ENDPOINT) or "-")),
        ("Client", str(metadata.get(BrowserFact.CLIENT) or "-")),
    ]


class BrowserCard:
    """The server's endpoint and the client version, side by side."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data

    def build(self) -> ft.Container:
        """Build the browser card."""
        return counts_card(
            self.component_data,
            ComponentName.BROWSER,
            get_component_title(ComponentName.BROWSER),
            counts(self.component_data.metadata or {}),
        )
