"""Starting worker load tests and reading them back, on any worker backend.

The tasks are sent by the caller and counted from task history
(``runs``), so the CLI, the API and Overseer share one path.
"""

import asyncio
from typing import Any

from app.components.worker.constants import LoadTestTypes
from app.components.worker.events import events_redis
from app.core.config import get_load_test_queue
from app.core.log import logger
from app.services.load_test.worker import runs
from app.services.load_test.worker.analysis import AnalysisMixin
from app.services.load_test.worker.models import (
    LoadTestConfiguration,
    OrchestratorRawResult,
)
from app.services.system.jobs import JobHandle, get_job_runner

__all__ = [
    "LoadTestService",
    "quick_cpu_test",
    "quick_io_test",
    "quick_memory_test",
]

# A run this server sends in the background, started from a page or the
# API: one click or one request, so a typo is not a million jobs. The CLI,
# which sends from its own process, takes more.
MAX_BACKGROUND_TASKS = 10_000


class LoadTestService(AnalysisMixin):
    """Service for managing load test operations."""

    @staticmethod
    async def enqueue_load_test(config: LoadTestConfiguration) -> str:
        """Start a run and send every task before returning; its test id."""
        redis = await events_redis()
        test_id = await runs.start(redis, config)
        logger.info(f"Load test {test_id}: {config.num_tasks} {config.task_type}")
        await runs.send(redis, test_id, config)
        return test_id

    @staticmethod
    async def begin_load_test(config: LoadTestConfiguration) -> str:
        """Start a run and send its tasks as a background job; its test id.

        For a process that stays up (the webserver): a request returns at
        once while a large or paced run is still being sent. Raises
        ``ValueError`` past the cap or for a queue no worker reads.
        """
        from app.components.worker.registry import validate_queue_name

        if config.num_tasks > MAX_BACKGROUND_TASKS:
            raise ValueError(
                f"At most {MAX_BACKGROUND_TASKS:,} tasks from here; the CLI takes more."
            )
        if not validate_queue_name(str(config.target_queue)):
            raise ValueError(f"No queue named {config.target_queue!r}.")
        redis = await events_redis()
        test_id = await runs.start(redis, config)

        async def send(handle: JobHandle) -> None:
            await runs.send(redis, test_id, config)

        get_job_runner().start(f"worker-load-test:{test_id}", send)
        return test_id

    @staticmethod
    async def recent(limit: int) -> list[dict[str, Any]]:
        """The newest runs' counts, newest first."""
        redis = await events_redis()
        ids = await runs.recent(redis, limit)
        found = await asyncio.gather(*(runs.read(redis, i) for i in ids))
        return [run for run in found if run is not None]

    @staticmethod
    async def get_load_test_result(test_id: str) -> dict[str, Any] | None:
        """The analysed result once the run has finished, else None."""
        progress = await runs.read(await events_redis(), test_id)
        if progress is None or not progress["finished"]:
            return None
        result = OrchestratorRawResult(**progress).to_load_test_result()
        return LoadTestService._analyze_load_test_result(result).model_dump()


# Convenience functions for common load test patterns
async def quick_cpu_test(num_tasks: int = 50) -> str:
    """Quick CPU load test with sensible defaults."""
    config = LoadTestConfiguration(
        num_tasks=num_tasks,
        task_type=LoadTestTypes.CPU_INTENSIVE,
        batch_size=10,
        target_queue=get_load_test_queue(),
    )
    return await LoadTestService.enqueue_load_test(config)


async def quick_io_test(num_tasks: int = 100) -> str:
    """Quick I/O load test with sensible defaults."""
    config = LoadTestConfiguration(
        num_tasks=num_tasks,
        task_type=LoadTestTypes.IO_SIMULATION,
        batch_size=20,
        delay_ms=50,
        target_queue=get_load_test_queue(),
    )
    return await LoadTestService.enqueue_load_test(config)


async def quick_memory_test(num_tasks: int = 200) -> str:
    """Quick memory load test with sensible defaults."""
    config = LoadTestConfiguration(
        num_tasks=num_tasks,
        task_type=LoadTestTypes.MEMORY_OPERATIONS,
        batch_size=25,
        target_queue=get_load_test_queue(),
    )
    return await LoadTestService.enqueue_load_test(config)
