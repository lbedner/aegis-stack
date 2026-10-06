"""MCP component detail modal: the same served tools, connect commands,
client activity and (with auth) tokens as the htmx page (``ui_mcp``), read
when it opens."""

import flet as ft

from app.components.frontend.controls import H3Text, SecondaryText
from app.components.frontend.controls.buttons import IconCopyButton
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import ui_mcp
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from ..cards.mcp_card import counts
from .base_detail_popup import BaseDetailPopup
from .mcp_tokens import McpTokensSection
from .modal_sections import StatRowsSection, metric_row
from .table_tab import TableTab, columns_of


def _command(value: str) -> ft.Control:
    """A command to run, with its copy button (htmx's ``command`` macro)."""
    return ft.Row(
        [SecondaryText(value, selectable=True), IconCopyButton(lambda: value)],
        spacing=Theme.Spacing.XS,
    )


class McpSection(ft.Column):
    """What a client is served and not, how to connect one, and what each
    client did."""

    def __init__(self) -> None:
        super().__init__(spacing=Theme.Spacing.SM)
        self.controls = [SecondaryText("Reading the grant.")]

    def did_mount(self) -> None:
        self.page.run_task(self.load)

    async def load(self) -> None:
        grant, recorded = ui_mcp.grant(), await ui_mcp.recorded()
        controls: list[ft.Control] = [
            H3Text("Served"),
            TableTab(
                grant["served"], columns_of(ui_mcp.SERVED_COLUMNS), ui_mcp.NONE_SERVED
            ),
        ]
        if grant["dropped"]:
            controls += [
                H3Text("Granted, not served"),
                TableTab(grant["dropped"], columns_of(ui_mcp.DROPPED_COLUMNS), ""),
            ]
        controls.append(
            StatRowsSection(
                "Connect a client",
                {c["label"]: _command(c["command"]) for c in ui_mcp.connect()},
            )
        )
        if recorded["clients"]:
            controls += [
                H3Text("By client"),
                TableTab(recorded["clients"], columns_of(ui_mcp.CLIENT_COLUMNS), ""),
                H3Text("Recent calls"),
                TableTab(recorded["calls"], columns_of(ui_mcp.CALL_COLUMNS), ""),
            ]
        else:
            controls.append(SecondaryText(recorded["note"]))
        self.controls = controls
        if self.page is not None:
            self.update()


class McpDetailDialog(BaseDetailPopup):
    """What an outside assistant can reach, and what it did."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        metadata = component_data.metadata or {}
        tokens: list[ft.Control] = (
            [ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT), McpTokensSection(page)]
            if ui_mcp.has_tokens()
            else []
        )
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title(ui_mcp.NAME),
            subtitle_text=get_component_subtitle(ui_mcp.NAME, metadata),
            sections=[
                metric_row(counts(metadata)),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                McpSection(),
                *tokens,
            ],
            width=900,
            height=640,
            status_detail=get_status_detail(component_data),
        )
