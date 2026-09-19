"""The dialog that hangs the tabs together."""

import flet as ft

from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.modals.database_modal.migrations import (
    MigrationsTab,
)
from app.components.frontend.dashboard.modals.database_modal.overview import OverviewTab
from app.components.frontend.dashboard.modals.database_modal.schema import SchemaTab
from app.components.frontend.dashboard.modals.database_modal.settings import SettingsTab
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title, get_database_subtitle

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup


class DatabaseDetailDialog(BaseDetailPopup):
    """Database detail popup with tabbed interface."""

    def __init__(
        self,
        database_component: ComponentStatus,
        page: ft.Page,
    ) -> None:
        metadata = database_component.metadata or {}
        subtitle = get_database_subtitle(metadata)

        # Build tabs
        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Overview", content=OverviewTab(database_component, page)),
                ft.Tab(text="Schema", content=SchemaTab(database_component, page)),
                ft.Tab(
                    text="Migrations", content=MigrationsTab(database_component, page)
                ),
                ft.Tab(text="Settings", content=SettingsTab(database_component, page)),
            ],
            expand=True,
        )

        # Initialize base popup with tabs
        super().__init__(
            page=page,
            component_data=database_component,
            title_text=get_component_title("database"),
            subtitle_text=subtitle,
            sections=[tabs],
            scrollable=False,
            width=1000,
            height=700,
            status_detail=get_status_detail(database_component),
        )
