# Worker Configuration

Comprehensive guide to configuring and scaling the worker component in your Aegis Stack application.

## Worker Settings

=== "arq"

    Workers use arq's native `WorkerSettings` classes with direct task imports. Each queue has its own configuration:

    **System Worker (`app/components/worker/queues/system.py`):**

    ```python
    from arq import RedisSettings
    from app.components.worker.tasks.system import system_health_check

    class WorkerSettings:
        functions = [system_health_check]
        queue_name = "arq:queue:system"
        max_jobs = 15
        job_timeout = 300
    ```

    **Load Test Worker (`app/components/worker/queues/load_test.py`):**

    ```python
    from app.components.worker.tasks.load_tasks import (
        cpu_intensive_task,
        io_simulation_task,
        memory_operations_task,
        failure_testing_task,
    )

    class WorkerSettings:
        functions = [cpu_intensive_task, io_simulation_task, memory_operations_task, failure_testing_task]
        queue_name = "arq:queue:load_test"
        max_jobs = 50
        job_timeout = 60
    ```

    **Global Configuration (`app/core/config.py`):**

    ```python
    class Settings(BaseSettings):
        REDIS_URL: str = "redis://localhost:6379"
        REDIS_DB: int = 0
        WORKER_KEEP_RESULT_SECONDS: int = 3600
        WORKER_MAX_TRIES: int = 3

        @property
        def redis_settings(self) -> RedisSettings:
            """Get Redis settings for arq workers."""
            return RedisSettings.from_dsn(self.REDIS_URL, database=self.REDIS_DB)
    ```

=== "Dramatiq"

    Dramatiq uses a **single global broker** shared by all queues. The broker is configured once and set globally via `dramatiq.set_broker()`:

    **Broker Setup (`app/components/worker/broker.py`):**

    ```python
    import dramatiq
    from app.components.worker.middleware import EventPublishMiddleware
    from app.core.config import settings
    from dramatiq.brokers.redis import RedisBroker
    from dramatiq.middleware import AsyncIO
    from dramatiq.results import Results
    from dramatiq.results.backends.redis import RedisBackend

    # Result backend for storing task return values
    result_backend = RedisBackend(url=settings.REDIS_URL)

    # Create a single global RedisBroker
    broker = RedisBroker(url=settings.REDIS_URL)
    broker.add_middleware(AsyncIO())
    broker.add_middleware(Results(backend=result_backend))
    broker.add_middleware(EventPublishMiddleware())

    # Set as the global broker so @dramatiq.actor uses it
    dramatiq.set_broker(broker)
    ```

    !!! info "AsyncIO Middleware"
        The `AsyncIO` middleware is part of Dramatiq's standard library (`dramatiq.middleware`). No external packages are required to run async actors. Simply define your actor as `async def` and Dramatiq handles the event loop.

    **Actor Definition (`app/components/worker/queues/system.py`):**

    ```python
    import dramatiq
    from app.components.worker.broker import broker  # noqa: F401 - imports trigger broker setup
    from app.core.log import logger

    @dramatiq.actor(queue_name="system", store_results=True)
    async def system_health_check() -> dict:
        """Periodic system health check."""
        logger.info("Running system health check")
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

    @dramatiq.actor(queue_name="system", store_results=True, max_retries=3)
    async def cleanup_temp_files(days_old: int = 7) -> dict:
        """Remove temporary files older than specified days."""
        cleaned = await remove_old_files(days_old)
        return {"files_removed": cleaned}
    ```

=== "TaskIQ"

    TaskIQ uses **per-queue broker instances**. Each queue module creates its own `RedisStreamBroker` with a unique queue name:

    **Queue Broker (`app/components/worker/queues/system.py`):**

    ```python
    from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker
    from app.components.worker.middleware_taskiq import EventPublishMiddleware
    from app.core.config import settings

    redis_url = settings.redis_url_effective

    broker = (
        RedisStreamBroker(url=redis_url, queue_name="taskiq:system")
        .with_result_backend(
            RedisAsyncResultBackend(redis_url=redis_url, result_ex_time=60)
        )
        .with_middlewares(EventPublishMiddleware().set_queue_name("system"))
    )

    @broker.task
    async def system_health_check() -> dict[str, str]:
        """Simple system health check task."""
        return {
            "status": "healthy",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    ```

    Key characteristics:
    - `RedisStreamBroker` uses Redis Streams for acknowledgement support
    - Unique `queue_name` per broker prevents worker cross-contamination
    - `result_ex_time=60` sets result TTL in seconds
    - `EventPublishMiddleware` publishes lifecycle events for the dashboard

---

## Environment Variables

### Shared (All Backends)

```bash
# Redis connection
REDIS_URL=redis://redis:6379        # Used by Docker containers
REDIS_URL_LOCAL=redis://localhost:6379  # Used by CLI commands running locally
REDIS_DB=0
```

### Backend-Specific

=== "arq"

    ```bash
    WORKER_KEEP_RESULT_SECONDS=3600     # How long to retain task results
    WORKER_MAX_TRIES=3                  # Retry attempts on failure
    ```

=== "Dramatiq"

    ```bash
    WORKER_PROCESSES=1                  # Number of OS processes
    WORKER_QUEUES='{"system": {"concurrency": 8}}'  # Threads per process
    ```

    `WORKER_PROCESSES` x the queue's concurrency (`WORKER_QUEUES`, used as dramatiq's threads) determines total concurrency. For I/O-bound async actors, increasing threads is usually sufficient. For CPU-bound work, increase processes to utilize multiple cores.

=== "TaskIQ"

    ```bash
    WORKER_PROCESSES=2                  # Number of worker processes (--workers flag)
    ```

    TaskIQ only uses process-based concurrency (no thread configuration). Each process runs its own async event loop.

### Local Development

```bash
# .env file for local development
REDIS_URL=redis://redis:6379        # Used by Docker containers
REDIS_URL_LOCAL=redis://localhost:6379  # Used by CLI commands running locally
REDIS_DB=0
ENVIRONMENT=development
APP_ENV=dev                         # Enables auto-reload in Docker
```

When running CLI commands locally (outside Docker), the system automatically uses `REDIS_URL_LOCAL` if configured. This dual-configuration approach allows:

- **Docker containers** to connect to the `redis` service
- **Local CLI commands** to connect to `localhost` Redis without starting containers

### Production Settings

=== "arq"

    ```bash
    ENVIRONMENT=production
    WORKER_KEEP_RESULT_SECONDS=1800     # Shorter retention in production
    WORKER_MAX_TRIES=5                  # More retries in production
    REDIS_URL=redis://redis-prod:6379
    REDIS_DB=1
    REDIS_PASSWORD=your-secure-password
    ```

=== "Dramatiq"

    ```bash
    ENVIRONMENT=production
    WORKER_PROCESSES=4                  # Match the container's cpus limit
    WORKER_QUEUES='{"system": {"concurrency": 8}}'  # Per-process threads
    REDIS_URL=redis://redis-prod:6379
    REDIS_DB=1
    REDIS_PASSWORD=your-secure-password
    ```

=== "TaskIQ"

    ```bash
    ENVIRONMENT=production
    WORKER_PROCESSES=4                  # Match the container's cpus limit
    REDIS_URL=redis://redis-prod:6379
    REDIS_DB=1
    REDIS_PASSWORD=your-secure-password
    ```

!!! note "Processes need memory and CPU to match"
    Each worker process costs about 95 MiB, on top of about 90 MiB the container pays once, and a container's `cpus` limit caps it however many processes it runs. Raising `WORKER_PROCESSES` means raising the service's `memory` and `cpus` limits with it. The generated workers default to one process per container; to add capacity without touching limits, scale containers instead: `docker compose up -d --scale worker-system=3`.

---

## Docker Integration

=== "arq"

    ```yaml
    # docker-compose.yml
    services:
      worker-system:
        build: .
        command:
          - worker
          - system
        environment:
          - DOCKER_CONTAINER=1
          - WORKER_QUEUE_TYPE=system
          - WORKER_TIMEOUT_SECONDS=1800
          - WORKER_MAX_TRIES=5
          - REDIS_URL=redis://redis:6379
        depends_on:
          redis:
            condition: service_healthy
        restart: unless-stopped

      worker-load-test:
        build: .
        command:
          - worker
          - load_test
        environment:
          - DOCKER_CONTAINER=1
          - WORKER_QUEUE_TYPE=load_test
          - WORKER_TIMEOUT_SECONDS=60
          - WORKER_MAX_TRIES=1
          - REDIS_URL=redis://redis:6379
        depends_on:
          redis:
            condition: service_healthy
        restart: unless-stopped
    ```

=== "Dramatiq"

    ```yaml
    # docker-compose.yml
    services:
      worker-system:
        build: .
        command:
          - worker
          - system
        environment:
          - DOCKER_CONTAINER=1
          - WORKER_QUEUE_TYPE=system
          - WORKER_PROCESSES=${SYSTEM_WORKER_PROCESSES:-1}
          - WORKER_TIMEOUT_SECONDS=1800
          - REDIS_URL=redis://redis:6379
        depends_on:
          redis:
            condition: service_healthy
        restart: unless-stopped

      worker-load-test:
        build: .
        command:
          - worker
          - load_test
        environment:
          - DOCKER_CONTAINER=1
          - WORKER_QUEUE_TYPE=load_test
          - WORKER_PROCESSES=${LOAD_TEST_WORKER_PROCESSES:-1}
          - WORKER_TIMEOUT_SECONDS=60
          - REDIS_URL=redis://redis:6379
        depends_on:
          redis:
            condition: service_healthy
        restart: unless-stopped
    ```

=== "TaskIQ"

    ```yaml
    # docker-compose.yml
    services:
      worker-system:
        build: .
        command:
          - worker
          - system
        environment:
          - DOCKER_CONTAINER=1
          - WORKER_QUEUE_TYPE=system
          - WORKER_PROCESSES=${SYSTEM_WORKER_PROCESSES:-1}
          - WORKER_TIMEOUT_SECONDS=1800
          - REDIS_URL=redis://redis:6379
          # Docker file watching fix
          - WATCHFILES_FORCE_POLLING=true
          - WATCHFILES_POLL_DELAY_MS=800
        depends_on:
          redis:
            condition: service_healthy
        restart: unless-stopped

      worker-load-test:
        build: .
        command:
          - worker
          - load_test
        environment:
          - DOCKER_CONTAINER=1
          - WORKER_QUEUE_TYPE=load_test
          - WORKER_PROCESSES=${LOAD_TEST_WORKER_PROCESSES:-1}
          - WORKER_TIMEOUT_SECONDS=60
          - REDIS_URL=redis://redis:6379
          - WATCHFILES_FORCE_POLLING=true
          - WATCHFILES_POLL_DELAY_MS=800
        depends_on:
          redis:
            condition: service_healthy
        restart: unless-stopped
    ```

    !!! info "Watchfiles Polling"
        TaskIQ uses `watchfiles` for auto-reload in development. Docker volume mounts require polling mode (`WATCHFILES_FORCE_POLLING=true`) since filesystem events don't propagate through bind mounts.

---

## Scaling Strategies

=== "arq"

    ### Horizontal Scaling

    Scale by running multiple worker containers. arq workers coordinate through Redis:

    ```bash
    docker compose up --scale worker-system=3
    ```

    ### Vertical Scaling

    Increase per-worker concurrency via `WorkerSettings`:

    ```python
    # app/components/worker/queues/system.py
    class WorkerSettings:
        functions = [system_health_check]
        queue_name = "arq:queue:system"
        max_jobs = 30  # Increased from 15
        job_timeout = 300
    ```

    ### Environment-Based Configuration

    ```python
    # app/components/worker/queues/system.py
    from app.core.config import settings

    class WorkerSettings:
        functions = [system_health_check]
        queue_name = "arq:queue:system"

        keep_result = settings.WORKER_KEEP_RESULT_SECONDS
        max_tries = settings.WORKER_MAX_TRIES
        redis_settings = settings.redis_settings

        max_jobs = 30 if settings.ENVIRONMENT == "production" else 15
        job_timeout = 300 if settings.ENVIRONMENT == "production" else 600
    ```

=== "Dramatiq"

    ### Process x Thread Scaling

    Dramatiq's concurrency model is explicit:

    ```python
    # Total concurrent messages = WORKER_PROCESSES x the queue's concurrency (threads)
    # Example: 2 processes x 8 threads = 16 concurrent messages per container
    ```

    **I/O-bound workloads**: increase threads.

    ```bash
    WORKER_PROCESSES=1
    WORKER_QUEUES='{"system": {"concurrency": 32}}'  # Async actors spend most time awaiting I/O
    ```

    **CPU-bound workloads**: increase processes.

    ```bash
    WORKER_PROCESSES=4   # One per CPU core
    WORKER_QUEUES='{"system": {"concurrency": 4}}'  # Fewer threads per process
    ```

    **Mixed workloads**: balanced.

    ```bash
    WORKER_PROCESSES=2
    WORKER_QUEUES='{"system": {"concurrency": 8}}'
    ```

    ### Horizontal Scaling

    For horizontal scaling, run multiple worker containers:

    ```bash
    docker compose up --scale worker-system=3
    ```

    Each container runs its own set of processes and threads.

=== "TaskIQ"

    ### Process Scaling

    TaskIQ uses process-based concurrency via the `--workers` flag:

    ```bash
    taskiq worker app.components.worker.queues.system:broker --workers 4
    ```

    Each process runs its own async event loop, making it effective for both I/O-bound and CPU-bound workloads.

    In Docker, configure via environment variable:

    ```bash
    WORKER_PROCESSES=4   # Passed to --workers flag
    ```

    ### Horizontal Scaling

    Run multiple worker containers for additional capacity:

    ```bash
    docker compose up --scale worker-system=3
    ```

    Redis Streams ensure each message is consumed by exactly one worker, even across multiple containers.

---

## Concurrency per Queue

How many jobs one worker process runs at once is a per-queue setting, the
same for every backend:

```python
# app/core/config.py
WORKER_QUEUES: dict[str, QueueWorker]  # {"load_test": QueueWorker(concurrency=50), "system": QueueWorker(concurrency=15)}
WORKER_QUEUE_DEFAULT: QueueWorker      # any queue not listed (concurrency 10)
```

Override it from the environment as JSON:

```bash
WORKER_QUEUES='{"load_test": {"concurrency": 100}}'
```

| Backend | Where the value goes |
|---|---|
| taskiq | `--max-async-tasks` (entrypoint) |
| dramatiq | `--threads` (entrypoint) |
| arq | `WorkerSettings.max_jobs` |

`QueueWorker` rejects unknown fields and non-positive values when settings
load, and a queue name that matches no queue stops the worker at startup.
The total a queue can run at once is its concurrency times its processes
(`WORKER_PROCESSES`). Each worker reports what it runs with, shown in
Overseer under Worker > Runtime.

### How a TaskIQ worker takes jobs

A TaskIQ queue is a Redis stream read by one consumer group. A worker claims
jobs with `XREADGROUP` and acks each when it finishes; a claimed job belongs
to that worker alone.

- **It claims what it can start.** Each read takes at most the queue's
  concurrency, so a busy worker never sits on jobs an idle one could run, and
  a worker that dies strands no more than one round.
- **A running job keeps its claim.** Jobs a dead worker left unacked are
  handed to another after 10 minutes. While a job runs, its claim is
  refreshed, so a long job is never run a second time alongside itself.
- **A busy worker still counts as alive.** A worker working through what it
  claimed reads nothing for a while; Overseer counts it as serving its queue
  as long as it keeps reporting itself (Worker > Runtime).

---

## Redis Configuration

### Connection Settings

```python
# app/core/config.py
class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_CONNECTION_TIMEOUT: int = 5
```

### Redis Persistence

For production, configure Redis persistence:

```yaml
# docker-compose.yml
redis:
  image: redis:7-alpine
  command: >
    redis-server
    --maxmemory 512mb
    --maxmemory-policy volatile-lru
    --save 900 1
    --save 300 10
    --save 60 10000
    --appendonly yes
  volumes:
    - redis-data:/data
    - ./redis.conf:/usr/local/etc/redis/redis.conf
```

Keep the eviction policy `volatile-*`, never `allkeys-*`. Redis holds the
job streams next to the cache: `allkeys-lru` evicts any key when memory
runs out, so queued jobs silently disappear. `volatile-lru` only evicts
keys that already expire (cache entries, job results, task records), and
once none are left Redis refuses the write instead of dropping work.

---

## Performance Tuning

=== "arq"

    ### Memory Management

    ```python
    class WorkerSettings:
        functions = [system_health_check]
        keep_result = 1800  # 30 minutes for production
        max_jobs = 15       # Limit concurrent jobs to manage memory
    ```

    ### Timeout Configuration

    ```python
    class WorkerSettings:  # system queue
        functions = [system_health_check, cleanup_temp_files]
        job_timeout = 300  # 5 minutes for system tasks

    class WorkerSettings:  # load_test queue
        functions = [cpu_intensive_task, io_simulation_task]
        job_timeout = 60   # Quick test tasks
        max_jobs = 50
    ```

=== "Dramatiq"

    ### Process/Thread Tuning

    `WORKER_PROCESSES` x the queue's concurrency (`WORKER_QUEUES`, used as dramatiq's threads) determines total concurrency:

    ```bash
    # I/O-bound: more threads, fewer processes
    WORKER_PROCESSES=1
    WORKER_QUEUES='{"system": {"concurrency": 16}}'

    # CPU-bound: more processes (one per core), fewer threads
    WORKER_PROCESSES=4
    WORKER_QUEUES='{"system": {"concurrency": 4}}'
    ```

    ### Actor-Level Tuning

    ```python
    @dramatiq.actor(
        queue_name="system",
        store_results=True,
        max_retries=3,
        min_backoff=1000,     # 1s minimum backoff
        max_backoff=600_000,  # 10m maximum backoff
        time_limit=300_000,   # 5 minute time limit (ms)
    )
    async def my_task() -> dict:
        ...
    ```

=== "TaskIQ"

    ### Result TTL

    Configure how long results are stored in Redis:

    ```python
    broker = (
        RedisStreamBroker(url=redis_url, queue_name="taskiq:system")
        .with_result_backend(
            RedisAsyncResultBackend(
                redis_url=redis_url,
                result_ex_time=60,  # Result TTL in seconds
            )
        )
    )
    ```

    ### Process Count

    ```bash
    # Match CPU count for CPU-bound tasks
    WORKER_PROCESSES=4

    # Fewer processes for I/O-bound tasks (async handles concurrency)
    WORKER_PROCESSES=2
    ```

### Connection Pooling

```python
REDIS_MAX_CONNECTIONS = 50  # Per worker process
REDIS_CONNECTION_TIMEOUT = 5
REDIS_SOCKET_KEEPALIVE = True
```

---

## Monitoring & Health Checks

=== "arq"

    Health checks use Redis heartbeat keys with TTL. Each worker writes a heartbeat key on startup and updates it periodically:

    ```python
    # app/components/worker/queues/system.py
    class WorkerSettings:
        functions = [system_health_check]
        health_check_key = "worker:health:system"
        health_check_interval = 30  # seconds
        keep_result = 3600
    ```

    **Check queue metrics:**

    ```bash
    arq app.components.worker.queues.system.WorkerSettings --check
    ```

    The API uses `LLEN` on queue keys for depth metrics.

=== "Dramatiq"

    Dramatiq health is monitored via Redis queue depth and delay queue inspection:

    ```bash
    # Query Redis directly
    KEYS dramatiq:*           # List all Dramatiq keys
    LLEN dramatiq:system      # System queue depth
    LLEN dramatiq:system.DQ   # System delay queue depth
    ```

    The Overseer dashboard reads these metrics automatically for real-time display.

=== "TaskIQ"

    TaskIQ publishes lifecycle events to Redis Streams via `EventPublishMiddleware`:

    **Event types:**

    - `worker.started` / `worker.stopped`, Worker lifecycle
    - `job.enqueued`, Task enqueued (from client side)
    - `job.started` / `job.completed` / `job.failed`, Task execution

    ```python
    class EventPublishMiddleware(TaskiqMiddleware):
        async def startup(self) -> None:
            await publish_event(redis, "worker.started", queue_name)

        async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
            await publish_event(redis, "job.started", queue_name, {...})

        async def post_execute(self, message, result) -> None:
            event_type = "job.failed" if result.is_err else "job.completed"
            await publish_event(redis, event_type, queue_name, {...})
    ```

    The Overseer dashboard subscribes to these events via SSE for real-time updates.

---

## Security Configuration

### Authentication

```python
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
REDIS_USERNAME = os.getenv("REDIS_USERNAME")  # Redis 6.0+
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() == "true"
```

### Network Security

```yaml
# docker-compose.yml - Internal network only
services:
  worker-system:
    networks:
      - internal
    # No ports exposed

  redis:
    networks:
      - internal
    ports:
      - "127.0.0.1:6379:6379"  # Localhost only

networks:
  internal:
    driver: bridge
    internal: true
```

---

## Advanced Configuration

=== "arq"

    ### Custom Worker Classes

    ```python
    # app/components/worker/custom.py
    from arq import Worker

    class CustomWorker(Worker):
        """Extended worker with custom behavior."""

        async def startup(self):
            """Initialize resources on worker startup."""
            await super().startup()
            await init_database_pool()
            await setup_monitoring()

        async def shutdown(self):
            """Cleanup on worker shutdown."""
            await close_database_pool()
            await super().shutdown()
    ```

=== "Dramatiq"

    ### Dramatiq Result Retrieval

    Results are stored using a key derived from the actor name, queue name, and message ID. The `Results` middleware with `RedisBackend` handles storage automatically when `store_results=True`:

    Result keys follow the pattern: `MD5(namespace:queue_name:actor_name:message_id)`.

    ```bash
    curl "http://localhost:8000/api/v1/tasks/result/{message_id}?actor_name=io_simulation_task&queue_name=load_test"
    ```

=== "TaskIQ"

    ### Custom Middleware

    TaskIQ middleware hooks into the task lifecycle:

    ```python
    from taskiq import TaskiqMiddleware, TaskiqMessage, TaskiqResult

    class MyMiddleware(TaskiqMiddleware):
        async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
            """Run before each task."""
            logger.info(f"Starting task: {message.task_name}")
            return message

        async def post_execute(self, message: TaskiqMessage, result: TaskiqResult) -> None:
            """Run after each task."""
            if result.is_err:
                logger.error(f"Task failed: {message.task_name}")
    ```

    Attach middleware when creating the broker:

    ```python
    broker = (
        RedisStreamBroker(url=redis_url, queue_name="taskiq:system")
        .with_middlewares(MyMiddleware())
    )
    ```

## Next Steps

- **[Examples](examples.md)** - See configuration in action
- **[Load Testing](extras/load-testing.md)** - Test your configuration
- **[Back to Overview](index.md)** - Return to worker component overview
