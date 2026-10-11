"""Browser component detail modal: the Playwright server as the app sees it.

It renders what the health check already gathered; nothing here opens a
browser.
"""

import flet as ft

from app.components.browser.health import BrowserFact
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.browser_card import counts
from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import StatRowsSection, health_dot


class BrowserDetailDialog(BaseDetailPopup):
    """Where the browser server is, and whether it answers."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        metadata = component_data.metadata or {}
        connection = StatRowsSection(
            "Connection",
            {
                **dict(counts(metadata)),
                "Status": health_dot(
                    component_data, str(metadata.get(BrowserFact.ENDPOINT) or "")
                ),
            },
        )
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title(ComponentName.BROWSER),
            subtitle_text=get_component_subtitle(ComponentName.BROWSER, metadata),
            sections=[connection],
            width=900,
            height=340,
            status_detail=get_status_detail(component_data),
        )
