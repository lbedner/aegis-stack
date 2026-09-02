"""Storage component detail modal: the bucket as the app sees it."""

import flet as ft

from app.core.formatting import format_bytes
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import InfoCard, SectionHeader


class StorageDetailDialog(BaseDetailPopup):
    """Where objects live, how the app reaches them, and how many there are."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        metadata = component_data.metadata or {}
        cards: list[ft.Control] = [
            InfoCard("Backend", str(metadata.get("backend") or "-")),
            InfoCard("Endpoint", str(metadata.get("endpoint") or "-")),
            InfoCard("Bucket", str(metadata.get("bucket") or "-")),
            InfoCard("Region", str(metadata.get("region") or "-")),
        ]
        if "objects" in metadata:
            cards.append(InfoCard("Objects", str(metadata.get("objects", 0))))
            cards.append(InfoCard("Stored", format_bytes(int(metadata.get("bytes") or 0))))
        sections: list[ft.Control] = [
            SectionHeader("Connection"),
            ft.Row(cards, wrap=True, spacing=12, run_spacing=12),
        ]
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("storage"),
            subtitle_text=get_component_subtitle("storage", metadata),
            sections=sections,
            status_detail=get_status_detail(component_data),
        )
