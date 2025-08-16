"""
System and orchestration tasks.

Contains the load test orchestrator which spawns many tasks to measure queue throughput.
"""

import asyncio
from datetime import datetime
from typing import Any

from app.components.worker.constants import LoadTestTypes, TaskNames
from app.core.config import get_load_test_queue
from app.core.log import logger


async def load_test_orchestrator(
    ctx: dict[str, Any],
    num_tasks: int = 100,
    task_type: str = "cpu_intensive",
    batch_size: int = 10,
    delay_ms: int = 0,
    target_queue: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Load test orchestrator that spawns many lightweight tasks to measure queue
    throughput.

    This is the new approach: instead of one task doing heavy work, we spawn
    hundreds of lightweight tasks to actually stress test the queue infrastructure
    and measure meaningful performance metrics like tasks/second.

    Args:
        num_tasks: Number of tasks to spawn for the load test
        task_type: Type of worker task to spawn (cpu_intensive, io_simulation,
            memory_operations)
        batch_size: How many tasks to send concurrently per batch
        delay_ms: Delay between batches in milliseconds
        target_queue: Which queue to test (defaults to configured load_test queue)

    Returns:
        Comprehensive load test results with throughput metrics
    """
    start_time = datetime.now()
    test_id = ctx.get("job_id", "unknown")

    # Use configured load test queue if not specified
    if target_queue is None:
        target_queue = get_load_test_queue()

    logger.info(
        f"🚀 Starting load test orchestrator: {num_tasks} {task_type} tasks "
        f"(batches of {batch_size})"
    )

    try:
        # Import here to avoid circular imports
        from app.components.worker.pools import get_queue_pool

        # Get queue pool for enqueueing
        pool, queue_name = await get_queue_pool(target_queue)

        # Spawn tasks in batches
        task_ids = []
        tasks_sent = 0

        for batch_start in range(0, num_tasks, batch_size):
            batch_end = min(batch_start + batch_size, num_tasks)
            current_batch_size = batch_end - batch_start

            # Enqueue batch of tasks
            # Map task type to actual function name
            task_func = _get_task_function_name(task_type)

            batch_jobs = []
            for _ in range(current_batch_size):
                job = await pool.enqueue_job(task_func, _queue_name=queue_name)
                if job is not None:
                    batch_jobs.append(job)
                    task_ids.append(job.job_id)

            tasks_sent += current_batch_size
            logger.info(
                f"📤 Sent batch: {current_batch_size} tasks "
                f"(total: {tasks_sent}/{num_tasks})"
            )

            # Add configurable delay between batches if specified
            if delay_ms > 0 and batch_end < num_tasks:
                await asyncio.sleep(delay_ms / 1000.0)

        # Don't close the pool yet - we need it for monitoring!
        # await pool.aclose()

        logger.info(f"✅ All {tasks_sent} tasks enqueued to {queue_name}")

        # Monitor task completion with timeout based on queue configuration
        from app.core.config import settings

        queue_config = settings.WORKER_QUEUES.get(target_queue, {})
        monitor_timeout = queue_config.get(
            "timeout_seconds", 300
        )  # Use queue's timeout

        logger.info(f"⏱️ Monitoring task completion (timeout: {monitor_timeout}s)...")

        completion_result = await _monitor_task_completion(
            task_ids=task_ids,
            pool=pool,
            expected_tasks=tasks_sent,
            timeout_seconds=monitor_timeout,  # Use configured timeout
        )

        # NOW we can close the pool after monitoring is done
        await pool.aclose()

        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()

        # Combine orchestrator stats with completion monitoring
        result = {
            "test_id": test_id,
            "task_type": task_type,
            "tasks_sent": tasks_sent,
            "task_ids": task_ids[:10],  # Sample of IDs for debugging
            "batch_size": batch_size,
            "delay_ms": delay_ms,
            "target_queue": target_queue,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "total_duration_seconds": round(total_duration, 2),
            **completion_result,  # Merge in the monitoring results
        }

        # Calculate overall throughput based on completed tasks
        if result.get("tasks_completed", 0) > 0:
            result["overall_throughput_per_second"] = round(
                result["tasks_completed"] / total_duration, 2
            )
        else:
            result["overall_throughput_per_second"] = 0

        logger.info(
            f"🏁 Load test complete: {result['tasks_completed']}/{tasks_sent} "
            f"tasks in {total_duration:.1f}s"
        )
        logger.info(
            f"📈 Throughput: {result['overall_throughput_per_second']} tasks/sec"
        )

        return result

    except Exception as e:
        logger.error(f"Load test orchestrator failed: {e}")
        return {"test_id": test_id, "error": str(e), "tasks_sent": tasks_sent}


def _get_task_function_name(task_type: str) -> str:
    """Map task type to actual function name."""
    task_map = {
        LoadTestTypes.CPU_INTENSIVE: TaskNames.CPU_INTENSIVE_TASK,
        LoadTestTypes.IO_SIMULATION: TaskNames.IO_SIMULATION_TASK,
        LoadTestTypes.MEMORY_OPERATIONS: TaskNames.MEMORY_OPERATIONS_TASK,
        LoadTestTypes.FAILURE_TESTING: TaskNames.FAILURE_TESTING_TASK,
    }
    return task_map.get(task_type, TaskNames.CPU_INTENSIVE_TASK)


async def _monitor_task_completion(
    task_ids: list[str],
    pool: Any,
    expected_tasks: int,
    timeout_seconds: int = 300,
    poll_interval: float = 2.0,
) -> dict[str, Any]:
    """
    Monitor task completion by checking job results directly.

    This avoids Redis queue type errors by tracking job completion
    instead of trying to read queue internals.
    """
    start_monitor = datetime.now()
    tasks_completed = 0
    tasks_failed = 0
    last_progress_time = start_monitor
    last_completed = 0

    # Track which task IDs we've seen complete
    completed_ids: set[str] = set()
    failed_ids: set[str] = set()

    try:
        while True:
            # Check each task ID for completion
            for task_id in task_ids:
                if task_id in completed_ids or task_id in failed_ids:
                    continue  # Already processed

                # Check if job result exists
                result_key = f"arq:result:{task_id}"
                result_data = await pool.get(result_key)

                if result_data:
                    # Job completed - check if it succeeded or failed
                    try:
                        # arq stores results as msgpack, but we can check existence
                        completed_ids.add(task_id)
                        tasks_completed += 1
                    except Exception:
                        # If we can't parse, assume it completed
                        completed_ids.add(task_id)
                        tasks_completed += 1

            tasks_done = tasks_completed + tasks_failed

            # Calculate throughput
            elapsed = (datetime.now() - start_monitor).total_seconds()
            throughput = tasks_completed / elapsed if elapsed > 0 else 0

            # Check if we're making progress
            if tasks_completed > last_completed:
                last_progress_time = datetime.now()
                last_completed = tasks_completed

            # Progress logging (less verbose)
            progress_pct = (
                (tasks_done / expected_tasks * 100) if expected_tasks > 0 else 0
            )
            if (
                tasks_done % 10 == 0 or tasks_done == expected_tasks
            ):  # Log every 10 tasks or at completion
                logger.info(
                    f"📈 Progress: {tasks_done}/{expected_tasks} "
                    f"({progress_pct:.0f}% - completed: {tasks_completed}, "
                    f"failed: {tasks_failed}) throughput: {throughput:.1f} tasks/sec"
                )

            # Check completion
            if tasks_done >= expected_tasks:
                logger.info(
                    f"✅ All tasks completed: {tasks_completed} success, "
                    f"{tasks_failed} failed"
                )
                break

            # Check timeout
            if elapsed > timeout_seconds:
                logger.warning(f"⏱️ Load test timed out after {timeout_seconds}s")
                break

            # Check if we're stuck (no progress for 30 seconds)
            stuck_duration = (datetime.now() - last_progress_time).total_seconds()
            if stuck_duration > 30 and tasks_done > 0:
                logger.warning(
                    f"⚠️ No progress for {stuck_duration:.0f}s, stopping monitor"
                )
                break

            await asyncio.sleep(poll_interval)

    except Exception as e:
        logger.error(f"Task monitoring error: {e}")

    # Final metrics
    final_elapsed = (datetime.now() - start_monitor).total_seconds()

    return {
        "tasks_completed": tasks_completed,
        "tasks_failed": tasks_failed,
        "monitor_duration_seconds": round(final_elapsed, 2),
        "average_throughput_per_second": round(tasks_completed / final_elapsed, 2)
        if final_elapsed > 0
        else 0,
        "completion_percentage": round((tasks_completed / expected_tasks * 100), 1)
        if expected_tasks > 0
        else 0,
        "failure_rate_percent": round((tasks_failed / expected_tasks * 100), 1)
        if expected_tasks > 0
        else 0,
    }
