"""Activity: transactions held too long and statements that found the
database locked, with the code behind each (``app.core.db_activity``)."""

import flet as ft

from app.services.system import ui_database
from app.services.system.models import ComponentStatus

from .table_tab import TableTab


class ActivityTab(TableTab):
    """The last hour's slow transactions and lock failures, newest first."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        super().__init__(
            ui_database.activity(database_component.metadata or {}),
            [
                ("When", "when", 110),
                ("What", "what", 110),
                ("Process", "process", 140),
                ("Code", "caller", None),
            ],
            "Nothing slow or locked in the last hour",
        )
