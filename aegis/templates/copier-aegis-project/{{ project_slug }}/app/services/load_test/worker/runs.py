"""A worker load test: its caller sends the tasks, task history counts them.

No job runs the test. A job sending the load would compete with that load
for the worker, hold a slot in the queue it measures, and on a long run
outlive its claim and be redelivered, sending the whole load again.

A run is a hash (its configuration, when it started, when the last task
was sent) and the list of its tasks' job ids. Progress is read on demand
from those tasks' history records, so the CLI, the API and Overseer all
see the same run, whichever started it. Once a run has finished, its
tally is kept in its hash and its tasks are not read again.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.components.worker.constants import LoadTestTypes, TaskNames
from app.components.worker.task_history import get_task_records
from app.core.config import settings
from app.services.load_test.worker.models import LoadTestConfiguration
from app.services.system.redis_keys import KeyFamily, decoded

PREFIX = "load_test:worker"
RECENT_KEY = f"{PREFIX}:recent"

TASK_FOR = {
    LoadTestTypes.CPU_INTENSIVE: TaskNames.CPU_INTENSIVE_TASK,
    LoadTestTypes.IO_SIMULATION: TaskNames.IO_SIMULATION_TASK,
    LoadTestTypes.MEMORY_OPERATIONS: TaskNames.MEMORY_OPERATIONS_TASK,
    LoadTestTypes.FAILURE_TESTING: TaskNames.FAILURE_TESTING_TASK,
}

REDIS_KEYS = (
    KeyFamily(
        f"{PREFIX}:*",
        "hash",
        "Worker load tests",
        "Each run's configuration and the job ids of the tasks it sent",
        "Worker load tests",
        columns=("Field", "Value"),
    ),
)


def _key(test_id: str) -> str:
    return f"{PREFIX}:{test_id}"


def _jobs_key(test_id: str) -> str:
    return f"{PREFIX}:{test_id}:jobs"


async def _enqueue(task_name: str, queue: str) -> str:
    """One task on the queue, by name; its job id."""
    from app.components.worker.pools import enqueue_task, job_id

    return job_id(await enqueue_task(task_name, queue))


async def start(redis: Any, config: LoadTestConfiguration) -> str:
    """Record a new run; its id. Nothing is sent yet (``send``)."""
    now = datetime.now(UTC)
    test_id = f"wlt_{now:%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}"
    ttl = settings.TASK_HISTORY_TTL_SECONDS
    await redis.hset(
        _key(test_id),
        mapping={"config": config.model_dump_json(), "started_at": now.isoformat()},
    )
    await redis.expire(_key(test_id), ttl)
    await redis.zadd(RECENT_KEY, {test_id: now.timestamp()})
    await redis.expire(RECENT_KEY, ttl)
    return test_id


async def send(redis: Any, test_id: str, config: LoadTestConfiguration) -> None:
    """Send the run's tasks in batches, each batch at once, recording its
    job ids. A send that fails is recorded on the run, then raised."""
    task_name = TASK_FOR[config.task_type]
    queue = str(config.target_queue)
    try:
        for first in range(0, config.num_tasks, config.batch_size):
            size = min(config.batch_size, config.num_tasks - first)
            ids = await asyncio.gather(
                *(_enqueue(task_name, queue) for _ in range(size))
            )
            await redis.rpush(_jobs_key(test_id), *ids)
            await redis.expire(_jobs_key(test_id), settings.TASK_HISTORY_TTL_SECONDS)
            if config.delay_ms and first + size < config.num_tasks:
                await asyncio.sleep(config.delay_ms / 1000)
    except Exception as exc:
        await redis.hset(_key(test_id), mapping={"error": f"Sending stopped: {exc}"})
        raise
    await redis.hset(_key(test_id), mapping={"sent_at": datetime.now(UTC).isoformat()})


async def read(redis: Any, test_id: str) -> dict[str, Any] | None:
    """The run as it stands, or None if there is no such run (or it expired)."""
    run = {decoded(k): decoded(v) for k, v in (await redis.hgetall(_key(test_id))).items()}
    if not run:
        return None
    if "tally" in run:
        return json.loads(run["tally"])
    ids = [decoded(i) for i in await redis.lrange(_jobs_key(test_id), 0, -1)]
    progress = tally(test_id, run, sent=len(ids), tasks=await get_task_records(redis, ids))
    if progress["finished"]:
        await redis.hset(_key(test_id), mapping={"tally": json.dumps(progress)})
        await redis.delete(_jobs_key(test_id))
    return progress


async def recent(redis: Any, limit: int) -> list[str]:
    """Run ids, newest first."""
    return [decoded(i) for i in await redis.zrevrange(RECENT_KEY, 0, limit - 1)]


def tally(
    test_id: str, run: dict[str, str], sent: int, tasks: list[dict[str, str]]
) -> dict[str, Any]:
    """A run's counts and timing from its tasks' records.

    Finished once every task was sent and every sent task has finished, or
    once sending stopped on an error. The duration runs from the start to
    the last task to finish (so far).
    """
    config = LoadTestConfiguration.model_validate_json(run["config"])
    completed = sum(t.get("status") == "completed" for t in tasks)
    failed = sum(t.get("status") == "failed" for t in tasks)
    started = datetime.fromisoformat(run["started_at"])
    ends = [datetime.fromisoformat(t["finished_at"]) for t in tasks if "finished_at" in t]
    end = max(ends, default=started)
    duration = (end - started).total_seconds()
    return {
        "test_id": test_id,
        "task_type": config.task_type.value,
        "tasks_planned": config.num_tasks,
        "tasks_sent": sent,
        "tasks_completed": completed,
        "tasks_failed": failed,
        "batch_size": config.batch_size,
        "delay_ms": config.delay_ms,
        "target_queue": config.target_queue,
        "start_time": started.isoformat(),
        "end_time": end.isoformat(),
        "total_duration_seconds": round(duration, 2),
        "overall_throughput_per_second": round(completed / duration, 2)
        if duration > 0
        else 0,
        "completion_percentage": round(completed / max(sent, 1) * 100, 1),
        "failure_rate_percent": round(failed / max(sent, 1) * 100, 1),
        "error": run.get("error"),
        "sending": "sent_at" not in run and "error" not in run,
        "finished": "error" in run or ("sent_at" in run and completed + failed >= sent),
    }

