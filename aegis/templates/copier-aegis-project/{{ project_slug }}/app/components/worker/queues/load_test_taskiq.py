"""
Load test worker queue configuration for TaskIQ.

Runs the synthetic workload tasks a load test sends.
"""

from typing import Any

from taskiq_redis import RedisAsyncResultBackend

from app.components.worker.broker import PausableRedisStreamBroker
from app.components.worker.middleware import EventPublishMiddleware
from app.core.config import settings
from app.core.constants import QueueName
from app.services.load_test_workloads import (
    run_cpu_intensive,
    run_failure_testing,
    run_io_simulation,
    run_memory_operations,
)

# Use redis_url_effective for Docker vs local auto-detection
redis_url = settings.redis_url_effective

# Create the broker with Redis backend (using streams for acknowledgement support)
# Use unique queue_name to ensure workers don't consume from each other's streams
broker = (
    # ``consumer_id="0"``: a group created at "$" starts at the tail, so
    # anything enqueued before the worker's first successful start is
    # skipped forever - the job sits queued and no worker ever sees it.
    # Starting at "0" hands a new group the backlog it was created to work.
    PausableRedisStreamBroker(
        url=redis_url,
        queue_name="taskiq:load_test",
        consumer_id="0",
        # One job per read: taskiq reads each time a slot frees, so a
        # bigger read claims jobs that only wait (claimed jobs are this
        # worker's alone, and only running ones keep their claim alive).
        xread_count=1,
    )
    .with_result_backend(
        RedisAsyncResultBackend(redis_url=redis_url, result_ex_time=60)
    )
    .with_middlewares(EventPublishMiddleware().set_queue_name(QueueName.LOAD_TEST))
)


@broker.task
async def cpu_intensive_task() -> dict[str, Any]:
    """Stress-test CPU with synthetic computation.

    Runs a configurable burst of mathematical operations (prime sieve,
    matrix multiply) to measure worker throughput under CPU pressure.
    """
    return await run_cpu_intensive()


@broker.task
async def io_simulation_task() -> dict[str, Any]:
    """Simulate I/O-bound workloads with async sleep.

    Mimics network calls, file reads, and database queries using
    randomised async delays to test worker concurrency handling.
    """
    return await run_io_simulation()


@broker.task
async def memory_operations_task() -> dict[str, Any]:
    """Exercise memory allocation and garbage collection.

    Allocates and releases large byte buffers and data structures to
    test worker memory behaviour under sustained allocation pressure.
    """
    return await run_memory_operations()


@broker.task
async def failure_testing_task() -> dict[str, Any]:
    """Randomly raise exceptions for error-handling validation.

    Fails with a configurable probability to verify retry logic,
    dead-letter routing, and failure metric collection.
    """
    return await run_failure_testing()
