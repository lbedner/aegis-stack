"""
Load testing service module for TaskIQ.

This module provides business logic for orchestrating and analyzing load tests,
separating concerns from API endpoints and worker tasks.
"""

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

        Args:
            config: Load test configuration

        Returns:
            Task ID for the orchestrator job
        """
        logger.info(
            f"Enqueueing load test: {config.num_tasks} {config.task_type} tasks"
        )

        try:
            # Use TaskIQ's enqueue_task wrapper
            task_handle = await enqueue_task(
                "load_test_orchestrator",
                config.target_queue,
                num_tasks=config.num_tasks,
                task_type=config.task_type,
                batch_size=config.batch_size,
                delay_ms=config.delay_ms,
                target_queue=config.target_queue,
            )

            logger.info(f"Load test orchestrator enqueued: {task_handle.task_id}")
            return str(task_handle.task_id)

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
            target_queue: Queue where the test was run (defaults to configured
                load_test queue)

        Returns:
            Analyzed load test results or None if not found
        """
        from taskiq_redis import RedisAsyncResultBackend

        from app.core.config import settings

        # Use configured load test queue if not specified
        if target_queue is None:
            target_queue = get_load_test_queue()

        # Use fresh result backend to avoid cached connections that cause
        # 'Event loop is closed' errors when CLI exits
        redis_url = (
            settings.redis_url_effective
            if hasattr(settings, "redis_url_effective")
            else settings.REDIS_URL
        )
        result_backend = RedisAsyncResultBackend(redis_url=redis_url)

        try:
            try:
                result = await result_backend.get_result(task_id)
            except Exception as e:
                logger.debug(f"Result not found for task {task_id}: {e}")
                return None

            # Handle error results
            if result.is_err:
                return {
                    "task": "load_test_orchestrator",
                    "status": "failed",
                    "error": str(result.error),
                    "test_id": task_id,
                }

            # Get the actual return value
            actual_result = result.return_value

            # Handle different result formats
            if isinstance(actual_result, dict):
                # Check if it's a direct load test result
                if actual_result.get("task") == "load_test_orchestrator":
                    analyzed_result = LoadTestService._analyze_load_test_result(
                        actual_result
                    )
                    return analyzed_result.model_dump()
                # Check if it looks like a load test orchestrator result
                # Note: test_id is optional for TaskIQ (task doesn't know its own ID)
                elif "task_type" in actual_result and "tasks_sent" in actual_result:
                    try:
                        # Validate and transform using Pydantic models
                        orchestrator_result = OrchestratorRawResult(**actual_result)
                        load_test_result = orchestrator_result.to_load_test_result()
                        analyzed_result = LoadTestService._analyze_load_test_result(
                            load_test_result
                        )
                        return analyzed_result.model_dump()
                    except ValidationError as e:
                        logger.error(f"Failed to validate orchestrator result: {e}")
                        # Fall back to manual transformation
                        transformed_result = (
                            LoadTestService._transform_orchestrator_result(
                                actual_result
                            )
                        )
                        analyzed_result = LoadTestService._analyze_load_test_result(
                            transformed_result
                        )
                        return analyzed_result.model_dump()

            # Return result as-is if it's already a dict
            if isinstance(actual_result, dict):
                return actual_result
            return None

        except Exception as e:
            logger.error(f"Failed to get load test result for {task_id}: {e}")
            return None
        finally:
            # Always close the result backend to prevent connection leaks
            await result_backend.shutdown()


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
