"""
Load testing service module for Dramatiq.

This module provides business logic for orchestrating and analyzing load tests,
separating concerns from API endpoints and worker tasks.
"""

import asyncio
from typing import Any

from pydantic import ValidationError

from app.components.worker.constants import LoadTestTypes
from app.components.worker.pools import enqueue_task
from app.core.config import get_load_test_queue
from app.core.log import logger
from app.services.load_test.worker.analysis import AnalysisMixin
from app.services.load_test.worker.models import (
    LoadTestConfiguration,
    OrchestratorRawResult,
)

__all__ = [
    "LoadTestConfiguration",
    "LoadTestService",
    "quick_cpu_test",
    "quick_io_test",
    "quick_memory_test",
]


class LoadTestService(AnalysisMixin):
    """Service for managing load test operations."""

    @staticmethod
    async def enqueue_load_test(config: LoadTestConfiguration) -> str:
        """
        Enqueue a load test orchestrator task.

        Only one load test can run at a time. A Redis lock prevents
        concurrent orchestrators from being enqueued.

        Args:
            config: Load test configuration

        Returns:
            Task ID for the orchestrator job

        Raises:
            RuntimeError: If another load test is already running.
        """
        import redis.asyncio as aioredis

        from app.core.config import settings

        redis_url = (
            settings.redis_url_effective
            if hasattr(settings, "redis_url_effective")
            else settings.REDIS_URL
        )
        lock_redis = aioredis.from_url(redis_url)
        lock_key = "aegis:load_test:lock"

        try:
            existing = await lock_redis.get(lock_key)
            if existing:
                raise RuntimeError(
                    f"A load test is already running (task: {existing.decode()}). "
                    "Wait for it to complete or flush Redis to clear stale locks."
                )
        finally:
            await lock_redis.aclose()

        logger.info(
            f"Enqueueing load test: {config.num_tasks} {config.task_type} tasks"
        )

        try:
            # Use Dramatiq's enqueue_task wrapper
            # Convert enum to string value — Dramatiq JSON-serializes kwargs
            msg = await enqueue_task(
                "load_test_orchestrator",
                config.target_queue,
                num_tasks=config.num_tasks,
                task_type=config.task_type.value,
                batch_size=config.batch_size,
                delay_ms=config.delay_ms,
                target_queue=config.target_queue,
            )

            # Set lock with 10-minute TTL (auto-expires if orchestrator crashes)
            lock_redis = aioredis.from_url(redis_url)
            try:
                await lock_redis.set(lock_key, msg.message_id, ex=600)
            finally:
                await lock_redis.aclose()

            logger.info(f"Load test orchestrator enqueued: {msg.message_id}")
            return str(msg.message_id)

        except Exception as e:
            cause = e.__cause__ if e.__cause__ else e
            logger.error(f"Failed to enqueue load test: {e} (cause: {cause})")
            raise

    @staticmethod
    async def get_load_test_result(
        task_id: str, target_queue: str | None = None
    ) -> dict[str, Any] | None:
        """
        Retrieve and analyze load test results.

        Args:
            task_id: The orchestrator task ID
            target_queue: Queue where the test was run

        Returns:
            Analyzed load test results or None if not found
        """
        import dramatiq
        from dramatiq.results import ResultMissing

        if target_queue is None:
            target_queue = get_load_test_queue()

        # Get result backend from broker middleware
        backend = None
        for middleware in dramatiq.get_broker().middleware:
            if isinstance(middleware, dramatiq.results.Results):
                backend = middleware.backend
                break

        if backend is None:
            logger.error("No result backend configured")
            return None

        try:
            try:
                actual_result = await asyncio.to_thread(
                    backend.get_result,
                    dramatiq.Message(
                        queue_name=target_queue,
                        actor_name="load_test_orchestrator",
                        args=(),
                        kwargs={},
                        options={},
                        message_id=task_id,
                    ),
                    block=False,
                )
            except ResultMissing:
                logger.debug(f"Result not found for task {task_id}")
                return None
            except Exception as e:
                logger.debug(f"Result not found for task {task_id}: {e}")
                return None

            # Handle different result formats
            if isinstance(actual_result, dict):
                if actual_result.get("task") == "load_test_orchestrator":
                    analyzed_result = LoadTestService._analyze_load_test_result(
                        actual_result
                    )
                    return analyzed_result.model_dump()
                elif "task_type" in actual_result and "tasks_sent" in actual_result:
                    try:
                        orchestrator_result = OrchestratorRawResult(**actual_result)
                        load_test_result = orchestrator_result.to_load_test_result()
                        analyzed_result = LoadTestService._analyze_load_test_result(
                            load_test_result
                        )
                        return analyzed_result.model_dump()
                    except ValidationError as e:
                        logger.error(f"Failed to validate orchestrator result: {e}")
                        transformed_result = (
                            LoadTestService._transform_orchestrator_result(
                                actual_result
                            )
                        )
                        analyzed_result = LoadTestService._analyze_load_test_result(
                            transformed_result
                        )
                        return analyzed_result.model_dump()

            if isinstance(actual_result, dict):
                return actual_result
            return None

        except Exception as e:
            logger.error(f"Failed to get load test result for {task_id}: {e}")
            return None


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
