"""MCP component card: how many granted tools a client is served, how many
granted names it never sees, and the transport."""

from typing import Any

import flet as ft

from app.services.system import ui_mcp
from app.services.system.models import ComponentStatus

from .counts_card import counts_card


def counts(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("Served", str(metadata.get("served", 0))),
        ("Not served", str(metadata.get("dropped", 0))),
        ("Transport", str(metadata.get("transport", "stdio"))),
    ]


class McpCard:
    """Served and dropped counts from the health check."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data

    def build(self) -> ft.Container:
        """Build the MCP card."""
        return counts_card(
            self.component_data,
            ui_mcp.NAME,
            "MCP",
            counts(self.component_data.metadata or {}),
        )
