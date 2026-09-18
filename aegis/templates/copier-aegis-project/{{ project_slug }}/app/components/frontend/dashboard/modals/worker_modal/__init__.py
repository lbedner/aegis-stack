"""The worker detail modal, split by what each part shows.

``worker_modal.py`` was thirteen hundred lines holding four controls
and the queue-row helpers two of them share. Each is now its own
module; this re-exports the names that were importable before, so
nothing outside the package had to change.
"""

from .dialog import WorkerDetailDialog
from .lifecycle_tab import WorkerLifecycleTab
from .overview_section import OverviewSection
from .queue_health_section import QueueHealthSection
from .queue_rows import _compute_queue_values, _format_eta

__all__ = [
    "OverviewSection",
    "QueueHealthSection",
    "WorkerDetailDialog",
    "WorkerLifecycleTab",
    "_compute_queue_values",
    "_format_eta",
]
