"""The backend modal itself: six tabs, and the spans that time them.

Each tab's construction is wrapped in a Logfire span so a slow modal
can be attributed to the tab that caused it. ``_span`` is a no-op when
observability is not installed, which is why the import is guarded.
"""

from collections.abc import Generator
from contextlib import contextmanager

import flet as ft
from app.components.frontend.controls.tabs import PulseTabs
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from ..load_tests_tab import LoadTestsTab
from .lifecycle_tab import LifecycleTab
from .overview_tab import OverviewTab
from .performance_tab import PerformanceTab
from .routes_tab import RoutesTab
from .traffic_tab import TrafficTab

try:
    import logfire
except ModuleNotFoundError:  # observability not installed
    logfire = None  # type: ignore[assignment]


@contextmanager
def _span(name: str) -> Generator[None]:
    """Logfire span wrapper — no-op when logfire is unavailable."""
    if logfire is not None:
        with logfire.span(name):
            yield
    else:
        yield


class BackendDetailDialog(BaseDetailPopup):
    """
    Comprehensive backend detail popup with tabbed interface.

    Displays routes, middleware stack, system metrics, and configuration
    details for the FastAPI backend component in separate tabs.
    """

    def __init__(self, backend_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize backend detail popup.

        Args:
            backend_component: ComponentStatus containing backend data
            page: Flet page instance
        """
        # Build tabs with optional logfire instrumentation
        with _span("overseer.modal.backend.build_tabs"):
            with _span("overseer.modal.backend.overview_tab"):
                overview_tab = OverviewTab(backend_component)
            with _span("overseer.modal.backend.routes_tab"):
                routes_tab = RoutesTab(backend_component)
            with _span("overseer.modal.backend.performance_tab"):
                performance_tab = PerformanceTab(backend_component)
            with _span("overseer.modal.backend.lifecycle_tab"):
                lifecycle_tab = LifecycleTab(backend_component)
            with _span("overseer.modal.backend.load_tests_tab"):
                load_tests_tab = LoadTestsTab()
            with _span("overseer.modal.backend.traffic_tab"):
                traffic_tab = TrafficTab(backend_component)

            tabs = PulseTabs(
                selected_index=0,
                tabs=[
                    ft.Tab(text="Overview", content=overview_tab),
                    ft.Tab(text="Routes", content=routes_tab),
                    ft.Tab(text="Performance", content=performance_tab),
                    ft.Tab(text="Traffic", content=traffic_tab),
                    ft.Tab(text="Lifecycle", content=lifecycle_tab),
                    ft.Tab(text="Load Tests", content=load_tests_tab),
                ],
                expand=True,
            )

        # Initialize base popup with tabs
        # (non-scrollable - tabs handle their own scrolling)
        super().__init__(
            page=page,
            component_data=backend_component,
            title_text=get_component_title("backend"),
            sections=[tabs],
            subtitle_text=get_component_subtitle("backend", backend_component.metadata),
            scrollable=False,
            width=1100,
            height=800,
            status_detail=get_status_detail(backend_component),
        )
