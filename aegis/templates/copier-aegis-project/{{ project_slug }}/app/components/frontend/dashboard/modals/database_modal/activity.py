"""Slow & locked: the last hour's slow transactions and lock failures by
the code behind them, the summary the database health carries
(``app.core.db_activity.summary``); Overseer's Slow & locked has the rows,
any window and the filters."""

import flet as ft

from app.core import db_activity
from app.services.system import ui_database
from app.services.system.models import ComponentStatus

from ..table_tab import TableTab


class ActivityTab(TableTab):
    """The summary's code sites, the longest held in all first."""

    def __init__(self, database_component: ComponentStatus, page: ft.Page) -> None:
        summary = (database_component.metadata or {}).get("activity") or {}
        super().__init__(
            ui_database.activity_groups(summary.get("by_code", [])),
            [
                ("Count", "count", 70),
                ("Held", "held", 90),
                ("Longest", "longest", 90),
                ("Process", "processes", 140),
                ("Code", "code", None),
            ],
            ui_database.nothing_in(
                summary.get("window_s", db_activity.SUMMARY_SECONDS)
            ),
        )
