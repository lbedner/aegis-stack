"""The dashboard's own object: the surfaces, and how a status reaches them.

Extracted from ``main.py``, which had grown to 1430 lines around it. The
class holds direct references to its surfaces rather than indexing into
the page tree, which is what stopped the IndexError crashes that
index-based access used to produce.

Two ways in, both landing in the same registry so they cannot drift:
``update_component_cards`` for the whole board on the refresh cycle, and
``update_component`` for a single component from a surface that already
holds a fresh reading.
"""

from collections.abc import Callable

import flet as ft
from flet import PageDisconnectedException

from app.components.frontend.core.session_health import page_is_connected
from app.components.frontend.dashboard.activity_feed import ActivityFeed
from app.components.frontend.dashboard.card_registry import CardRegistry
from app.components.frontend.dashboard.cards.card_utils import (
    create_health_status_indicator,
)
from app.components.frontend.dashboard.diagram.diagram_view import DiagramView
from app.components.frontend.dashboard.status_overview import StatusOverviewPanel
from app.components.frontend.theme_manager import ThemeManager
from app.core.log import logger
from app.services.system.models import ComponentStatus, ComponentStatusType


class SystemDashboard:
    """
    Professional system dashboard with safe component references.

    Eliminates IndexError crashes by storing direct references to dashboard
    components instead of using brittle index-based access patterns.

    Includes robust page disconnection handling to prevent crashes when
    users navigate away from the dashboard during auto-refresh cycles.

    Note: Uses defensive programming around Flet's private APIs for
    connection checking. This may need updates with future Flet versions.
    """

    def __init__(self):
        # Direct component references - no more brittle indexing!
        self._health_indicator_container: ft.Container | None = None
        self._cards_container: ft.Container | None = None
        self._status_overview_panel: StatusOverviewPanel | None = None
        self._activity_feed: ActivityFeed | None = None
        self._diagram_view: DiagramView | None = None
        self._theme_manager: ThemeManager | None = None
        self._page: ft.Page | None = None
        # Holds the cards between refreshes so an unchanged component
        # keeps its card object; see card_registry for why that matters.
        self._card_registry = CardRegistry()

    def initialize_components(
        self,
        health_indicator_container: ft.Container,
        cards_container: ft.Container,
        status_overview_panel: StatusOverviewPanel,
        activity_feed: ActivityFeed,
        diagram_view: DiagramView,
        theme_manager: ThemeManager,
        page: ft.Page,
    ) -> None:
        """Initialize dashboard with component references."""
        self._health_indicator_container = health_indicator_container
        self._cards_container = cards_container
        self._status_overview_panel = status_overview_panel
        self._activity_feed = activity_feed
        self._diagram_view = diagram_view
        self._theme_manager = theme_manager
        self._page = page

        # Log Flet version for debugging connection check compatibility
        try:
            from importlib.metadata import version

            flet_version = version("flet")
            logger.debug(f"Initializing dashboard with Flet version: {flet_version}")
        except Exception:
            logger.debug("Flet version not available for compatibility logging")

    def _is_page_connected(self) -> bool:
        """Whether the page's tab is still open; see ``page_is_connected``."""
        return page_is_connected(self._page)

    async def update_health_status(
        self,
        healthy_count: int,
        total_count: int,
        worst_status: ComponentStatusType | None = None,
    ) -> None:
        """Safely update health status indicator."""
        if not self._is_page_connected():
            logger.debug("Page disconnected, skipping health status update")
            return

        if not self._health_indicator_container:
            logger.warning("Health indicator container not initialized")
            return

        try:
            new_health_indicator = create_health_status_indicator(
                healthy_count, total_count, worst_status
            )
            self._health_indicator_container.content = new_health_indicator
            # No .update() call here - batched with
            # page.update() in refresh_dashboard
        except PageDisconnectedException:
            logger.debug("Page disconnected during health status update")
            return
        except Exception as e:
            logger.error(
                f"Failed to update health status: {e}",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__,
                    "function": "update_health_status",
                    "healthy_count": healthy_count,
                    "total_count": total_count,
                }
            )

    async def update_component(self, name: str, status: ComponentStatus) -> None:
        """Apply one component's status without repainting the board.

        For a surface already holding a fresh reading - the Ollama modal
        calls check_ollama_health() in-process. Goes through the same
        registry as the refresh, so what is applied here is not rebuilt
        next cycle and a health check that disagrees still wins. The
        caller owns the page push, as with the refresh methods.
        """
        if not self._is_page_connected() or not self._cards_container:
            return
        if not self._card_registry.apply(name, status):
            return
        self._cards_container.content.controls = self._card_registry.controls()

    async def update_component_cards(
        self, components: dict[str, ComponentStatus], card_creator_fn: Callable
    ) -> None:
        """Safely update component cards."""
        if not self._is_page_connected():
            logger.debug("Page disconnected, skipping component cards update")
            return

        if not self._cards_container or not self._cards_container.content:
            logger.warning("Cards container not initialized")
            return

        try:
            # Unchanged components keep the card objects Flet already
            # knows about, so the refresh diffs to nothing.
            self._cards_container.content.controls = self._card_registry.sync(
                components, card_creator_fn
            )

            # No .update() call here - batched with
            # page.update() in refresh_dashboard
        except PageDisconnectedException:
            logger.debug("Page disconnected during component cards update")
            return
        except Exception as e:
            logger.error(
                f"Failed to update component cards: {e}",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__,
                    "function": "update_component_cards",
                    "component_count": len(components),
                }
            )

    async def update_status_overview(
        self, components: dict[str, ComponentStatus]
    ) -> None:
        """Safely update the status overview panel and activity feed."""
        if not self._is_page_connected():
            logger.debug("Page disconnected, skipping status overview update")
            return

        if not self._status_overview_panel:
            logger.debug("Status overview panel not initialized")
            return

        try:
            self._status_overview_panel.update_components(components)

            # Also refresh the activity feed
            if self._activity_feed:
                self._activity_feed.refresh()

            # No .update() calls here - batched with
            # page.update() in refresh_dashboard
        except PageDisconnectedException:
            logger.debug("Page disconnected during status overview update")
            return
        except Exception as e:
            logger.error(
                f"Failed to update status overview: {e}",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__,
                    "function": "update_status_overview",
                    "component_count": len(components),
                }
            )

    async def update_diagram_view(
        self, components: dict[str, ComponentStatus]
    ) -> None:
        """Safely update the diagram view."""
        if not self._is_page_connected():
            logger.debug("Page disconnected, skipping diagram view update")
            return

        if not self._diagram_view:
            logger.debug("Diagram view not initialized")
            return

        try:
            self._diagram_view.update_components(components)
            # No .update() calls here - batched with
            # page.update() in refresh_dashboard
        except PageDisconnectedException:
            logger.debug("Page disconnected during diagram view update")
            return
        except Exception as e:
            logger.error(
                f"Failed to update diagram view: {e}",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__,
                    "function": "update_diagram_view",
                    "component_count": len(components),
                }
            )

    async def show_error_status(self) -> None:
        """Safely show error status in health indicator."""
        if not self._is_page_connected():
            logger.debug("Page disconnected, skipping error status display")
            return

        if not self._health_indicator_container:
            logger.warning(
                "Health indicator container not initialized for error display"
            )
            return

        try:
            error_indicator = create_health_status_indicator(0, 1)
            self._health_indicator_container.content = error_indicator
            # Check connection again before updating container
            if self._is_page_connected():
                self._health_indicator_container.update()
        except PageDisconnectedException:
            logger.debug("Page disconnected during error status display")
            return
        except Exception as e:
            logger.error(
                f"Failed to show error status: {e}",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__,
                    "function": "show_error_status",
                }
            )
