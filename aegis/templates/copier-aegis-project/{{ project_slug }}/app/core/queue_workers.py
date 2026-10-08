"""Worker settings per queue, validated when the settings load.

``Settings.WORKER_QUEUES`` maps a queue name to its ``QueueWorker``; any
queue not listed uses ``Settings.WORKER_QUEUE_DEFAULT``. Every worker
engine reads its concurrency from here (taskiq's max async tasks,
dramatiq's threads, arq's ``max_jobs``), so the number has one home.

Queue names are strings: queues are discovered from
``app/components/worker/queues/`` and services add their own, so the set is
open. The ones the stack ships are named in ``QueueName``. A name that
matches no queue is caught when a worker starts
(``app.components.worker.runtime.check_queues``).
"""

from pydantic import BaseModel, ConfigDict, PositiveInt

from app.core.constants import QueueName


class QueueWorker(BaseModel):
    """How the workers on one queue run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    concurrency: PositiveInt = 10  # jobs one worker process runs at once
    # The oldest waiting job past this marks the queue backed up.
    max_wait_seconds: PositiveInt = 300


# The queues the stack ships with; override any of them, or add others,
# with ``WORKER_QUEUES='{"load_test": {"concurrency": 100}}'``.
DEFAULT_QUEUES: dict[str, QueueWorker] = {
    QueueName.LOAD_TEST: QueueWorker(concurrency=50),
    QueueName.SYSTEM: QueueWorker(concurrency=15),
}


def queue_worker(
    queue: str, queues: dict[str, QueueWorker], default: QueueWorker
) -> QueueWorker:
    """``queue``'s settings, or the default when it is not listed."""
    return queues.get(queue, default)


def settings_for(queue: str) -> QueueWorker:
    """``queue``'s worker settings, read from the live settings."""
    from app.core.config import settings

    return queue_worker(queue, settings.WORKER_QUEUES, settings.WORKER_QUEUE_DEFAULT)


def concurrency_for(queue: str) -> int:
    """Jobs one worker process runs at once on ``queue``, per the settings."""
    return settings_for(queue).concurrency
