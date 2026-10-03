"""Settings: the server knobs and what they are set to."""

import flet as ft

from app.services.system import ui_database
from app.services.system.models import ComponentStatus

from .table_tab import TableTab


class SettingsTab(TableTab):
    """Settings tab for PostgreSQL or SQLite PRAGMA settings."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__(
            ui_database.settings(database_component.metadata or {}),
            [
                ("Setting", "setting", None),
                ("Value", "value", 120),
                ("Category", "category", 120),
            ],
            "No settings available",
        )
