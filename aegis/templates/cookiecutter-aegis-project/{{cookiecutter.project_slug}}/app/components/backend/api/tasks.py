"""
Background tasks API endpoints.

Provides endpoints for enqueueing and monitoring background tasks
using the arq worker infrastructure.
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from app.components.backend.api.models import (
    LoadTestRequest,
    TaskListResponse,
    TaskRequest,
    TaskResponse,
    TaskResultResponse,
    TaskStatusResponse,
)
from app.components.worker.pools import get_queue_pool
from app.components.worker.tasks import get_task_by_name, list_available_tasks
from app.core.config import get_default_queue
from app.core.log import logger

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/", response_model=TaskListResponse)
async def list_tasks() -> TaskListResponse:
    """
    Get list of all available background tasks.

    Returns:
        List of available task names organized by functional queue
    """
    available_tasks = list_available_tasks()

    # Import here to avoid circular imports
    from app.components.worker.tasks import get_queue_for_task

    # Organize tasks by their appropriate functional queues
    from app.core.config import settings

    queues: dict[str, list[str]] = {queue_type: [] for queue_type in settings.WORKER_QUEUES.keys()}

    for task in available_tasks:
        queue_type = get_queue_for_task(task)
        queues[queue_type].append(task)

    return TaskListResponse(
        available_tasks=available_tasks,
        total_count=len(available_tasks),
        queues=queues,
    )


@router.post("/enqueue", response_model=TaskResponse)
async def enqueue_task(task_request: TaskRequest) -> TaskResponse:
    """
    Enqueue a background task for processing.

    Args:
        task_request: Task details including name, priority, and arguments

    Returns:
        Task enqueue confirmation with task ID

    Raises:
        HTTPException: If task name is invalid or enqueueing fails
    """
    logger.info(
        f"Enqueueing task: {task_request.task_name} (queue: {task_request.queue_type})"
    )

    # Validate task exists
    task_func = get_task_by_name(task_request.task_name)
    if not task_func:
        available_tasks = list_available_tasks()
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_task_name",
                "message": f"Task '{task_request.task_name}' not found",
                "available_tasks": available_tasks,
            },
        )

    # Validate queue type
    from app.core.config import settings

    if task_request.queue_type not in settings.WORKER_QUEUES:
        available_queues = list(settings.WORKER_QUEUES.keys())
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_queue_type",
                "message": f"Queue type must be one of: {available_queues}",
            },
        )

    try:
        # Get appropriate queue pool and queue name
        pool, queue_name = await get_queue_pool(task_request.queue_type)

        # Enqueue the task with the specific queue name
        job = await pool.enqueue_job(
            task_request.task_name,
            *task_request.args,
            _queue_name=queue_name,
            _defer_by=task_request.delay_seconds,
            **task_request.kwargs,
        )

        queued_at = datetime.now()
        estimated_start = None
        if task_request.delay_seconds:
            estimated_start = queued_at + timedelta(seconds=task_request.delay_seconds)

        await pool.aclose()  # Use aclose() instead of close()

        if job is None:
            raise HTTPException(status_code=500, detail="Failed to enqueue task")

        logger.info(f"✅ Task enqueued: {job.job_id} ({task_request.task_name})")

        return TaskResponse(
            task_id=job.job_id,
            task_name=task_request.task_name,
            queue_type=task_request.queue_type,
            queued_at=queued_at,
            estimated_start=estimated_start,
            message=(
                f"Task '{task_request.task_name}' enqueued to "
                f"{task_request.queue_type} queue"
            ),
        )

    except Exception as e:
        logger.error(f"Failed to enqueue task {task_request.task_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "enqueue_failed",
                "message": f"Failed to enqueue task: {str(e)}",
            },
        )


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """
    Get the status of a background task.

    Args:
        task_id: The task ID returned when enqueueing

    Returns:
        Task status information
    """
    try:
        # Get Redis pool to check job status (use default queue for status checks)
        pool, _ = await get_queue_pool(get_default_queue())

        # Check if job exists in Redis using arq's key patterns
        job_key = f"arq:job:{task_id}"
        result_key = f"arq:result:{task_id}"

        # Check if job data exists
        job_exists = await pool.exists(job_key)
        result_exists = await pool.exists(result_key)

        if not job_exists and not result_exists:
            await pool.aclose()
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "task_not_found",
                    "message": f"Task {task_id} not found",
                },
            )

        # Determine status based on what exists in Redis
        if result_exists:
            # Task completed (successfully or failed)
            result_data = await pool.get(result_key)
            if result_data:
                try:
                    import pickle

                    result = pickle.loads(result_data)
                    if isinstance(result, dict) and result.get("error"):
                        status = "failed"
                        error = result.get("error")
                    else:
                        status = "complete"
                        error = None
                except Exception:
                    status = "complete"
                    error = None
            else:
                status = "complete"
                error = None
        elif job_exists:
            # Job is queued or in progress
            # We can't easily distinguish queued vs in_progress without more
            # Redis inspection
            status = "queued"
            error = None
        else:
            status = "unknown"
            error = None

        await pool.aclose()

        return TaskStatusResponse(
            task_id=task_id, 
            status=status, 
            result_available=result_exists, 
            error=error,
            enqueue_time=None,
            start_time=None,
            finish_time=None
        )

    except Exception as e:
        logger.error(f"Failed to get task status for {task_id}: {e}")
        raise HTTPException(
            status_code=500, detail={"error": "status_check_failed", "message": str(e)}
        )


@router.get("/result/{task_id}", response_model=TaskResultResponse)
async def get_task_result(task_id: str) -> TaskResultResponse:
    """
    Get the result of a completed background task.

    Args:
        task_id: The task ID returned when enqueueing

    Returns:
        Task result data
    """
    try:
        # Get Redis pool to check job result (use default queue for result checks)
        pool, _ = await get_queue_pool(get_default_queue())

        # Check if result exists
        result_key = f"arq:result:{task_id}"
        result_exists = await pool.exists(result_key)

        if not result_exists:
            # Check if job exists at all
            job_key = f"arq:job:{task_id}"
            job_exists = await pool.exists(job_key)

            await pool.aclose()

            if not job_exists:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": "task_not_found",
                        "message": f"Task {task_id} not found",
                    },
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "task_not_completed",
                        "message": f"Task {task_id} has not completed yet",
                        "current_status": "queued or in_progress",
                    },
                )

        # Get the result data
        result_data = await pool.get(result_key)
        await pool.aclose()

        if not result_data:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "result_data_missing",
                    "message": "Result data is missing",
                },
            )

        # Deserialize the result
        try:
            import pickle

            result = pickle.loads(result_data)

            # Handle error results (failed tasks store exception objects)
            if isinstance(result, Exception):
                result_data = {
                    "error_type": type(result).__name__,
                    "error_message": str(result),
                    "task_failed": True,
                }
                task_status = "failed"
            else:
                # For successful results, ensure they're JSON-serializable
                try:
                    import json

                    json.dumps(result)  # Test if it's serializable
                    result_data = result
                    task_status = "completed"
                except (TypeError, ValueError):
                    # If not serializable, convert to string representation
                    result_data = {
                        "result_type": type(result).__name__,
                        "result_str": str(result),
                        "note": "Result was not JSON-serializable, converted to string",
                    }
                    task_status = "completed"

            return TaskResultResponse(
                task_id=task_id, 
                status=task_status, 
                result=result_data,
                enqueue_time=None,
                start_time=None,
                finish_time=None
            )

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "result_deserialization_failed",
                    "message": f"Failed to deserialize result: {str(e)}",
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task result for {task_id}: {e}")
        raise HTTPException(
            status_code=500, detail={"error": "result_fetch_failed", "message": str(e)}
        )


@router.post("/load-test", response_model=TaskResponse)
async def start_load_test(load_test_config: LoadTestRequest) -> TaskResponse:
    """
    Start a comprehensive load test that measures queue throughput.

    This orchestrates many lightweight tasks to stress test the queue
    infrastructure and provide meaningful performance metrics including
    task-type-specific verification and analysis.

    Args:
        load_test_config: Load test configuration with parameters

    Returns:
        Task response with load test orchestrator job ID
    """
    from app.components.worker.constants import LoadTestTypes, TaskNames
    from app.services.load_test import (
        LoadTestConfiguration,
        LoadTestService,
    )

    logger.info(
        f"🚀 Starting load test: {load_test_config.num_tasks} "
        f"{load_test_config.task_type} tasks"
    )

    # Convert to service layer configuration
    # Validate task type against known types
    valid_types = [
        LoadTestTypes.CPU_INTENSIVE,
        LoadTestTypes.IO_SIMULATION,
        LoadTestTypes.MEMORY_OPERATIONS,
        LoadTestTypes.FAILURE_TESTING,
    ]
    if load_test_config.task_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_task_type",
                "message": f"Invalid task type: {load_test_config.task_type}",
                "valid_types": valid_types,
            },
        )

    config = LoadTestConfiguration(
        num_tasks=load_test_config.num_tasks,
        task_type=load_test_config.task_type,
        batch_size=load_test_config.batch_size,
        delay_ms=load_test_config.delay_ms,
        target_queue=load_test_config.target_queue,
    )

    try:
        task_id = await LoadTestService.enqueue_load_test(config)

        return TaskResponse(
            task_id=task_id,
            task_name=TaskNames.LOAD_TEST_ORCHESTRATOR,
            queue_type=load_test_config.target_queue,
            queued_at=datetime.now(),
            estimated_start=None,
            message=(
                f"Load test '{load_test_config.task_type}' enqueued: "
                f"{load_test_config.num_tasks} tasks to "
                f"{load_test_config.target_queue} queue"
            ),
        )

    except Exception as e:
        logger.error(f"Failed to enqueue load test: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "load_test_failed",
                "message": f"Failed to start load test: {str(e)}",
            },
        )


@router.post("/examples/load-test-small", response_model=TaskResponse)
async def enqueue_small_load_test() -> TaskResponse:
    """
    Example: Small load test with 50 CPU tasks.

    Good for testing basic queue functionality and getting quick results.
    """
    load_test_config = LoadTestRequest(
        num_tasks=50,
        task_type="cpu_intensive",
        batch_size=10,
        delay_ms=0,
        target_queue=get_default_queue(),
    )

    return await start_load_test(load_test_config)


@router.post("/examples/load-test-medium", response_model=TaskResponse)
async def enqueue_medium_load_test() -> TaskResponse:
    """
    Example: Medium load test with 200 I/O tasks.

    Tests concurrent async task handling with realistic batching.
    """
    load_test_config = LoadTestRequest(
        num_tasks=200,
        task_type="io_simulation",
        batch_size=20,
        delay_ms=50,
        target_queue=get_default_queue(),
    )

    return await start_load_test(load_test_config)


@router.post("/examples/load-test-large", response_model=TaskResponse)
async def enqueue_large_load_test() -> TaskResponse:
    """
    Example: Large load test with 1000 memory tasks.

    Stress tests queue capacity and worker performance under heavy load.
    """
    load_test_config = LoadTestRequest(
        num_tasks=1000,
        task_type="memory_operations",
        batch_size=50,
        delay_ms=0,
        target_queue=get_default_queue(),
    )

    return await start_load_test(load_test_config)


@router.get("/load-test-result/{task_id}")
async def get_load_test_result(task_id: str, target_queue: str | None = None) -> dict[str, Any]:
    """
    Get enhanced load test results with analysis and verification.

    Returns comprehensive load test results including performance analysis,
    test type verification, and recommendations for optimization.

    Args:
        task_id: The load test orchestrator task ID
        target_queue: Queue where the test was run (defaults to configured
            load_test queue)

    Returns:
        Enhanced load test results with analysis
    """
    from app.services.load_test import LoadTestService

    try:
        result = await LoadTestService.get_load_test_result(task_id, target_queue)

        if not result:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "load_test_not_found",
                    "message": f"No load test results found for task {task_id}",
                    "task_id": task_id,
                    "target_queue": target_queue,
                },
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get load test result for {task_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "result_retrieval_failed",
                "message": f"Failed to retrieve load test results: {str(e)}",
            },
        )


@router.get("/load-test-types")
async def get_load_test_types() -> dict[str, Any]:
    """
    Get information about available load test types.

    Returns detailed information about each test type including
    expected metrics, performance characteristics, and usage guidance.

    Returns:
        Dictionary of test type information
    """
    from app.components.worker.constants import LoadTestTypes
    from app.services.load_test import LoadTestService

    test_types = {}

    # Get info for all available test types
    all_types = [
        LoadTestTypes.CPU_INTENSIVE,
        LoadTestTypes.IO_SIMULATION,
        LoadTestTypes.MEMORY_OPERATIONS,
        LoadTestTypes.FAILURE_TESTING,
    ]
    for test_type in all_types:
        test_types[test_type] = LoadTestService.get_test_type_info(test_type)

    return {
        "available_test_types": test_types,
        "usage_examples": {
            "quick_cpu_test": {
                "description": "Quick CPU test with 50 tasks",
                "parameters": {
                    "num_tasks": 50,
                    "task_type": "cpu_intensive",
                    "batch_size": 10,
                    "target_queue": "load_test",
                },
            },
            "io_stress_test": {
                "description": "I/O stress test with concurrent operations",
                "parameters": {
                    "num_tasks": 200,
                    "task_type": "io_simulation",
                    "batch_size": 20,
                    "delay_ms": 50,
                    "target_queue": "load_test",
                },
            },
            "memory_load_test": {
                "description": "Memory allocation test with GC pressure",
                "parameters": {
                    "num_tasks": 500,
                    "task_type": "memory_operations",
                    "batch_size": 25,
                    "target_queue": "media",
                },
            },
        },
    }
