"""
Load test worker queue configuration.

Handles load testing orchestration and synthetic workload tasks using native arq
patterns.
"""

from arq.connections import RedisSettings

from app.components.worker import arq_hooks
from app.components.worker.tasks.load_tasks import (
    cpu_intensive_task,
    failure_testing_task,
    io_simulation_task,
    memory_operations_task,
)
from app.components.worker.tasks.system_tasks import (
    load_test_orchestrator,
)
from app.core.config import settings
from app.core.queue_workers import concurrency_for


class WorkerSettings:
    """Load testing worker configuration."""

    # Human-readable description
    description = "Load testing and performance testing"

    # Task functions for this queue
    functions = [
        # Load test orchestrator
        load_test_orchestrator,
        # Synthetic workload tasks
        cpu_intensive_task,
        io_simulation_task,
        memory_operations_task,
        failure_testing_task,
    ]

    # arq configuration with improved connection settings
    base_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    redis_settings = RedisSettings(
        host=base_settings.host,
        port=base_settings.port,
        database=base_settings.database,
        password=base_settings.password,
        conn_timeout=settings.REDIS_CONN_TIMEOUT,
        conn_retries=settings.REDIS_CONN_RETRIES,
        conn_retry_delay=settings.REDIS_CONN_RETRY_DELAY,
    )
    queue_name = "arq:queue:load_test"
    max_jobs = concurrency_for("load_test")  # Settings.WORKER_QUEUES
    job_timeout = 60  # Quick tasks
    keep_result = 60  # Short TTL — load test results are fire-and-forget
    max_tries = settings.WORKER_MAX_TRIES
    health_check_interval = settings.WORKER_HEALTH_CHECK_INTERVAL

    on_startup, on_shutdown, on_job_start, after_job_end = arq_hooks.for_queue(
        "load_test", max_jobs
    )
