"""
Dramatiq middleware for publishing worker events to Redis Streams.

Publishes job lifecycle events (started, completed, failed) and worker
lifecycle events (started, stopped) from the worker process. Middleware
hooks in Dramatiq are **sync**, so this uses sync ``redis.Redis`` for
event publishing.

Enqueue-side events (job.enqueued) are handled separately in
pools.py since middleware runs in the worker process, not
the client process.
"""

import contextlib
import sys
import threading
from typing import Any

import dramatiq
from dramatiq.asyncio import get_event_loop_thread
import redis
from app.components.worker import runtime
from app.components.worker.heartbeat import mark_busy_sync, mark_idle_sync, worker_id
from app.core.boot import apply_saved_overrides
from app.core.config import settings
from app.core.log import logger
from app.core.key_family import KeyFamily

# Redis Stream name for worker events (must match events.py)
WORKER_EVENT_STREAM = "aegis:events:worker"


def _sync_publish(
    client: redis.Redis,
    event_type: str,
    queue_name: str,
    metadata: dict[str, str] | None = None,
) -> None:
    """Publish an event to the Redis Stream (sync)."""
    from datetime import UTC, datetime

    fields: dict[str, str] = {
        "type": event_type,
        "queue": queue_name,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if metadata:
        fields.update(metadata)

    try:
        client.xadd(WORKER_EVENT_STREAM, fields)  # type: ignore[arg-type]
    except Exception as e:
        logger.debug(f"Failed to publish worker event: {e}")


REDIS_KEYS = (
    KeyFamily(
        "dramatiq:heartbeat:*",
        "string",
        "Queue heartbeats",
        "One per consumed queue while a worker runs, 30s TTL",
        "Dramatiq worker events",
        columns=("Key", "Value"),
    ),
)


class EventPublishMiddleware(dramatiq.Middleware):
    """Publishes worker lifecycle events to a Redis Stream."""

    HEARTBEAT_TTL = 30
    HEARTBEAT_INTERVAL = 15

    _redis: redis.Redis | None = None
    _queue_names: set[str] = set()
    _heartbeat_thread: threading.Thread | None = None
    _stop_event: threading.Event = threading.Event()
    _runtime_reports: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Worker lifecycle hooks
    # ------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """Background thread that refreshes heartbeat keys periodically."""
        while not self._stop_event.wait(self.HEARTBEAT_INTERVAL):
            if self._redis:
                for queue_name in self._queue_names:
                    with contextlib.suppress(Exception):
                        self._redis.set(
                            f"dramatiq:heartbeat:{queue_name}",
                            "alive",
                            ex=self.HEARTBEAT_TTL,
                        )
                for fields in self._runtime_reports:
                    runtime.publish_runtime_sync(self._redis, fields)

    def after_worker_boot(
        self, broker: dramatiq.Broker, worker: dramatiq.Worker
    ) -> None:
        """Apply what the Overseer saved, on the AsyncIO middleware's loop:
        the one this worker's async actors and their database engine use."""
        loop = get_event_loop_thread()
        if loop is None:
            logger.warning("No asyncio loop at worker boot: saved settings not applied")
            return
        loop.run_coroutine(apply_saved_overrides())

    def before_worker_boot(
        self, broker: dramatiq.Broker, worker: dramatiq.Worker
    ) -> None:
        """Initialize the middleware on worker boot.

        Creates a sync Redis connection, publishes a worker.started event
        for each queue this worker consumes, sets initial heartbeat keys,
        and starts a background thread that refreshes heartbeats every 10s.
        Called once when the Dramatiq worker process starts.

        Also sets the prefetch to the thread count, not dramatiq's default
        of twice that: a prefetched message is this worker's alone while it
        waits. Consumers are built after this hook, so every launcher
        (entrypoint, a bare ``dramatiq`` command) gets it.
        """
        worker.queue_prefetch = worker.worker_threads
        try:
            self._redis = redis.from_url(settings.redis_url_effective)
            self._queue_names = (
                worker.consumer_whitelist or broker.get_declared_queues()
            )

            # Publish started event and set initial heartbeat
            for queue_name in self._queue_names:
                _sync_publish(self._redis, "worker.started", queue_name)
                self._redis.set(
                    f"dramatiq:heartbeat:{queue_name}",
                    "alive",
                    ex=self.HEARTBEAT_TTL,
                )

            # Report what this process runs with (refreshed with the heartbeat)
            launched = runtime.launch_settings("dramatiq", sys.argv)
            self._runtime_reports = [
                runtime.report(
                    worker=worker_id(),
                    queue=queue_name,
                    engine="dramatiq",
                    version=runtime.engine_version("dramatiq"),
                    **launched,
                )
                for queue_name in self._queue_names
            ]
            for fields in self._runtime_reports:
                runtime.publish_runtime_sync(self._redis, fields)

            # Start background heartbeat thread
            self._stop_event.clear()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True
            )
            self._heartbeat_thread.start()
        except Exception as e:
            logger.debug(f"Failed to initialize event publishing: {e}")

    def before_worker_shutdown(
        self, broker: dramatiq.Broker, worker: dramatiq.Worker
    ) -> None:
        """Gracefully shut down the middleware.

        Stops the heartbeat thread, publishes a worker.stopped event for
        each queue, deletes heartbeat keys, and closes the Redis connection.
        Called once when the Dramatiq worker process is shutting down.
        """
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

        if self._redis:
            for queue_name in self._queue_names:
                _sync_publish(self._redis, "worker.stopped", queue_name)
                self._redis.delete(f"dramatiq:heartbeat:{queue_name}")
            with contextlib.suppress(Exception):
                self._redis.delete(runtime.runtime_key(worker_id()))
            self._redis.close()
            self._redis = None

    # ------------------------------------------------------------------
    # Message lifecycle hooks
    # ------------------------------------------------------------------

    def before_process_message(
        self, broker: dramatiq.Broker, message: dramatiq.Message
    ) -> None:
        """Run before each task executes.

        Publishes a job.started event to the Redis Stream and records the
        task as started in the task history. Fires after the message is
        dequeued but before the actor function runs.
        """
        if self._redis:
            mark_busy_sync(self._redis)
            _sync_publish(
                self._redis,
                "job.started",
                message.queue_name,
                {"job_id": message.message_id, "task": message.actor_name},
            )
            # Record task started in history
            from app.components.worker.task_history import record_task_started_sync

            record_task_started_sync(
                self._redis,
                message.message_id,
                task_name=message.actor_name,
                queue_name=message.queue_name,
            )

    def after_process_message(
        self,
        broker: dramatiq.Broker,
        message: dramatiq.Message,
        *,
        result: object | None = None,
        exception: BaseException | None = None,
    ) -> None:
        """Run after each task completes or fails.

        Publishes a job.completed or job.failed event to the Redis Stream
        and records the final status in the task history. Fires after the
        actor function returns (or raises), with the exception available
        for inspection.
        """
        if self._redis:
            event_type = "job.failed" if exception else "job.completed"
            _sync_publish(
                self._redis,
                event_type,
                message.queue_name,
                {"job_id": message.message_id, "task": message.actor_name},
            )
            # Record task finished in history
            from app.components.worker.task_history import record_task_finished_sync

            record_task_finished_sync(
                self._redis,
                message.message_id,
                success=exception is None,
                error=str(exception) if exception else None,
                task_name=message.actor_name,
                queue_name=message.queue_name,
            )
            mark_idle_sync(self._redis)
