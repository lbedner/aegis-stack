"""
Load test worker queue configuration for Dramatiq.

Runs the synthetic workload tasks a load test sends.
"""

from typing import Any

# Import broker to ensure it is initialised before actors are registered
import app.components.worker.broker  # noqa: F401
import dramatiq
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
