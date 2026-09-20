"""One task's life, written down and read back.

Split by what a caller is doing: ``record`` while the task runs,
``read`` for the dashboard and the API, ``prune`` when history should
expire, ``shared`` for the keys and the name resolution both sides
need.
"""

from app.components.worker.task_history.prune import (
    cleanup_old_tasks,
    clear_queue_history,
)
from app.components.worker.task_history.read import (
    get_queue_stats,
    get_task_record,
    list_tasks_by_queue,
)
from app.components.worker.task_history.record import (
    record_task_enqueued,
    record_task_enqueued_sync,
    record_task_finished,
    record_task_finished_sync,
    record_task_started,
    record_task_started_sync,
)
from app.components.worker.task_history.shared import (
    resolve_arq_task_name,
    resolve_task_docstring,
)

__all__ = [
    "cleanup_old_tasks",
    "clear_queue_history",
    "get_queue_stats",
    "get_task_record",
    "list_tasks_by_queue",
    "record_task_enqueued",
    "record_task_enqueued_sync",
    "record_task_finished",
    "record_task_finished_sync",
    "record_task_started",
    "record_task_started_sync",
    "resolve_arq_task_name",
    "resolve_task_docstring",
]
