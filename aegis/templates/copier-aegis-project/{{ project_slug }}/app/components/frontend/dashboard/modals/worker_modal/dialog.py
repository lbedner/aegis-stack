"""The worker modal itself: the three sections, tabbed.

Owns the SSE fan-out. An event arrives once and is applied to every
section that shows it, then ``flush`` paints at most once per tick
rather than once per event.
"""

import contextlib

import flet as ft
from app.components.frontend.controls.tabs import PulseTabs
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle, get_component_title

from ..base_detail_popup import BaseDetailPopup
from ..task_history_section import TaskHistorySection
from .lifecycle_tab import WorkerLifecycleTab
from .overview_section import OverviewSection
from .queue_health_section import QueueHealthSection


class WorkerDetailDialog(BaseDetailPopup):
    """
    Worker component detail popup dialog.

    Displays comprehensive worker information including queue health,
    job statistics, and broker connection diagram.
    """

    # Worker modal is taller to accommodate tabs
    WORKER_MODAL_HEIGHT = 800

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize worker detail popup.

        Args:
            component_data: Worker ComponentStatus from health check
        """
        # Kept for the live feed: ``self.page`` is only set once mounted,
        # which the first ``show`` can precede.
        self._feed_page = page
        # Build sections (store references for live updates)
        self._overview = OverviewSection(component_data, page)
        self._queue_health = QueueHealthSection(component_data, page)
        self._lifecycle = WorkerLifecycleTab()
        self._task_history = TaskHistorySection(page)
        self._dirty = False

        # Build tabbed layout (matches AI modal tab styling)
        tabs = PulseTabs(
            selected_index=0,
            expand=True,
            tabs=[
                ft.Tab(
                    text="Overview",
                    content=ft.Container(
                        content=ft.Column(
                            [self._overview],
                            spacing=0,
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        expand=True,
                    ),
                ),
                ft.Tab(
                    text="Queues",
                    content=ft.Container(
                        content=ft.Column(
                            [self._queue_health],
                            spacing=0,
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        expand=True,
                    ),
                ),
                ft.Tab(
                    text="Activity",
                    content=ft.Container(
                        content=self._task_history,
                        expand=True,
                    ),
                ),
                ft.Tab(
                    text="Lifecycle",
                    content=ft.Container(
                        content=self._lifecycle,
                        expand=True,
                    ),
                ),
            ],
        )

        # Compute status detail (e.g., "2/3 queues online")
        status_detail = self._compute_status_detail(component_data)

        # Initialize base popup with tabs as single section (non-scrollable)
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("worker"),
            subtitle_text=get_component_subtitle("worker", component_data.metadata),
            sections=[tabs],
            status_detail=status_detail,
            scrollable=False,
            height=self.WORKER_MODAL_HEIGHT,
        )

    def show(self) -> None:
        """Show, and start the live feed: it only runs while this is open."""
        super().show()
        stream = (self._feed_page.data or {}).get("worker_stream")
        if stream is not None:
            stream.start()

    def hide(self) -> None:
        """Hide, and stop the live feed. Every close path ends up here."""
        super().hide()
        stream = (self._feed_page.data or {}).get("worker_stream")
        if stream is not None:
            stream.stop()

    def update_data(self, component_data: ComponentStatus) -> None:
        """Update all sections with fresh data (mutates existing controls)."""
        self._overview.update_data(component_data)
        self._queue_health.update_data(component_data)

        # Update status badge in header
        new_detail = self._compute_status_detail(component_data)
        self.update_status(component_data.status, new_detail)

        # Push changes to Flet client — page.update() alone doesn't
        # propagate to controls inside page.overlay popups
        self.update()

        # Refresh task history after UI update completes
        with contextlib.suppress(Exception):
            self._task_history._schedule_load()

    def increment_queued(self, queue: str) -> None:
        """A job was enqueued — increment queued counters."""
        self._overview.increment_queued()
        self._queue_health.increment_queued(queue)
        self._dirty = True

    def decrement_queued(self, queue: str) -> None:
        """A job left the queue — decrement queued counters."""
        self._overview.decrement_queued()
        self._queue_health.decrement_queued(queue)
        self._dirty = True

    def increment_ongoing(self, queue: str) -> None:
        """A job started processing — increment ongoing counters."""
        self._overview.increment_ongoing()
        self._queue_health.increment_ongoing(queue)
        self._dirty = True

    def increment_completed(self, queue: str) -> None:
        """A job completed — increment completed, decrement ongoing."""
        self._overview.increment_completed()
        self._overview.decrement_ongoing()
        self._queue_health.increment_completed(queue)
        self._queue_health.decrement_ongoing(queue)
        # Sync summary queued card with per-queue totals (cleanup may have zeroed rows)
        self._overview.sync_queued(self._queue_health.total_queued())
        self._overview.rebuild_charts(
            self._queue_health.per_queue_completed(),
            self._queue_health.per_queue_failed(),
            self._queue_health.per_queue_queued(),
        )
        self._dirty = True

    def increment_failed(self, queue: str) -> None:
        """A job failed — increment failed, decrement ongoing."""
        self._overview.increment_failed()
        self._overview.decrement_ongoing()
        self._queue_health.increment_failed(queue)
        self._queue_health.decrement_ongoing(queue)
        # Sync summary queued card with per-queue totals (cleanup may have zeroed rows)
        self._overview.sync_queued(self._queue_health.total_queued())
        self._overview.rebuild_charts(
            self._queue_health.per_queue_completed(),
            self._queue_health.per_queue_failed(),
            self._queue_health.per_queue_queued(),
        )
        self._dirty = True

    def set_totals(self, queues: dict[str, dict[str, int]]) -> None:
        """Set all counters to absolute values from SSE batch data.

        Args:
            queues: Mapping of queue_type → {queued, ongoing, completed, failed}
        """
        total_queued = total_ongoing = total_completed = total_failed = 0
        for queue, vals in queues.items():
            q = vals.get("queued", 0)
            o = vals.get("ongoing", 0)
            c = vals.get("completed", 0)
            f = vals.get("failed", 0)
            total_queued += q
            total_ongoing += o
            total_completed += c
            total_failed += f
            self._queue_health.set_queue_totals(queue, q, o, c, f)
        self._overview.set_totals(
            total_queued,
            total_ongoing,
            total_completed,
            total_failed,
        )
        self._overview.rebuild_charts(
            self._queue_health.per_queue_completed(),
            self._queue_health.per_queue_failed(),
            self._queue_health.per_queue_queued(),
        )
        self._dirty = True

    def flush(self) -> None:
        """Push pending UI changes to the Flet client.

        Called by the SSE listener on a time-based schedule rather than
        per-event, so the browser isn't overwhelmed during high throughput.
        """
        if self._dirty:
            self.update()
            self._dirty = False

    @staticmethod
    def _compute_status_detail(component_data: ComponentStatus) -> str | None:
        """Get status detail for non-healthy states.

        Uses health check message for detail text.
        """
        from app.components.frontend.dashboard.cards.card_utils import get_status_detail

        return get_status_detail(component_data)
