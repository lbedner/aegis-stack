"""
Load testing service module.

This module provides business logic for orchestrating and analyzing load tests,
separating concerns from API endpoints and worker tasks.
"""

from typing import Any

from pydantic import ValidationError

from app.components.worker.constants import LoadTestTypes
from app.components.worker.pools import get_queue_pool
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
        from app.components.worker.pools import get_queue_pool

        logger.info(
            f"Enqueueing load test: {config.num_tasks} {config.task_type} tasks"
        )

        # Get appropriate queue pool
        pool, queue_name = await get_queue_pool(config.target_queue)

        try:
            # Enqueue the orchestrator task with enum preserved
            job = await pool.enqueue_job(
                "load_test_orchestrator",
                _queue_name=queue_name,
                num_tasks=config.num_tasks,
                task_type=config.task_type,  # Preserve enum instead of serializing
                batch_size=config.batch_size,
                delay_ms=config.delay_ms,
                target_queue=config.target_queue,
            )

            await pool.aclose()

            if job is None:
                raise RuntimeError("Failed to enqueue job - returned None")

            logger.info(f"Load test orchestrator enqueued: {job.job_id}")
            return str(job.job_id)

        except Exception as e:
            await pool.aclose()
            logger.error(f"Failed to enqueue load test: {e}")
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
        # Use configured load test queue if not specified
        if target_queue is None:
            target_queue = get_load_test_queue()

        pool = None
        try:
            pool, _ = await get_queue_pool(target_queue)
            # Check if result exists
            result_key = f"arq:result:{task_id}"
            result_exists = await pool.exists(result_key)

            if not result_exists:
                return None

            # Get the result data
            result_data = await pool.get(result_key)
            if not result_data:
                return None

            # Deserialize the result
            import pickle

            result = pickle.loads(result_data)

            # Handle different result formats
            if isinstance(result, Exception):
                # Task failed completely
                return {
                    "task": "load_test_orchestrator",
                    "status": "failed",
                    "error": str(result),
                    "test_id": task_id,
                }
            elif isinstance(result, dict):
                # Check if it's a direct load test result
                if result.get("task") == "load_test_orchestrator":
                    analyzed_result = LoadTestService._analyze_load_test_result(result)
                    return analyzed_result.model_dump()
                # Check if it's an arq job result with embedded data
                elif "r" in result and isinstance(result["r"], dict):
                    # Extract the actual result
                    actual_result = result["r"]
                    # Check if this looks like a load test orchestrator result
                    if (
                        "test_id" in actual_result
                        and "task_type" in actual_result
                        and "tasks_sent" in actual_result
                    ):
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
                            # Fall back to manual transformation if validation fails
                            transformed_result = (
                                LoadTestService._transform_orchestrator_result(
                                    actual_result
                                )
                            )
                            analyzed_result = LoadTestService._analyze_load_test_result(
                                transformed_result
                            )
                            return analyzed_result.model_dump()
                    elif actual_result.get("task") == "load_test_orchestrator":
                        analyzed_result = LoadTestService._analyze_load_test_result(
                            actual_result
                        )
                        return analyzed_result.model_dump()
                elif "r" in result and isinstance(result["r"], Exception):
                    # Task timed out or failed
                    return {
                        "task": "load_test_orchestrator",
                        "status": "timed_out",
                        "error": str(result["r"]),
                        "test_id": task_id,
                        "partial_info": (
                            "Task may have completed work but timed out at "
                            "orchestrator level"
                        ),
                    }

            # result is already dict[str, Any] at this point
            return result  # type: ignore[no-any-return]

        except Exception as e:
            logger.error(f"Failed to get load test result for {task_id}: {e}")
            return None
        finally:
            if pool is not None:
                await pool.aclose()


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
