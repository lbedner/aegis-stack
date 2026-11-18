"""Runner component detail modal: the queue as the health check counted it.

It renders what the health check already gathered; the runs themselves are
on the Overseer's Runner page.
"""

import flet as ft

from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from ..cards.runner_card import counts
from .base_detail_popup import BaseDetailPopup
from .modal_sections import StatRowsSection, health_dot


class RunnerDetailDialog(BaseDetailPopup):
    """How many runs wait, how many a runner has, and whether one listens."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        metadata = component_data.metadata or {}
        queue = StatRowsSection(
            "Queue",
            {
                **dict(counts(metadata)),
                "Status": health_dot(component_data, component_data.message),
            },
        )
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title(ComponentName.RUNNER),
            subtitle_text=get_component_subtitle(ComponentName.RUNNER, metadata),
            sections=[queue],
            width=900,
            height=340,
            status_detail=get_status_detail(component_data),
        )
