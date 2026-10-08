"""Worker load-test endpoints, the same on every worker backend.

A run is sent by this server in the background (``LoadTestService``) and
read back from task history, so nothing here depends on the backend. Each
backend's worker router includes this one under its ``/tasks`` prefix.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from app.components.backend.api.models import LoadTestRequest, TaskResponse
from app.components.worker.constants import LoadTestTypes
from app.core.config import get_default_queue
from app.core.constants import QueueName
from app.core.log import logger
from app.services.load_test import LoadTestConfiguration, LoadTestService

router = APIRouter()

RESULT_PATH = "/api/v1/tasks/load-test-result/{test_id}"


@router.post("/load-test", response_model=TaskResponse)
async def start_load_test(load_test_config: LoadTestRequest) -> TaskResponse:
    """Start a load test that measures queue throughput; read it back from
    ``/tasks/load-test-result/{task_id}``."""
    logger.info(
        f"Starting load test: {load_test_config.num_tasks} "
        f"{load_test_config.task_type} tasks"
    )
    config = LoadTestConfiguration(
        num_tasks=load_test_config.num_tasks,
        task_type=load_test_config.task_type,
        batch_size=load_test_config.batch_size,
        delay_ms=load_test_config.delay_ms,
        target_queue=load_test_config.target_queue,
    )
    try:
        test_id = await LoadTestService.begin_load_test(config)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": "load_test_refused", "message": str(e)},
        ) from None
    except Exception as e:
        logger.error(f"Failed to start load test: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "load_test_failed",
                "message": f"Failed to start load test: {str(e)}",
            },
        ) from e
    return TaskResponse(
        task_id=test_id,
        task_name="worker_load_test",
        queue_type=load_test_config.target_queue,
        queued_at=datetime.now(),
        estimated_start=None,
        message=(
            f"Load test '{load_test_config.task_type}' started: "
            f"{load_test_config.num_tasks} tasks to the "
            f"{load_test_config.target_queue} queue. Results: "
            + RESULT_PATH.format(test_id=test_id)
        ),
    )


@router.post("/examples/load-test-small", response_model=TaskResponse)
async def enqueue_small_load_test() -> TaskResponse:
    """Example: Small load test with 50 CPU tasks."""
    load_test_config = LoadTestRequest(
        num_tasks=50,
        task_type=LoadTestTypes.CPU_INTENSIVE,
        batch_size=10,
        delay_ms=0,
        target_queue=get_default_queue(),
    )
    return await start_load_test(load_test_config)


@router.post("/examples/load-test-medium", response_model=TaskResponse)
async def enqueue_medium_load_test() -> TaskResponse:
    """Example: Medium load test with 200 I/O tasks."""
    load_test_config = LoadTestRequest(
        num_tasks=200,
        task_type=LoadTestTypes.IO_SIMULATION,
        batch_size=20,
        delay_ms=50,
        target_queue=get_default_queue(),
    )
    return await start_load_test(load_test_config)


@router.post("/examples/load-test-large", response_model=TaskResponse)
async def enqueue_large_load_test() -> TaskResponse:
    """Example: Large load test with 1000 memory tasks."""
    load_test_config = LoadTestRequest(
        num_tasks=1000,
        task_type=LoadTestTypes.MEMORY_OPERATIONS,
        batch_size=50,
        delay_ms=0,
        target_queue=get_default_queue(),
    )
    return await start_load_test(load_test_config)


@router.get("/load-test-result/{task_id}")
async def get_load_test_result(task_id: str) -> dict[str, Any]:
    """Get enhanced load test results with analysis and verification."""
    try:
        result = await LoadTestService.get_load_test_result(task_id)
    except Exception as e:
        logger.error(f"Failed to get load test result for {task_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "result_retrieval_failed",
                "message": f"Failed to retrieve load test results: {str(e)}",
            },
        ) from e
    if not result:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "load_test_not_found",
                "message": f"Load test {task_id} is still running, or there is no such run",
                "task_id": task_id,
            },
        )
    return result


@router.get("/load-test-types")
async def get_load_test_types() -> dict[str, Any]:
    """Get information about available load test types."""
    return {
        "available_test_types": {
            test_type: LoadTestService.get_test_type_info(test_type)
            for test_type in LoadTestTypes
        },
        "usage_examples": {
            "quick_cpu_test": {
                "description": "Quick CPU test with 50 tasks",
                "parameters": {
                    "num_tasks": 50,
                    "task_type": "cpu_intensive",
                    "batch_size": 10,
                    "target_queue": QueueName.LOAD_TEST,
                },
            },
            "io_stress_test": {
                "description": "I/O stress test with concurrent operations",
                "parameters": {
                    "num_tasks": 200,
                    "task_type": "io_simulation",
                    "batch_size": 20,
                    "delay_ms": 50,
                    "target_queue": QueueName.LOAD_TEST,
                },
            },
            "memory_load_test": {
                "description": "Memory allocation test with GC pressure",
                "parameters": {
                    "num_tasks": 500,
                    "task_type": "memory_operations",
                    "batch_size": 25,
                    "target_queue": QueueName.LOAD_TEST,
                },
            },
        },
    }
