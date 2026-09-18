"""Per-queue health: one expandable row for each queue that exists.

The column widths live here because this is the only table that has
these columns. The counter methods mirror ``OverviewSection``'s, at the
granularity of a single queue, so an event that names a queue can move
that queue's cell and leave the rest alone.
"""

import time

import flet as ft
from app.components.frontend.controls import (
    DataTableColumn,
    ExpandableDataTable,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from .queue_rows import _build_queue_health_row, _compute_queue_values, _format_eta

# Queue health table column widths (pixels)
COL_WIDTH_STATUS_ICON = 30


COL_WIDTH_QUEUED = 80


COL_WIDTH_PROCESSING = 80


COL_WIDTH_COMPLETED = 100


COL_WIDTH_FAILED = 80


COL_WIDTH_SUCCESS_RATE = 100


COL_WIDTH_THROUGHPUT = 80


COL_WIDTH_ETA = 80


COL_WIDTH_STATUS = 80


class QueueHealthSection(ft.Container):
    """Queue health status table section."""

    def __init__(self, worker_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize queue health section.

        Args:
            worker_component: Worker ComponentStatus with queue sub-components
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        # Extract queue sub-components
        queues_component = worker_component.sub_components.get("queues")
        queue_components = []
        if queues_component and queues_component.sub_components:
            queue_components = list(queues_component.sub_components.values())

        # Define columns
        self._columns = [
            DataTableColumn("", width=COL_WIDTH_STATUS_ICON),  # Status icon
            DataTableColumn("Queue Name"),  # expands
            DataTableColumn("Queued", width=COL_WIDTH_QUEUED, alignment="center"),
            DataTableColumn(
                "Processing", width=COL_WIDTH_PROCESSING, alignment="center"
            ),
            DataTableColumn("Completed", width=COL_WIDTH_COMPLETED, alignment="center"),
            DataTableColumn("Failed", width=COL_WIDTH_FAILED, alignment="center"),
            DataTableColumn(
                "Success Rate", width=COL_WIDTH_SUCCESS_RATE, alignment="center"
            ),
            DataTableColumn("Tasks/s", width=COL_WIDTH_THROUGHPUT, alignment="center"),
            DataTableColumn("ETA", width=COL_WIDTH_ETA, alignment="center"),
            DataTableColumn("Status", width=COL_WIDTH_STATUS, alignment="center"),
        ]

        # Build row data and store cell references by queue name
        rows = []
        self._queue_cells: dict[str, list] = {}
        # Throughput tracking: {queue: {"start_time": float, "start_completed": int}}
        self._queue_tracking: dict[str, dict[str, float | int]] = {}
        for queue in queue_components:
            row = _build_queue_health_row(queue)
            rows.append(row)
            self._queue_cells[queue.name] = row.cells

        # Build table (stored for potential rebuild on queue list changes)
        self._table = ExpandableDataTable(
            columns=self._columns,
            rows=rows,
            row_padding=6,
            empty_message="No queues configured",
        )

        self.content = self._table

    def update_data(self, worker_component: ComponentStatus) -> None:
        """Update queue health values in place by mutating existing cell controls."""
        queues_component = worker_component.sub_components.get("queues")
        if not queues_component or not queues_component.sub_components:
            return

        # If queue list changed, rebuild the entire table
        new_names = set(queues_component.sub_components.keys())
        if new_names != set(self._queue_cells.keys()):
            queue_components = list(queues_component.sub_components.values())
            rows = []
            self._queue_cells = {}
            for queue in queue_components:
                row = _build_queue_health_row(queue)
                rows.append(row)
                self._queue_cells[queue.name] = row.cells
            self._table._rows = rows
            self._table._expanded = [False] * len(rows)
            self._table._build()
            return

        # Same queues — mutate cell values in place (no rebuild needed)
        for queue_name, queue_comp in queues_component.sub_components.items():
            cells = self._queue_cells.get(queue_name)
            if not cells:
                continue

            vals = _compute_queue_values(queue_comp)
            # cells: [0]=status dot, [1]=name, [2]=queued, [3]=processing,
            #         [4]=completed, [5]=failed, [6]=rate,
            #         [7]=tasks/s, [8]=ETA, [9]=status
            cells[0].content.bgcolor = vals["status_color"]
            cells[2].value = str(vals["queued_jobs"])
            cells[3].value = str(vals["jobs_ongoing"])
            cells[4].value = str(vals["jobs_completed"])
            cells[5].value = str(vals["jobs_failed"])
            cells[6].value = (
                f"{vals['success_rate']:.1f}%"
                if vals["success_rate"] is not None
                else "N/A"
            )
            cells[6].color = vals["rate_color"]
            cells[9].value = vals["status_text"]
            cells[9].color = vals["status_color"]

    def _increment_cell(self, queue: str, cell_idx: int, delta: int = 1) -> None:
        """Increment a numeric cell value for a queue row."""
        cells = self._queue_cells.get(queue)
        if not cells:
            return
        current = int(cells[cell_idx].value or "0")
        cells[cell_idx].value = str(current + delta)

    def increment_queued(self, queue: str) -> None:
        """Increment queued cell (index 2) for a queue."""
        self._increment_cell(queue, 2)

    def decrement_queued(self, queue: str) -> None:
        """Decrement queued cell (index 2) for a queue, floor at 0."""
        cells = self._queue_cells.get(queue)
        if not cells:
            return
        current = int(cells[2].value or "0")
        cells[2].value = str(max(0, current - 1))

    def increment_ongoing(self, queue: str) -> None:
        """Increment processing cell (index 3) for a queue."""
        self._increment_cell(queue, 3)
        cells = self._queue_cells.get(queue)
        if cells:
            cells[0].content.bgcolor = Theme.Colors.INFO
            cells[9].value = "Active"
            cells[9].color = Theme.Colors.INFO

    def decrement_ongoing(self, queue: str) -> None:
        """Decrement processing cell (index 3) for a queue, floor at 0."""
        cells = self._queue_cells.get(queue)
        if not cells:
            return
        current = int(cells[3].value or "0")
        new_val = max(0, current - 1)
        cells[3].value = str(new_val)
        if new_val == 0:
            queued = int(cells[2].value or "0")
            if queued <= 1:
                # Revert to Online when truly idle. The <= 1 guard
                # tolerates a stale queued count of 1 caused by SSE
                # event gaps (events published between read_queue_totals
                # and the first XREAD are lost, leaving the counter off
                # by 1). Zero out queued to prevent the stale value from
                # persisting in the UI.
                cells[2].value = "0"
                cells[0].content.bgcolor = Theme.Colors.SUCCESS
                cells[9].value = "Online"
                cells[9].color = Theme.Colors.SUCCESS
                self._queue_tracking.pop(queue, None)

    def total_queued(self) -> int:
        """Sum queued values across all queue rows."""
        total = 0
        for cells in self._queue_cells.values():
            total += int(cells[2].value or "0")
        return total

    def per_queue_completed(self) -> dict[str, int]:
        """Return completed counts per queue."""
        return {
            queue: int(cells[4].value or "0")
            for queue, cells in self._queue_cells.items()
        }

    def per_queue_failed(self) -> dict[str, int]:
        """Return failed counts per queue."""
        return {
            queue: int(cells[5].value or "0")
            for queue, cells in self._queue_cells.items()
        }

    def per_queue_queued(self) -> dict[str, int]:
        """Return queued (pending) counts per queue."""
        return {
            queue: int(cells[2].value or "0")
            for queue, cells in self._queue_cells.items()
        }

    def increment_completed(self, queue: str) -> None:
        """Increment completed cell (index 4) for a queue."""
        self._increment_cell(queue, 4)
        self._update_throughput(queue)

    def increment_failed(self, queue: str) -> None:
        """Increment failed cell (index 5) for a queue."""
        self._increment_cell(queue, 5)
        self._update_throughput(queue)

    def _update_throughput(self, queue: str) -> None:
        """Recompute tasks/s and ETA for a queue based on completed count."""
        cells = self._queue_cells.get(queue)
        if not cells:
            return

        completed = int(cells[4].value or "0")
        queued = int(cells[2].value or "0")

        tracking = self._queue_tracking.get(queue)
        if not tracking:
            # First completion event — start tracking
            self._queue_tracking[queue] = {
                "start_time": time.monotonic(),
                "start_completed": completed - 1,  # this call already incremented
            }
            cells[7].value = "—"
            cells[8].value = "—"
            return

        elapsed = time.monotonic() - tracking["start_time"]
        delta = completed - int(tracking["start_completed"])
        if elapsed < 0.1 or delta <= 0:
            return

        tps = delta / elapsed
        cells[7].value = f"{tps:.1f}"
        cells[7].color = Theme.Colors.INFO

        # ETA based on queued jobs remaining
        if queued > 0 and tps > 0:
            eta_s = queued / tps
            eta_str = _format_eta(eta_s)
            cells[8].value = eta_str
            # Only color as warning when showing a real ETA, not "—"
            cells[8].color = (
                Theme.Colors.WARNING if eta_str != "—" else ft.Colors.ON_SURFACE_VARIANT
            )
        else:
            cells[8].value = "—"
            cells[8].color = ft.Colors.ON_SURFACE_VARIANT

    def set_queue_totals(
        self,
        queue: str,
        queued: int,
        ongoing: int,
        completed: int,
        failed: int,
    ) -> None:
        """Set absolute values for a queue row's numeric cells."""
        cells = self._queue_cells.get(queue)
        if not cells:
            return
        # cells: [2]=queued, [3]=processing, [4]=completed, [5]=failed
        cells[2].value = str(queued)
        cells[3].value = str(ongoing)
        cells[4].value = str(completed)
        cells[5].value = str(failed)
        # Update success rate
        total = completed + failed
        if total > 0:
            rate = (completed / total) * 100
            cells[6].value = f"{rate:.1f}%"
            cells[6].color = (
                Theme.Colors.SUCCESS
                if rate >= 95
                else Theme.Colors.WARNING
                if rate >= 80
                else Theme.Colors.ERROR
            )
        else:
            cells[6].value = "N/A"
        # Reset throughput tracking with new baseline
        self._queue_tracking[queue] = {
            "start_time": time.monotonic(),
            "start_completed": completed,
        }
        cells[7].value = "—"
        cells[7].color = ft.Colors.ON_SURFACE_VARIANT
        cells[8].value = "—"
        cells[8].color = ft.Colors.ON_SURFACE_VARIANT
        # set_queue_totals is the authoritative baseline — set status here
        if ongoing > 0:
            cells[0].content.bgcolor = Theme.Colors.INFO
            cells[9].value = "Active"
            cells[9].color = Theme.Colors.INFO
        else:
            cells[0].content.bgcolor = Theme.Colors.SUCCESS
            cells[9].value = "Online"
            cells[9].color = Theme.Colors.SUCCESS
