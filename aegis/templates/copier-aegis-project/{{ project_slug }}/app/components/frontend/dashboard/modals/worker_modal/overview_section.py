"""The top of the worker modal: four counters and two charts.

Holds the totals the SSE stream drives. Every ``increment_*`` here
moves a number on screen without a round trip to the backend, which is
why the section owns its cards rather than rebuilding them from a
status each cycle.
"""

import flet as ft
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import (
    MetricCard,
    PieChartCard,
)


class OverviewSection(ft.Container):
    """Overview section showing key worker metrics and charts."""

    def __init__(self, worker_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize overview section.

        Args:
            worker_component: Worker ComponentStatus with metadata and sub_components
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = worker_component.metadata or {}

        total_ongoing = metadata.get("total_ongoing", 0)
        total_queued = metadata.get("total_queued", 0)
        total_completed = metadata.get("total_completed", 0)
        total_failed = metadata.get("total_failed", 0)

        # Color for failed jobs - red if any failures
        failed_color = Theme.Colors.ERROR if total_failed > 0 else Theme.Colors.SUCCESS

        # Broker info from metadata
        redis_url = metadata.get("redis_url", "redis://localhost:6379")
        broker_display = redis_url.replace("redis://", "")

        # Store references for live updates
        self._card_broker = MetricCard(
            "Broker",
            broker_display,
            Theme.Colors.INFO,
        )
        self._card_processing = MetricCard(
            "Processing", str(total_ongoing), Theme.Colors.INFO
        )
        self._card_queued = MetricCard(
            "Queued", str(total_queued), Theme.Colors.WARNING
        )
        self._card_completed = MetricCard(
            "Completed", str(total_completed), Theme.Colors.SUCCESS
        )
        self._card_failed = MetricCard("Failed", str(total_failed), failed_color)

        cards_row = ft.Row(
            [
                self._card_broker,
                self._card_processing,
                self._card_queued,
                self._card_completed,
                self._card_failed,
            ],
            spacing=Theme.Spacing.MD,
        )

        # Pie charts
        self._charts_row = self._build_charts_row(worker_component)

        self.content = ft.Column(
            [cards_row, self._charts_row],
            spacing=Theme.Spacing.LG,
        )

    def _build_charts_row(self, worker_component: ComponentStatus) -> ft.Row:
        """Build the pie charts row from worker component data."""
        metadata = worker_component.metadata or {}
        total_completed = metadata.get("total_completed", 0)
        total_failed = metadata.get("total_failed", 0)

        # Chart 1: Completion Breakdown (completed vs failed)
        completion_sections: list[dict[str, object]] = []
        completion_total = total_completed + total_failed
        if total_completed > 0:
            pct = total_completed / completion_total * 100 if completion_total else 0
            completion_sections.append(
                {
                    "value": total_completed,
                    "label": f"Completed ({total_completed:,}) · {pct:.0f}%",
                    "color": Theme.Colors.SUCCESS,
                }
            )
        if total_failed > 0:
            pct = total_failed / completion_total * 100 if completion_total else 0
            completion_sections.append(
                {
                    "value": total_failed,
                    "label": f"Failed ({total_failed:,}) · {pct:.0f}%",
                    "color": Theme.Colors.ERROR,
                }
            )
        completion_chart = PieChartCard("Completion Breakdown", completion_sections)

        # Gather per-queue data
        queues_component = worker_component.sub_components.get("queues")
        per_queue: list[
            tuple[str, int, int, int]
        ] = []  # (name, completed, failed, queued)
        if queues_component and queues_component.sub_components:
            for name, queue in queues_component.sub_components.items():
                meta = queue.metadata or {}
                per_queue.append(
                    (
                        name,
                        meta.get("jobs_completed", 0),
                        meta.get("jobs_failed", 0),
                        meta.get("queued_jobs", 0),
                    )
                )

        # Chart 2: Work Distribution (per-queue completed)
        dist_sections: list[dict[str, object]] = []
        dist_total = sum(c for _, c, _, _ in per_queue)
        for name, completed, _, _ in per_queue:
            if completed > 0:
                pct = completed / dist_total * 100 if dist_total else 0
                dist_sections.append(
                    {
                        "value": completed,
                        "label": f"{name} ({completed:,}) · {pct:.0f}%",
                    }
                )
        distribution_chart = PieChartCard("Work Distribution", dist_sections)

        # Chart 3: Failure Distribution (per-queue failures)
        fail_sections: list[dict[str, object]] = []
        fail_total = sum(f for _, _, f, _ in per_queue)
        for name, _, failed, _ in per_queue:
            if failed > 0:
                pct = failed / fail_total * 100 if fail_total else 0
                fail_sections.append(
                    {
                        "value": failed,
                        "label": f"{name} ({failed:,}) · {pct:.0f}%",
                    }
                )
        failure_chart = PieChartCard("Failure Distribution", fail_sections)

        # Chart 4: Queue Backlog (per-queue pending tasks)
        backlog_sections: list[dict[str, object]] = []
        backlog_total = sum(q for _, _, _, q in per_queue)
        for name, _, _, queued in per_queue:
            if queued > 0:
                pct = queued / backlog_total * 100 if backlog_total else 0
                backlog_sections.append(
                    {
                        "value": queued,
                        "label": f"{name} ({queued:,}) · {pct:.0f}%",
                    }
                )
        backlog_chart = PieChartCard("Queue Backlog", backlog_sections)

        return ft.Column(
            [
                ft.Row(
                    [completion_chart, distribution_chart], spacing=Theme.Spacing.MD
                ),
                ft.Row([failure_chart, backlog_chart], spacing=Theme.Spacing.MD),
            ],
            spacing=Theme.Spacing.MD,
        )

    def update_data(self, worker_component: ComponentStatus) -> None:
        """Update metric values in place."""
        metadata = worker_component.metadata or {}

        total_failed = metadata.get("total_failed", 0)
        failed_color = Theme.Colors.ERROR if total_failed > 0 else Theme.Colors.SUCCESS

        self._card_processing.set_value(str(metadata.get("total_ongoing", 0)))
        self._card_queued.set_value(str(metadata.get("total_queued", 0)))
        self._card_completed.set_value(str(metadata.get("total_completed", 0)))
        self._card_failed.set_value(str(total_failed), failed_color)

        # Rebuild charts
        new_charts_row = self._build_charts_row(worker_component)
        self.content.controls[1] = new_charts_row
        self._charts_row = new_charts_row

    def rebuild_charts(
        self,
        per_queue_completed: dict[str, int] | None = None,
        per_queue_failed: dict[str, int] | None = None,
        per_queue_queued: dict[str, int] | None = None,
    ) -> None:
        """Rebuild pie charts from current card values and per-queue data."""
        total_completed = int(self._card_completed.value_text.value or "0")
        total_failed = int(self._card_failed.value_text.value or "0")

        # Chart 1: Completion Breakdown
        completion_sections: list[dict[str, object]] = []
        completion_total = total_completed + total_failed
        if total_completed > 0:
            pct = total_completed / completion_total * 100 if completion_total else 0
            completion_sections.append(
                {
                    "value": total_completed,
                    "label": f"Completed ({total_completed:,}) · {pct:.0f}%",
                    "color": Theme.Colors.SUCCESS,
                }
            )
        if total_failed > 0:
            pct = total_failed / completion_total * 100 if completion_total else 0
            completion_sections.append(
                {
                    "value": total_failed,
                    "label": f"Failed ({total_failed:,}) · {pct:.0f}%",
                    "color": Theme.Colors.ERROR,
                }
            )
        completion_chart = PieChartCard("Completion Breakdown", completion_sections)

        # Chart 2: Work Distribution
        dist_sections: list[dict[str, object]] = []
        if per_queue_completed:
            dist_total = sum(per_queue_completed.values())
            for name, completed in per_queue_completed.items():
                if completed > 0:
                    pct = completed / dist_total * 100 if dist_total else 0
                    dist_sections.append(
                        {
                            "value": completed,
                            "label": f"{name} ({completed:,}) · {pct:.0f}%",
                        }
                    )
        distribution_chart = PieChartCard("Work Distribution", dist_sections)

        # Chart 3: Failure Distribution
        fail_sections: list[dict[str, object]] = []
        if per_queue_failed:
            fail_total = sum(per_queue_failed.values())
            for name, failed in per_queue_failed.items():
                if failed > 0:
                    pct = failed / fail_total * 100 if fail_total else 0
                    fail_sections.append(
                        {
                            "value": failed,
                            "label": f"{name} ({failed:,}) · {pct:.0f}%",
                        }
                    )
        failure_chart = PieChartCard("Failure Distribution", fail_sections)

        # Chart 4: Queue Backlog
        backlog_sections: list[dict[str, object]] = []
        if per_queue_queued:
            backlog_total = sum(per_queue_queued.values())
            for name, queued in per_queue_queued.items():
                if queued > 0:
                    pct = queued / backlog_total * 100 if backlog_total else 0
                    backlog_sections.append(
                        {
                            "value": queued,
                            "label": f"{name} ({queued:,}) · {pct:.0f}%",
                        }
                    )
        backlog_chart = PieChartCard("Queue Backlog", backlog_sections)

        new_charts = ft.Column(
            [
                ft.Row(
                    [completion_chart, distribution_chart], spacing=Theme.Spacing.MD
                ),
                ft.Row([failure_chart, backlog_chart], spacing=Theme.Spacing.MD),
            ],
            spacing=Theme.Spacing.MD,
        )
        self.content.controls[1] = new_charts
        self._charts_row = new_charts

    def _increment_card(self, card: MetricCard, delta: int = 1) -> None:
        """Increment a MetricCard's numeric value by delta."""
        current = int(card.value_text.value or "0")
        card.set_value(str(current + delta))

    def sync_queued(self, total: int) -> None:
        """Set queued card to an explicit value (used after per-queue cleanup)."""
        self._card_queued.set_value(str(total))

    def increment_queued(self) -> None:
        """Increment queued count by 1."""
        self._increment_card(self._card_queued)

    def decrement_queued(self) -> None:
        """Decrement queued count by 1 (floor at 0)."""
        current = int(self._card_queued.value_text.value or "0")
        self._card_queued.set_value(str(max(0, current - 1)))

    def increment_ongoing(self) -> None:
        """Increment processing count by 1."""
        self._increment_card(self._card_processing)

    def decrement_ongoing(self) -> None:
        """Decrement processing count by 1 (floor at 0)."""
        current = int(self._card_processing.value_text.value or "0")
        self._card_processing.set_value(str(max(0, current - 1)))

    def increment_completed(self) -> None:
        """Increment completed count by 1."""
        self._increment_card(self._card_completed)

    def increment_failed(self) -> None:
        """Increment failed count by 1."""
        self._increment_card(self._card_failed)
        # Ensure failed color is red when > 0
        self._card_failed.value_text.color = Theme.Colors.ERROR

    def set_totals(
        self,
        total_queued: int,
        total_ongoing: int,
        total_completed: int,
        total_failed: int,
    ) -> None:
        """Set all counters to absolute values from SSE batch data."""
        self._card_queued.set_value(str(total_queued))
        self._card_processing.set_value(str(total_ongoing))
        self._card_completed.set_value(str(total_completed))
        failed_color = Theme.Colors.ERROR if total_failed > 0 else Theme.Colors.SUCCESS
        self._card_failed.set_value(str(total_failed), failed_color)
