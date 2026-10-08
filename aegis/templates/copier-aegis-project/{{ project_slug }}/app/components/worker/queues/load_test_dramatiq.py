"""
Load test worker queue configuration for Dramatiq.

Handles load testing orchestration and synthetic workload tasks using Dramatiq patterns.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

# Import broker to ensure it is initialised before actors are registered
import app.components.worker.broker  # noqa: F401
import dramatiq
import redis.asyncio as aioredis
from app.components.worker.events import publish_event
from app.core.config import settings
from app.core.constants import QueueName
from app.core.log import logger
from app.services.load_test_workloads import (
    run_cpu_intensive,
    run_failure_testing,
    run_io_simulation,
    run_memory_operations,
)

# Use redis_url_effective for Docker vs local auto-detection
redis_url = settings.redis_url_effective


@dramatiq.actor(queue_name=QueueName.LOAD_TEST, store_results=True)
async def cpu_intensive_task() -> dict[str, Any]:
    """Stress-test CPU with synthetic computation.

    Runs a configurable burst of mathematical operations (prime sieve,
    matrix multiply) to measure worker throughput under CPU pressure.
    """
    return await run_cpu_intensive()


@dramatiq.actor(queue_name=QueueName.LOAD_TEST, store_results=True)
async def io_simulation_task() -> dict[str, Any]:
    """Simulate I/O-bound workloads with async sleep.

    Mimics network calls, file reads, and database queries using
    randomised async delays to test worker concurrency handling.
    """
    return await run_io_simulation()


@dramatiq.actor(queue_name=QueueName.LOAD_TEST, store_results=True)
async def memory_operations_task() -> dict[str, Any]:
    """Exercise memory allocation and garbage collection.

    Allocates and releases large byte buffers and data structures to
    test worker memory behaviour under sustained allocation pressure.
    """
    return await run_memory_operations()


@dramatiq.actor(queue_name=QueueName.LOAD_TEST, store_results=True)
async def failure_testing_task() -> dict[str, Any]:
    """Randomly raise exceptions for error-handling validation.

    Fails with a configurable probability to verify retry logic,
    dead-letter routing, and failure metric collection.
    """
    return await run_failure_testing()


def _get_task_by_type(task_type: str) -> Any:
    """Get the task function by type string."""
    task_map = {
        "cpu_intensive": cpu_intensive_task,
        "cpu": cpu_intensive_task,
        "io_simulation": io_simulation_task,
        "io": io_simulation_task,
        "memory_operations": memory_operations_task,
        "memory": memory_operations_task,
        "failure_testing": failure_testing_task,
        "failure": failure_testing_task,
    }
    return task_map.get(task_type, io_simulation_task)


@dramatiq.actor(queue_name=QueueName.LOAD_TEST, store_results=True)
async def load_test_orchestrator(
    num_tasks: int = 100,
    task_type: str = "io",
    batch_size: int = 10,
    delay_ms: int = 0,
    target_queue: str | None = None,
) -> dict[str, Any]:
    """
    Load test orchestrator that spawns many tasks to measure queue throughput.

    Enqueues all child tasks and returns immediately. Completion tracking is
    handled externally via SSE events streamed to the dashboard in real time.

    Args:
        num_tasks: Number of tasks to spawn for the load test
        task_type: Type of task (cpu, io, memory, failure)
        batch_size: How many tasks to send concurrently per batch
        delay_ms: Delay between batches in milliseconds
        target_queue: Which queue to test (kept for API compat)

    Returns:
        Enqueue summary with task IDs and timing
    """
    start_time = datetime.now(UTC)

    logger.info(
        f"Starting load test orchestrator: {num_tasks} {task_type} tasks "
        f"(batches of {batch_size})"
    )

    # Get the task function to spawn
    task_func = _get_task_by_type(task_type)

    tasks_sent = 0
    message_ids: list[str] = []

    # Redis client for publishing enqueue events to the dashboard
    events_redis = aioredis.from_url(redis_url)

    try:
        # Spawn tasks in batches
        for batch_start in range(0, num_tasks, batch_size):
            batch_end = min(batch_start + batch_size, num_tasks)
            current_batch_size = batch_end - batch_start

            # Enqueue batch of tasks using Dramatiq's send()
            for _ in range(current_batch_size):
                msg = await asyncio.to_thread(task_func.send)
                message_ids.append(msg.message_id)
                await publish_event(
                    events_redis,
                    "job.enqueued",
                    QueueName.LOAD_TEST,
                    {"job_id": msg.message_id, "task": task_type},
                )

            tasks_sent += current_batch_size
            logger.debug(
                f"Sent batch: {current_batch_size} tasks "
                f"(total: {tasks_sent}/{num_tasks})"
            )

            # Add configurable delay between batches if specified
            if delay_ms > 0 and batch_end < num_tasks:
                await asyncio.sleep(delay_ms / 1000.0)

        end_time = datetime.now(UTC)
        total_duration = (end_time - start_time).total_seconds()

        logger.info(
            f"All {tasks_sent} tasks enqueued in {total_duration:.1f}s "
            f"({tasks_sent / total_duration:.0f} enqueues/sec)"
        )

        return {
            "task_type": task_type,
            "tasks_sent": tasks_sent,
            "task_ids": message_ids[:10],
            "batch_size": batch_size,
            "delay_ms": delay_ms,
            "target_queue": target_queue,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "enqueue_duration_seconds": round(total_duration, 2),
            "enqueue_throughput_per_second": round(tasks_sent / total_duration, 2)
            if total_duration > 0
            else 0,
        }

    except Exception as e:
        logger.error(f"Load test orchestrator failed: {e}")
        return {"error": str(e), "tasks_sent": tasks_sent}
    finally:
        await events_redis.aclose()
        # Release the load test lock
        try:
            lock_redis = aioredis.from_url(redis_url)
            await lock_redis.delete("aegis:load_test:lock")
            await lock_redis.aclose()
        except Exception:
            pass
