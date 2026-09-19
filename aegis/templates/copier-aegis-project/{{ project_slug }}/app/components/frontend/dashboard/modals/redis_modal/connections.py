"""Connections: who is attached to the cache right now."""

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
from app.components.frontend.dashboard.modals.redis_modal.constants import COL_WIDTH_ADDRESS, COL_WIDTH_AGE, COL_WIDTH_CLIENT_ID, COL_WIDTH_COMMAND, COL_WIDTH_DB, COL_WIDTH_IDLE, STAT_LABEL_WIDTH


class ClientConnectionRow(ft.Container):
    """Single client connection display row."""

    def __init__(self, client: dict) -> None:
        """
        Initialize client connection row.

        Args:
            client: Client info from CLIENT LIST
        """
        super().__init__()

        client_id = client.get("id", "")
        addr = client.get("addr", "")
        age = client.get("age", "0")
        idle = client.get("idle", "0")
        db = client.get("db", "0")
        cmd = client.get("cmd", "")

        self.content = ft.Row(
            [
                ft.Container(
                    content=BodyText(client_id, text_align=ft.TextAlign.CENTER),
                    width=COL_WIDTH_CLIENT_ID,
                ),
                ft.Container(
                    content=BodyText(addr),
                    width=COL_WIDTH_ADDRESS,
                ),
                ft.Container(
                    content=BodyText(age, text_align=ft.TextAlign.CENTER),
                    width=COL_WIDTH_AGE,
                ),
                ft.Container(
                    content=BodyText(idle, text_align=ft.TextAlign.CENTER),
                    width=COL_WIDTH_IDLE,
                ),
                ft.Container(
                    content=BodyText(db, text_align=ft.TextAlign.CENTER),
                    width=COL_WIDTH_DB,
                ),
                ft.Container(
                    content=BodyText(cmd),
                    width=COL_WIDTH_COMMAND,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
        self.padding = ft.padding.symmetric(vertical=Theme.Spacing.XS)


class ActiveConnectionsSection(ft.Container):
    """Active client connections section."""

    def __init__(self, redis_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize active connections section.

        Args:
            redis_component: Redis ComponentStatus with active_clients
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = redis_component.metadata or {}
        active_clients = metadata.get("active_clients", [])

        # Column headers
        header_row = ft.Row(
            [
                ft.Container(
                    content=SecondaryText(
                        "Client ID",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_CLIENT_ID,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Address", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_ADDRESS,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Age (s)",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_AGE,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Idle (s)",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_IDLE,
                ),
                ft.Container(
                    content=SecondaryText(
                        "DB",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=COL_WIDTH_DB,
                ),
                ft.Container(
                    content=SecondaryText(
                        "Command", weight=Theme.Typography.WEIGHT_SEMIBOLD
                    ),
                    width=COL_WIDTH_COMMAND,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )

        # Client rows
        client_rows = [ClientConnectionRow(client) for client in active_clients]

        self.content = ft.Column(
            [
                H3Text("Active Connections"),
                ft.Container(height=Theme.Spacing.SM),
                header_row,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Column(
                    client_rows if client_rows else [BodyText("No active connections")],
                    spacing=0,
                ),
            ],
            spacing=0,
        )


class ConnectionsTab(ft.Container):
    """Connections tab showing active client connections and connection info."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}

        # Connection info section
        redis_url = metadata.get("url", "Not configured")
        host = metadata.get("host", "localhost")
        port = metadata.get("port", 6379)
        connected_clients = metadata.get("connected_clients", 0)
        total_connections = metadata.get("total_connections_received", 0)
        blocked_clients = metadata.get("blocked_clients", 0)

        def info_row(label: str, value: str) -> ft.Row:
            """Create an info row."""
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

        connection_info = ft.Column(
            [
                H3Text("Connection Info"),
                ft.Container(height=Theme.Spacing.SM),
                info_row("Host", f"{host}:{port}"),
                info_row("URL", redis_url),
                ft.Divider(height=20, color=ft.Colors.OUTLINE_VARIANT),
                info_row("Connected Clients", str(connected_clients)),
                info_row("Blocked Clients", str(blocked_clients)),
                info_row("Total Connections", str(total_connections)),
            ],
            spacing=Theme.Spacing.XS,
        )

        self.content = ft.Column(
            [
                ft.Container(content=connection_info, padding=Theme.Spacing.MD),
                ActiveConnectionsSection(component_data, page),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True

