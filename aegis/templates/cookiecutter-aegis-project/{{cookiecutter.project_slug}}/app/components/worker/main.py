"""
Worker component main module.

Configures and manages arq worker pools with priority queues.
"""

import asyncio

from arq.connections import RedisSettings
from arq.worker import Worker

from app.core.config import settings
from app.core.log import logger

from .tasks import get_queue_functions


class WorkerPool:
    """Manages arq worker pools with priority queues."""

    def __init__(self) -> None:
        self.redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
        self.workers: dict[str, Worker] = {}

    async def start_workers(self) -> None:
        """Start worker pools for functional queue domains."""
        logger.info("Starting functional worker pools...")

        # Start one worker pool per functional queue
        for queue_type, queue_config in settings.WORKER_QUEUES.items():
            try:
                # Get functions specific to this queue type
                queue_functions = get_queue_functions(queue_type)

                # Skip queues with no functions
                if not queue_functions:
                    logger.info(
                        f"Skipping {queue_type} worker: no functions registered "
                        f"({queue_config['description']})"
                    )
                    continue

                worker = Worker(
                    functions=queue_functions,
                    redis_settings=self.redis_settings,
                    queue_name=queue_config["queue_name"],
                    max_jobs=queue_config["max_jobs"],
                    job_timeout=queue_config["timeout_seconds"],
                    keep_result=settings.WORKER_KEEP_RESULT_SECONDS,
                    max_tries=settings.WORKER_MAX_TRIES,
                    health_check_interval=30,
                )

                # Start worker in background
                asyncio.create_task(worker.async_run())
                self.workers[queue_type] = worker

                function_names = [f.__name__ for f in queue_functions]
                logger.info(
                    f"Started {queue_type} worker: {queue_config['description']} "
                    f"({queue_config['max_jobs']} concurrent jobs) "
                    f"with {len(function_names)} functions: {', '.join(function_names)}"
                )

            except Exception as e:
                logger.error(f"Failed to start {queue_type} worker: {e}")
                raise

        logger.info(f"✅ Worker system started: {len(self.workers)} functional pools")

    async def stop_workers(self) -> None:
        """Stop all worker pools gracefully."""
        logger.info("Stopping worker pools...")

        for queue_type, worker in self.workers.items():
            try:
                await worker.close()
                logger.info(f"Stopped {queue_type} worker pool")
            except Exception as e:
                logger.error(f"Error stopping {queue_type} worker: {e}")

        self.workers.clear()
        logger.info("✅ All worker pools stopped")


# Global worker pool instance
worker_pool = WorkerPool()


async def run_worker() -> None:
    """
    Main worker entry point for the worker container.

    This function starts all worker pools and keeps them running.
    """
    logger.info("🔧 Initializing arq worker pools...")

    try:
        await worker_pool.start_workers()

        # Keep workers running until interrupted
        logger.info("🚀 Worker pools ready - waiting for tasks...")

        # Create a simple event loop that waits indefinitely
        stop_event = asyncio.Event()

        # Handle graceful shutdown
        import signal

        def signal_handler() -> None:
            logger.info("Received shutdown signal")
            stop_event.set()

        # Register signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in [signal.SIGTERM, signal.SIGINT]:
            loop.add_signal_handler(sig, signal_handler)

        # Wait for shutdown signal
        await stop_event.wait()

    except KeyboardInterrupt:
        logger.info("Worker shutdown requested")
    except Exception as e:
        logger.error(f"Worker pool error: {e}")
        raise
    finally:
        await worker_pool.stop_workers()
        logger.info("🛑 Worker pools shutdown complete")
