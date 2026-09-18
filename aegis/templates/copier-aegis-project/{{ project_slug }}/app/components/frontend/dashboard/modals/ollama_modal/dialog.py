"""The Ollama modal itself: three tabs, and the poll that feeds them.

While the modal is open it re-reads health on an interval and applies
the result. ``_data_snapshot`` is what decides whether that result is
worth repainting for - an unchanged snapshot skips the rebuild, so an
open modal does not discard its controls every few seconds.
"""

from __future__ import annotations

import asyncio
from typing import Any

import flet as ft
from app.components.frontend.controls.tabs import PulseTabs
from app.core.log import logger
from app.services.ai.domains.llm.ollama_activity import get_ollama_activity
from app.services.system.models import ComponentStatus

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from .activity_tab import ActivityTab
from .columns import MODELS_MODAL_WIDTH
from .models_tab import ModelsTab
from .overview_tab import OverviewTab

# How often the open modal re-checks Ollama. The /api/ps probe is a local
# sub-100ms call, so this is cheap; it exists because Ollama evicts idle
# models on its own (keep_alive expiry) and there is no event to listen for.
POLL_INTERVAL_SECONDS = 10.0


def _data_snapshot(component_data: ComponentStatus) -> tuple[Any, ...]:
    """Hashable fingerprint of everything the modal renders.

    Used by the poll loop to skip rebuilds when nothing changed - a rebuild
    drops scroll position and hover state, so it should only happen on a
    real transition (model loaded/evicted, VRAM shifted, new activity).
    """
    from app.core.config import settings

    metadata = component_data.metadata or {}
    events = get_ollama_activity().events()
    return (
        component_data.status,
        metadata.get("version"),
        metadata.get("total_vram_gb"),
        tuple(
            sorted(
                (rm.get("name", ""), rm.get("size_vram_gb", 0.0))
                for rm in metadata.get("running_models", [])
            )
        ),
        tuple(sorted(m.get("name", "") for m in metadata.get("installed_models", []))),
        getattr(settings, "AI_MODEL", None),
        len(events),
        events[0].timestamp if events else None,
    )


class OllamaDetailDialog(BaseDetailPopup):
    """
    Ollama local LLM infrastructure detail popup dialog.

    Displays comprehensive Ollama information including running models,
    VRAM usage, and server configuration.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the Ollama details popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
            page: Flet page instance
        """
        self._page = page
        self._component_data = component_data
        self._poll_task: asyncio.Task[None] | None = None
        self._snapshot = _data_snapshot(component_data)

        metadata = component_data.metadata or {}
        version = metadata.get("version", "")
        running_count = metadata.get("running_models_count", 0)

        # Build subtitle - show Ollama with version and model count
        subtitle = self._build_subtitle(version, running_count)

        # Build tabs - store references for refresh
        self._overview_tab = ft.Tab(
            text="Overview", content=OverviewTab(component_data, page)
        )
        self._models_tab = ft.Tab(
            text="Models", content=ModelsTab(component_data, page, dialog=self)
        )
        self._activity_tab = ft.Tab(text="Activity", content=ActivityTab())

        self._tabs = PulseTabs(
            selected_index=0,
            tabs=[self._overview_tab, self._models_tab, self._activity_tab],
            expand=True,
        )

        # Initialize base popup with tabs
        super().__init__(
            page=page,
            component_data=component_data,
            title_text="Inference",
            subtitle_text=subtitle,
            sections=[self._tabs],
            scrollable=False,
            # Sized to the Models table, the widest thing the dialog
            # holds - see MODEL_TABLE_WIDTH for why that is a computed
            # value rather than a number picked by eye.
            width=MODELS_MODAL_WIDTH,
            height=550,
            status_detail=get_status_detail(component_data),
        )

    def _build_subtitle(self, version: str, running_count: int) -> str:
        """Build subtitle text based on version and running model count."""
        subtitle = f"Ollama v{version}" if version else "Ollama"
        if running_count > 0:
            status = f"{running_count} model{'s' if running_count > 1 else ''} loaded"
            subtitle = f"{subtitle} • {status}"
        return subtitle

    def show(self) -> None:
        """Show the popup and start the visibility-scoped poll loop."""
        super().show()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = self._page.run_task(self._poll_while_visible)

    def hide(self) -> None:
        """Hide the popup and stop polling."""
        super().hide()
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    def update_data(self, component_data: ComponentStatus) -> None:
        """Adopt the dashboard's latest health snapshot on re-open.

        The modal is cached across opens (see ``_open_modal``), so without
        this a re-open would show whatever Ollama looked like the first
        time. The poll loop then re-fetches live data right after show().
        """
        self._snapshot = _data_snapshot(component_data)
        self._apply(component_data)

    async def _poll_while_visible(self) -> None:
        """Keep the modal in sync with Ollama while it is open.

        Ollama drops idle models on its own (``keep_alive`` expiry) and a
        chat request can warm one, so a modal that only refreshes after
        button clicks goes stale. The first tick runs immediately to catch
        anything that happened since the dialog was built or last shown.
        """
        while self.visible:
            try:
                await self.refresh_data(only_if_changed=True)
            except Exception as e:
                # A failing update means the page is gone (disconnect or
                # teardown); stop polling - show() restarts it next open.
                logger.debug(f"Ollama modal poll stopped: {e}")
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def refresh_data(self, *, only_if_changed: bool = False) -> None:
        """Refresh modal with fresh health data.

        Args:
            only_if_changed: Skip the tab rebuild when nothing the modal
                renders has changed. The poll loop passes True so scroll
                and hover state survive quiet ticks; the Load/Unload/Use
                buttons use the default and always rebuild.
        """
        from app.services.system.health import check_ollama_health

        fresh_status = await check_ollama_health()

        snapshot = _data_snapshot(fresh_status)
        if only_if_changed and snapshot == self._snapshot:
            # Nothing moved; just let the relative timestamps age.
            self._refresh_activity_times()
            self._page.update()
            return

        self._snapshot = snapshot
        self._apply(fresh_status)
        # Was stale for up to 30s after a load, and the only way to
        # hurry it was repainting the whole board. This reading is
        # already fresh, so hand it to the card it describes.
        apply_one = self._page.data.get("update_component")
        if apply_one is not None:
            await apply_one("ollama", fresh_status)
        self._page.update()

    def _apply(self, fresh_status: ComponentStatus) -> None:
        """Rebuild the modal header and tabs from a health snapshot."""
        self._component_data = fresh_status

        # Update subtitle with fresh counts
        metadata = fresh_status.metadata or {}
        version = metadata.get("version", "")
        running_count = metadata.get("running_models_count", 0)
        new_subtitle = self._build_subtitle(version, running_count)

        # Update subtitle in title row (second element in title column)
        if self._title_row and len(self._title_row.controls) > 0:
            title_column = self._title_row.controls[0]
            if hasattr(title_column, "controls") and len(title_column.controls) > 1:
                title_column.controls[1].value = new_subtitle

        # Update the status badge in the header
        self.update_status(fresh_status.status, get_status_detail(fresh_status))

        # Preserve current tab selection
        current_tab_index = self._tabs.selected_index

        # Rebuild tab contents with fresh data
        self._overview_tab.content = OverviewTab(fresh_status, self._page)
        self._models_tab.content = ModelsTab(fresh_status, self._page, dialog=self)
        self._activity_tab.content = ActivityTab()

        # Restore tab selection
        self._tabs.selected_index = current_tab_index

    def _refresh_activity_times(self) -> None:
        """Update the Activity tab's relative timestamps in place."""
        content = self._activity_tab.content
        if isinstance(content, ActivityTab):
            content.section.refresh_times()
