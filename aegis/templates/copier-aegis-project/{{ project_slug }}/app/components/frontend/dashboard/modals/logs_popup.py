"""Overseer > Logs in Flet: every service's lines (``LogsSection`` with no
page) in a popup, opened from the dashboard header."""

import flet as ft

from .base_detail_popup import PagePopup
from .logs_section import LogsSection


class LogsPopup(PagePopup):
    TITLE = "Logs"
    SUBTITLE = "Every service's lines in one place."

    def section(self) -> ft.Control:
        return LogsSection()
