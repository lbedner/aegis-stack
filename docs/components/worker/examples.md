# Worker Examples

Essential patterns for the worker component.

## Basic Task Implementation

=== "arq"

    ```python
    # app/components/worker/tasks/system_tasks.py
    from app.core.log import logger

    async def cleanup_old_logs(ctx, days_old: int = 30) -> dict:
        """Clean up log files older than specified days."""
        try:
            logger.info(f"Starting log cleanup: {days_old} days")

            cleaned_files = await remove_old_logs(days_old)
            space_freed = calculate_space_freed(cleaned_files)

            return {
                "status": "completed",
                "files_cleaned": len(cleaned_files),
                "space_freed_mb": space_freed
            }

        except Exception as e:
            logger.error(f"Log cleanup failed: {e}")
            raise  # Let arq handle retries
    ```

=== "Dramatiq"

    ```python
    # app/components/worker/queues/system.py
    import dramatiq
    from app.components.worker.broker import broker  # noqa: F401
    from app.core.log import logger

    @dramatiq.actor(queue_name="system", store_results=True, max_retries=3)
    async def cleanup_old_logs(days_old: int = 30) -> dict:
        """Clean up log files older than specified days."""
        try:
            logger.info(f"Starting log cleanup: {days_old} days")

            cleaned_files = await remove_old_logs(days_old)
            space_freed = calculate_space_freed(cleaned_files)

            return {
                "status": "completed",
                "files_cleaned": len(cleaned_files),
                "space_freed_mb": space_freed
            }

        except Exception as e:
            logger.error(f"Log cleanup failed: {e}")
            raise  # Dramatiq handles retries via Retries middleware
    ```

    Note the differences from arq:
    - No `ctx` parameter - Dramatiq actors receive only their own arguments
    - Retry count set on the actor via `max_retries=3`
    - Must import `broker` to trigger broker initialization before actors are defined

=== "TaskIQ"

    ```python
    # app/components/worker/queues/system.py
    from app.core.log import logger

    @broker.task
    async def cleanup_old_logs(days_old: int = 30) -> dict:
        """Clean up log files older than specified days."""
        try:
            logger.info(f"Starting log cleanup: {days_old} days")

            cleaned_files = await remove_old_logs(days_old)
            space_freed = calculate_space_freed(cleaned_files)

            return {
                "status": "completed",
                "files_cleaned": len(cleaned_files),
                "space_freed_mb": space_freed
            }

        except Exception as e:
            logger.error(f"Log cleanup failed: {e}")
            raise
    ```

    Note the differences from arq and Dramatiq:
    - No `ctx` parameter - TaskIQ tasks receive only their own arguments
    - Tasks are decorated with `@broker.task` on the queue's broker instance
    - All tasks must be `async def` (TaskIQ is async-native)
    - Retries are configured via middleware, not per-task

## Task Registration

=== "arq"

    Tasks are registered directly in `WorkerSettings.functions` - no central registry needed:

    ```python
    # app/components/worker/queues/system.py
    from app.components.worker.tasks.system_tasks import cleanup_old_logs

    class WorkerSettings:
        functions = [cleanup_old_logs]  # Direct import pattern
        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
        queue_name = "arq:queue:system"
        max_jobs = 15
    ```

=== "Dramatiq"

    Actors register themselves automatically when their module is imported. The worker CLI imports all queue modules to trigger registration:

    ```bash
    dramatiq app.components.worker.broker \
      app.components.worker.queues.system \
      app.components.worker.queues.load_test \
      --queues system load_test
    ```

    No explicit registration list is needed - the `@dramatiq.actor` decorator handles it.

=== "TaskIQ"

    Tasks register themselves via `@broker.task` when the module is imported. The worker CLI points directly at the broker instance:

    ```bash
    taskiq worker app.components.worker.queues.system:broker
    ```

    Each queue module defines its own broker and tasks. No central registry is needed - tasks are bound to their broker at import time.

## Enqueuing Tasks

### From Application Code

=== "arq"

    ```python
    from app.components.worker.pools import get_queue_pool

    async def enqueue_cleanup():
        """Enqueue a system task."""
        pool, queue_name = await get_queue_pool("system")
        try:
            job = await pool.enqueue_job(
                "cleanup_old_logs",
                days_old=7,
                _queue_name=queue_name
            )
            return job.job_id
        finally:
            await pool.aclose()
    ```

=== "Dramatiq"

    ```python
    import asyncio
    from app.components.worker.queues.system import cleanup_old_logs

    async def enqueue_cleanup():
        """Enqueue a system task."""
        # actor.send() is synchronous (Redis LPUSH)
        # Wrap with asyncio.to_thread to avoid blocking the event loop
        message = await asyncio.to_thread(cleanup_old_logs.send, 7)
        return message.message_id
    ```

    Or use the shared helper from `pools.py`:

    ```python
    from app.components.worker.pools import enqueue_task
    from app.components.worker.queues.system import cleanup_old_logs

    async def enqueue_cleanup():
        message = await enqueue_task(cleanup_old_logs, 7)
        return message.message_id
    ```

=== "TaskIQ"

    ```python
    from app.components.worker.queues.system import cleanup_old_logs

    async def enqueue_cleanup():
        """Enqueue a system task."""
        # .kiq() is async and returns a handle for tracking
        handle = await cleanup_old_logs.kiq(days_old=7)
        return str(handle.task_id)
    ```

    Or use the shared helper from `pools.py`:

    ```python
    from app.components.worker.pools import enqueue_task

    async def enqueue_cleanup():
        handle = await enqueue_task("cleanup_old_logs", "system", days_old=7)
        return str(handle.task_id)
    ```

### From API Endpoints

=== "arq"

    ```python
    # app/components/backend/api/admin.py
    from fastapi import APIRouter
    from app.components.worker.pools import get_queue_pool

    router = APIRouter()

    @router.post("/admin/cleanup")
    async def trigger_cleanup(days_old: int = 30):
        """Trigger cleanup via API."""
        pool, queue_name = await get_queue_pool("system")
        try:
            job = await pool.enqueue_job("cleanup_old_logs", days_old=days_old)
            return {"job_id": job.job_id, "status": "enqueued"}
        finally:
            await pool.aclose()
    ```

=== "Dramatiq"

    ```python
    # app/components/backend/api/admin.py
    from fastapi import APIRouter
    from app.components.worker.pools import enqueue_task
    from app.components.worker.queues.system import cleanup_old_logs

    router = APIRouter()

    @router.post("/admin/cleanup")
    async def trigger_cleanup(days_old: int = 30):
        """Trigger cleanup via API."""
        message = await enqueue_task(cleanup_old_logs, days_old)
        return {
            "message_id": message.message_id,
            "actor_name": cleanup_old_logs.actor_name,
            "queue_name": "system",
            "status": "enqueued",
        }
    ```

    The response includes `actor_name` and `queue_name` so the caller can retrieve results later:

    ```bash
    curl "http://localhost:8000/api/v1/tasks/result/{message_id}?actor_name=cleanup_old_logs&queue_name=system"
    ```

=== "TaskIQ"

    ```python
    # app/components/backend/api/admin.py
    from fastapi import APIRouter
    from app.components.worker.queues.system import cleanup_old_logs

    router = APIRouter()

    @router.post("/admin/cleanup")
    async def trigger_cleanup(days_old: int = 30):
        """Trigger cleanup via API."""
        handle = await cleanup_old_logs.kiq(days_old=days_old)
        return {
            "task_id": str(handle.task_id),
            "status": "enqueued",
        }
    ```

### From Scheduled Tasks

=== "arq"

    ```python
    # app/components/scheduler.py
    from app.components.worker.pools import get_queue_pool

    async def schedule_daily_cleanup():
        """Schedule daily cleanup task."""
        pool, queue_name = await get_queue_pool("system")
        try:
            await pool.enqueue_job("cleanup_old_logs", days_old=1)
        finally:
            await pool.aclose()
    ```

=== "Dramatiq"

    ```python
    # app/components/scheduler.py
    from app.components.worker.pools import enqueue_task
    from app.components.worker.queues.system import cleanup_old_logs

    async def schedule_daily_cleanup():
        """Schedule daily cleanup task."""
        await enqueue_task(cleanup_old_logs, 1)
    ```

=== "TaskIQ"

    ```python
    # app/components/scheduler.py
    from app.components.worker.queues.system import cleanup_old_logs

    async def schedule_daily_cleanup():
        """Schedule daily cleanup task."""
        await cleanup_old_logs.kiq(days_old=1)
    ```

## Result Retrieval

=== "arq"

    ```python
    from arq import ArqRedis
    from app.components.worker.pools import get_queue_pool

    async def get_task_result(job_id: str) -> dict | None:
        pool, _ = await get_queue_pool("system")
        try:
            job = await pool.job(job_id)
            if job is None:
                return None
            return await job.result(timeout=0)  # timeout=0 returns None if not done
        finally:
            await pool.aclose()
    ```

=== "Dramatiq"

    Dramatiq stores results in Redis keyed by a hash of `(namespace, queue_name, actor_name, message_id)`. The `Results` middleware handles encoding and decoding automatically.

    Retrieve via the API endpoint (handles the key derivation):

    ```bash
    curl "http://localhost:8000/api/v1/tasks/result/{message_id}?actor_name=cleanup_old_logs&queue_name=system"
    ```

    Or directly in Python:

    ```python
    from dramatiq.results.backends.redis import RedisBackend
    from app.core.config import settings

    async def get_dramatiq_result(message_id: str, actor_name: str, queue_name: str):
        backend = RedisBackend(url=settings.REDIS_URL)
        # backend.get_result raises ResultMissing if not found yet
        return backend.get_result(message_id, queue_name=queue_name, actor_name=actor_name)
    ```

=== "TaskIQ"

    TaskIQ returns an `AsyncTaskiqTask` handle when you enqueue with `.kiq()`. Use the handle to check status and retrieve results:

    ```python
    from app.components.worker.queues.system import cleanup_old_logs

    async def enqueue_and_get_result():
        handle = await cleanup_old_logs.kiq(days_old=7)

        # Check if result is ready
        is_ready = await handle.is_ready()

        if is_ready:
            result = await handle.get_result()
            if result.is_err:
                print(f"Task failed: {result.error}")
            else:
                print(f"Task result: {result.return_value}")
    ```

    Or retrieve by task ID using the result backend:

    ```python
    from app.components.worker.queues.system import broker

    async def get_result_by_id(task_id: str):
        result = await broker.result_backend.get_result(task_id)
        return result
    ```

## Error Handling Examples

### Task with Retry Logic

=== "arq"

    ```python
    async def resilient_task(ctx, max_retries: int = 3) -> dict:
        """Task with built-in retry handling."""
        current_try = ctx.get('job_try', 1)

        try:
            result = await perform_risky_operation()
            return {"status": "completed", "result": result}

        except TemporaryError as e:
            if current_try < max_retries:
                logger.warning(f"Temporary error on try {current_try}: {e}")
                raise  # Let arq retry
            else:
                logger.error(f"Permanent failure after {current_try} tries: {e}")
                return {"status": "failed", "error": str(e), "permanent": True}

        except PermanentError as e:
            logger.error(f"Permanent error: {e}")
            return {"status": "failed", "error": str(e), "permanent": True}
    ```

=== "Dramatiq"

    ```python
    @dramatiq.actor(queue_name="system", store_results=True, max_retries=3, min_backoff=1000)
    async def resilient_task() -> dict:
        """Task with built-in retry handling."""
        try:
            result = await perform_risky_operation()
            return {"status": "completed", "result": result}

        except PermanentError as e:
            logger.error(f"Permanent error: {e}")
            # Raise Retry to stop retrying immediately
            raise dramatiq.errors.Retry(delay=None) from e
    ```

    Retry behavior is controlled by `max_retries` and `min_backoff` on the actor decorator. The `Retries` middleware handles scheduling with exponential backoff.

=== "TaskIQ"

    ```python
    @broker.task
    async def resilient_task() -> dict:
        """Task with built-in retry handling."""
        try:
            result = await perform_risky_operation()
            return {"status": "completed", "result": result}

        except TemporaryError as e:
            logger.warning(f"Temporary error: {e}")
            raise  # TaskIQ will mark as failed; configure retries via middleware

        except PermanentError as e:
            logger.error(f"Permanent error: {e}")
            return {"status": "failed", "error": str(e), "permanent": True}
    ```

    TaskIQ retry behavior is configured via middleware rather than per-task decorators. Unhandled exceptions cause the task result to have `is_err=True`.

### Task Progress Tracking

```python
async def long_running_task(ctx, items: list[str]) -> dict:
    """Task with progress updates."""
    total_items = len(items)
    processed = 0

    for item in items:
        await process_item(item)
        processed += 1

        if processed % 10 == 0:
            progress = (processed / total_items) * 100
            logger.info(f"Progress: {progress:.1f}% ({processed}/{total_items})")

    return {
        "status": "completed",
        "items_processed": processed,
        "total_items": total_items
    }
```

## Multiple Queue Examples

### System Queue Tasks

=== "arq"

    ```python
    # app/components/worker/tasks/system_tasks.py
    async def backup_database(ctx) -> dict:
        backup_file = await create_database_backup()
        return {"status": "completed", "backup_file": backup_file}

    async def send_health_report(ctx) -> dict:
        report = await generate_health_report()
        await send_email_report(report)
        return {"status": "completed", "report_sent": True}
    ```

=== "Dramatiq"

    ```python
    # app/components/worker/queues/system.py
    @dramatiq.actor(queue_name="system", store_results=True)
    async def backup_database() -> dict:
        backup_file = await create_database_backup()
        return {"status": "completed", "backup_file": backup_file}

    @dramatiq.actor(queue_name="system", store_results=True)
    async def send_health_report() -> dict:
        report = await generate_health_report()
        await send_email_report(report)
        return {"status": "completed", "report_sent": True}
    ```

=== "TaskIQ"

    ```python
    # app/components/worker/queues/system.py
    @broker.task
    async def backup_database() -> dict:
        backup_file = await create_database_backup()
        return {"status": "completed", "backup_file": backup_file}

    @broker.task
    async def send_health_report() -> dict:
        report = await generate_health_report()
        await send_email_report(report)
        return {"status": "completed", "report_sent": True}
    ```

### Load Test Queue Tasks

=== "arq"

    ```python
    # app/components/worker/tasks/load_test_tasks.py
    async def cpu_intensive_task(ctx, duration_seconds: int = 1) -> dict:
        import time
        start_time = time.time()
        while time.time() - start_time < duration_seconds:
            _ = sum(i * i for i in range(1000))
        return {"status": "completed", "duration": duration_seconds}

    async def io_intensive_task(ctx, delay_seconds: int = 1) -> dict:
        await asyncio.sleep(delay_seconds)
        return {"status": "completed", "delay": delay_seconds}
    ```

=== "Dramatiq"

    ```python
    # app/components/worker/queues/load_test.py
    @dramatiq.actor(queue_name="load_test", store_results=True, time_limit=60_000)
    async def cpu_intensive_task(duration_seconds: int = 1) -> dict:
        import time
        start_time = time.time()
        while time.time() - start_time < duration_seconds:
            _ = sum(i * i for i in range(1000))
        return {"status": "completed", "duration": duration_seconds}

    @dramatiq.actor(queue_name="load_test", store_results=True)
    async def io_simulation_task(delay_seconds: float = 1.0) -> dict:
        await asyncio.sleep(delay_seconds)
        return {"status": "completed", "delay": delay_seconds}
    ```

    `time_limit` is in milliseconds when using the `TimeLimit` middleware.

=== "TaskIQ"

    ```python
    # app/components/worker/queues/load_test.py
    @broker.task
    async def cpu_intensive_task() -> dict:
        """CPU-bound task for load testing."""
        return await run_cpu_intensive()

    @broker.task
    async def io_simulation_task() -> dict:
        """I/O simulation task for load testing."""
        return await run_io_simulation()

    @broker.task
    async def memory_operations_task() -> dict:
        """Memory operations task for load testing."""
        return await run_memory_operations()
    ```

    TaskIQ load test tasks delegate to shared workload functions in `app/services/load_test_workloads.py`, keeping the queue module focused on task registration.

## Testing Worker Tasks

### Unit Testing

=== "arq"

    ```python
    # tests/worker/test_system_tasks.py
    import pytest
    from app.components.worker.tasks.system_tasks import cleanup_old_logs

    @pytest.mark.asyncio
    async def test_cleanup_old_logs():
        ctx = {"job_id": "test-job-123"}
        result = await cleanup_old_logs(ctx, days_old=7)
        assert result["status"] == "completed"
        assert "files_cleaned" in result
    ```

=== "Dramatiq"

    ```python
    # tests/worker/test_system_tasks.py
    import pytest
    from app.components.worker.queues.system import cleanup_old_logs

    @pytest.mark.asyncio
    async def test_cleanup_old_logs():
        # Call the underlying async function directly (no broker needed)
        result = await cleanup_old_logs.fn(days_old=7)
        assert result["status"] == "completed"
        assert "files_cleaned" in result
    ```

    Use `actor.fn` to call the underlying function directly in unit tests, bypassing the broker entirely.

=== "TaskIQ"

    ```python
    # tests/worker/test_system_tasks.py
    import pytest
    from app.components.worker.queues.system import cleanup_old_logs

    @pytest.mark.asyncio
    async def test_cleanup_old_logs():
        # Call the original async function directly (no broker needed)
        result = await cleanup_old_logs.original_func(days_old=7)
        assert result["status"] == "completed"
        assert "files_cleaned" in result
    ```

    Use `task.original_func` to call the unwrapped function directly in unit tests, bypassing TaskIQ's broker and middleware.

### Integration Testing

=== "arq"

    ```python
    # tests/worker/test_integration.py
    import pytest
    from app.components.worker.pools import get_queue_pool

    @pytest.mark.asyncio
    async def test_task_enqueue_and_process():
        pool, queue_name = await get_queue_pool("system")
        try:
            job = await pool.enqueue_job("cleanup_old_logs", days_old=1)
            assert job.job_id

            result = await job.result(timeout=30)
            assert result["status"] == "completed"
        finally:
            await pool.aclose()
    ```

=== "Dramatiq"

    ```python
    # tests/worker/test_integration.py
    import pytest
    from dramatiq.brokers.stub import StubBroker
    import dramatiq

    @pytest.fixture
    def stub_broker():
        broker = StubBroker()
        broker.emit_after("process_boot")
        dramatiq.set_broker(broker)
        yield broker
        broker.flush_all()
        broker.close()

    def test_task_enqueue(stub_broker):
        """Test that tasks are enqueued correctly."""
        from app.components.worker.queues.system import cleanup_old_logs
        cleanup_old_logs.send(7)
        stub_broker.join("system")
        # Verify message was processed
    ```

    Dramatiq's `StubBroker` is the standard way to test actors without a real Redis connection.

=== "TaskIQ"

    ```python
    # tests/worker/test_integration.py
    import pytest
    from app.components.worker.queues.system import broker, cleanup_old_logs

    @pytest.fixture
    async def started_broker():
        await broker.startup()
        yield broker
        await broker.shutdown()

    @pytest.mark.asyncio
    async def test_task_enqueue(started_broker):
        """Test that tasks are enqueued correctly."""
        handle = await cleanup_old_logs.kiq(days_old=1)
        assert handle.task_id

        # Wait for result
        result = await handle.wait_result(timeout=30)
        assert not result.is_err
        assert result.return_value["status"] == "completed"
    ```

    TaskIQ brokers need `startup()`/`shutdown()` for integration tests. Use `handle.wait_result()` to block until the task completes.

## API Reference

All task endpoints are available at `/api/v1/tasks/`:

```bash
# List all available tasks
curl http://localhost:8000/api/v1/tasks/

# Enqueue a task
curl -X POST http://localhost:8000/api/v1/tasks/enqueue \
  -H "Content-Type: application/json" \
  -d '{"task_name": "cpu_intensive_task", "queue_type": "load_test"}'

# Check task status
curl http://localhost:8000/api/v1/tasks/status/{task_id}

# Get task result
curl http://localhost:8000/api/v1/tasks/result/{task_id}

# Quick load tests; each answers with a test id (task_id)
curl -X POST http://localhost:8000/api/v1/tasks/examples/load-test-small
curl -X POST http://localhost:8000/api/v1/tasks/examples/load-test-medium
curl -X POST http://localhost:8000/api/v1/tasks/examples/load-test-large

# A load test's result, once it has finished (404 while it runs)
curl http://localhost:8000/api/v1/tasks/load-test-result/{test_id}
```

!!! info "Dramatiq status and result endpoints"
    The Dramatiq backend requires `actor_name` and `queue_name` query parameters for status and result lookups, because Dramatiq result keys are derived from the actor name and queue:

    ```bash
    curl "http://localhost:8000/api/v1/tasks/status/{message_id}?actor_name=io_simulation_task&queue_name=load_test"
    curl "http://localhost:8000/api/v1/tasks/result/{message_id}?actor_name=io_simulation_task&queue_name=load_test"
    ```

    The enqueue endpoint returns both `task_id` (the message ID) and `actor_name`/`queue_name` for use in subsequent calls.

## Next Steps

- **[Configuration](configuration.md)** - Configure workers for your use case
- **[Load Testing](extras/load-testing.md)** - Test your implementation
- **[Back to Overview](index.md)** - Return to worker component overview
