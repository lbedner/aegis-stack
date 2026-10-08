# Overseer Integration Guide

This guide shows how to add health monitoring to custom components and services in your Aegis Stack application.

## Health Check Registration

Overseer uses a registry pattern to collect health information from all components and services. During application startup, components and services register their health check functions with the central health registry.

### Component Health Checks

**Components** are infrastructure pieces like backends, databases, workers, and schedulers.

**Registration Function:**
```python
from app.services.system import register_health_check

register_health_check(name: str, check_fn: Callable[[], Awaitable[ComponentStatus]])
```

**Example: Backend Component**
```python
# app/components/backend/health.py
from app.core import thresholds
from app.services.system import register_health_check
from app.services.system.models import ComponentStatus

async def check_backend_health() -> ComponentStatus:
    """Check backend component health."""
    # Collect system metrics
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()

    # Unhealthy at the alert, a warning short of it: the rule every
    # Overseer figure and chart reads (app/core/thresholds.py)
    status = thresholds.status(cpu_percent, 90)

    return ComponentStatus(
        name="backend",
        status=status,
        message="Backend API operational",
        metadata={
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "disk_percent": psutil.disk_usage('/').percent,
        }
    )

# Register during component initialization
register_health_check("backend", check_backend_health)
```

**Warning and alert levels.** `thresholds.status(value, alert)` is unhealthy
at `alert` and a warning from `WARNING_PERCENT_OF_THRESHOLD` of it (Overseer >
Settings, Health). A live chart marks the same levels as dashed lines with
`series.chart(..., thresholds=thresholds.levels(alert))`.

### Service Health Checks

**Services** are business capabilities like authentication, AI integrations, and communications.

**Registration Function:**
```python
from app.services.system import register_service_health_check

register_service_health_check(name: str, check_fn: Callable[[], Awaitable[ComponentStatus]])
```

**Example: Auth Service**
```python
# app/services/auth/health.py
from app.services.system import register_service_health_check
from app.services.system.models import ComponentStatus, ComponentStatusType
from app.core.config import settings

async def check_auth_service_health() -> ComponentStatus:
    """Check auth service health including JWT configuration."""
    jwt_errors = []

    # Validate JWT configuration
    if not settings.SECRET_KEY or len(settings.SECRET_KEY) < 32:
        jwt_errors.append("SECRET_KEY misconfigured")

    # Check database connectivity
    database_available = True
    try:
        from sqlalchemy import text
        from app.core.db import db_session
        with db_session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        database_available = False
        jwt_errors.append("Database unavailable")

    # Determine status
    status = ComponentStatusType.HEALTHY
    if jwt_errors:
        status = ComponentStatusType.UNHEALTHY if not database_available else ComponentStatusType.WARNING

    return ComponentStatus(
        name="auth",
        status=status,
        message="Auth service ready" if not jwt_errors else f"Issues: {'; '.join(jwt_errors)}",
        metadata={
            "service_type": "auth",
            "jwt_algorithm": getattr(settings, "ALGORITHM", "HS256"),
            "database_available": database_available,
        }
    )

register_service_health_check("auth", check_auth_service_health)
```

## ComponentStatus Model

The `ComponentStatus` model defines the structure for health check results.

```python
ComponentStatus(
    name: str,                              # Component/service name
    status: ComponentStatusType,            # HEALTHY | INFO | WARNING | UNHEALTHY
    message: str,                           # Human-readable status message
    response_time_ms: float | None = None, # Optional response time
    metadata: dict[str, Any] = {},         # Custom metrics for dashboard
    children: list[ComponentStatus] = [],  # Nested components (optional)
)
```

## Custom Metadata for Dashboard Cards

The `metadata` dictionary passes custom data to dashboard cards.

**Example Patterns:**
```python
# System metrics
metadata = {
    "cpu_percent": 12.5,
    "memory_percent": 45.2,
    "disk_percent": 60.0,
}

# Service configuration
metadata = {
    "service_type": "auth",
    "user_count": 42,
    "jwt_algorithm": "HS256",
    "security_level": "standard",
}

# Queue statistics
metadata = {
    "jobs_queued": 5,
    "jobs_active": 2,
    "jobs_failed": 3,
    "failure_rate": 0.02,
}
```

## Status Hierarchy and Propagation

Overseer uses a four-tier status system that propagates from child components to parents.

**Status Priority (highest to lowest):**

1. **UNHEALTHY** - Any unhealthy child makes parent unhealthy
2. **WARNING** - Any warning child makes parent warning (if no unhealthy)
3. **INFO** - Any info child makes parent info (if no unhealthy/warning)
4. **HEALTHY** - All children healthy makes parent healthy

**Example with Children:**
```python
# Worker component with multiple queues
async def check_worker_health() -> ComponentStatus:
    """Check worker with per-queue status."""
    queue_statuses = [
        await check_queue_health("system"),
        await check_queue_health("notifications"),
    ]

    # Propagate worst status from queues
    from app.services.system.health import propagate_status
    overall_status = propagate_status([q.status for q in queue_statuses])

    return ComponentStatus(
        name="worker",
        status=overall_status,
        message=f"Worker with {len(queue_statuses)} queues",
        children=queue_statuses,
        metadata={"total_queues": len(queue_statuses)},
    )
```

## Health Check Best Practices

### 1. Keep Checks Fast
Health checks run every 30 seconds via dashboard polling. Avoid expensive operations.

```python
# ❌ BAD - Slow query
async def slow_health_check() -> ComponentStatus:
    users = session.exec(select(User)).all()  # Loads ALL users
    return ComponentStatus(...)

# ✅ GOOD - Limited query
async def fast_health_check() -> ComponentStatus:
    statement = select(User).limit(101)  # Only check if >100 users
    users = list(session.exec(statement).all())
    user_count_display = "100+" if len(users) > 100 else str(len(users))
    return ComponentStatus(metadata={"user_count_display": user_count_display})
```

### 2. Use Caching for Expensive Metrics
System metrics (CPU, memory, disk) can be cached briefly to improve performance.

```python
from datetime import UTC, datetime, timedelta

_metrics_cache: dict[str, tuple[dict, datetime]] = {}
CACHE_TTL = timedelta(seconds=5)

async def get_system_metrics() -> dict:
    """Get system metrics with 5-second cache."""
    now = datetime.now(UTC)

    if "system" in _metrics_cache:
        cached_data, cached_time = _metrics_cache["system"]
        if now - cached_time < CACHE_TTL:
            return cached_data

    # Expensive metrics collection
    metrics = {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
    }

    _metrics_cache["system"] = (metrics, now)
    return metrics
```

### 3. Handle Errors Gracefully
Always return a `ComponentStatus`, even on failure.

```python
async def check_external_api_health() -> ComponentStatus:
    """Check external API dependency."""
    try:
        response = await http_client.get("https://api.example.com/health")
        response.raise_for_status()

        return ComponentStatus(
            name="external_api",
            status=ComponentStatusType.HEALTHY,
            message="External API reachable",
        )
    except Exception as e:
        # Don't raise - return unhealthy status
        return ComponentStatus(
            name="external_api",
            status=ComponentStatusType.UNHEALTHY,
            message=f"External API unreachable: {str(e)}",
            metadata={"error": str(e)},
        )
```

### 4. Use Descriptive Messages
Messages appear in both the dashboard and CLI health output.

```python
# ❌ BAD - Vague message
message = "Worker error"

# ✅ GOOD - Specific message
message = f"Worker queue 'system' has 50 failed jobs (failure rate: 15%)"
```

### 5. Include Actionable Metadata
Metadata powers dashboard visualizations and debugging.

```python
# ✅ GOOD - Rich metadata for debugging
metadata = {
    "queue_name": "system",
    "jobs_queued": 50,
    "jobs_active": 0,  # ⚠️ No workers processing
    "jobs_failed": 15,
    "failure_rate": 0.15,
    "redis_connected": False,  # 🔴 Root cause
}
```

## Registration Timing

Health checks must be registered **during application startup**, before the health endpoint is accessed.

**Typical Registration Points:**

- **Component Initialization**: `app/components/{component}/__init__.py`
- **Service Initialization**: `app/services/{service}/__init__.py`
- **Backend Startup Hook**: `app/components/backend/startup/component_health.py`

**Conditional Registration Pattern:**
```python
# Register backend (always included)
register_health_check("backend", check_backend_health)

# Conditionally register optional components
try:
    from app.components.worker.health import check_worker_health
    register_health_check("worker", check_worker_health)
except ImportError:
    pass  # Worker component not included
```

## Next Steps

- **[Overseer Overview](index.md)** - Learn about Overseer's architecture and purpose
- **[The Overseer Story](story.md)** - Evolution and vision
- **[CLI Reference](../cli-reference.md)** - Health command documentation (search for "health")

## Container error collection

The backend's `startup/error_tracking.py` starts the collector through the shared
background task registry. The matching shutdown hook cancels and awaits pumps,
releases its lease when possible, and closes its Redis client. One 20-second
Redis lease per project fences writes from superseded collectors. Discovery and
lease renewal run every five seconds. Each running container on a known runtime
page has an independent stream; workers are supported without importing worker
modules. Sources reconnect with exponential backoff, capped at 30 seconds.

| Setting | Default | Meaning |
| --- | --- | --- |
| `ERROR_TRACKING_ENABLED` | `true` | Enable background collection |
| `ERROR_TRACKING_RETENTION_SECONDS` | `604800` | Maximum retained age: seven days |
| `ERROR_TRACKING_MAX_OCCURRENCES` | `10000` | Total retained occurrences per project; maximum 10,000 |
| `ERROR_TRACKING_MAX_SOURCES` | `64` | Concurrent container streams; maximum 256 |

Keys use `aegis:errors:<hash-of-PROJECT_NAME>:` and notifications use
`aegis:events:errors:<hash-of-PROJECT_NAME>`. Projects sharing Redis must use
distinct `PROJECT_NAME` values. Redis keyspace ownership is declared by the
repository and appears on Overseer's Redis page. History uses hashes and sorted
indexes; notifications are hints, capped at approximately 10,000 stream entries.

An occurrence is capped at 64 KiB including serialized JSON escaping. Each
source assembler holds at most 48 KiB per stdout/stderr record; the Docker stream
decoder bounds unfinished input to 1 MiB. Writes are awaited to apply backpressure.
Search metadata is bounded separately. Retention removes records, search metadata,
and indexes together in batches of at most 128 per atomic operation, yielding
between batches. Cleanup runs within one discovery tick plus batch processing
time; reading never writes. Empty issue indexes disappear. With no filter, the
list reads per-issue summaries each write keeps current; any filter reads the
search metadata once and groups it.
Active source cursors are removed when their containers leave discovery; lease
and shared health status expire automatically.

Replay identity retains Docker's original nanosecond timestamp and per-stream
ordinal, including non-error input. A source's position is saved at most once a
second, and reconnect re-reads the second before it; occurrence IDs absorb the
overlap. A fixed-size discarded-history watermark
prevents count-pruned records from returning on replay. Late inputs at or before
that boundary, including timestamp ties, are conservatively dropped and counted.

Recovery is **best effort within Docker log retention**, not a durable capture
or exactly-once promise. The restricted proxy does not expose exact restart
incarnations; container ID plus timestamp identify restart input. Rotation, missing
source timestamps, unfinished traces and oversized input can leave gaps. Bootstrap
looks back at most the retention window. Redis persistence/eviction configuration
determines whether history and cursors survive Redis restarts. Losing cursors may
trigger a broader retained-log replay; losing both source logs and Redis history
cannot be repaired.

Credential-shaped keys, authorization strings, URL credentials, and recognized
nested locals are redacted before retention. Redaction is best effort: secrets in
arbitrary exception prose may remain. Stored data is escaped when rendered; it is
never treated as HTML. Collector failures are reported through shared status,
rather than logging captured error diagnostics back into their own feed.

The page distinguishes disabled collection (configuration or missing Redis/Docker),
degraded collection (source/Redis failure, stale status, source cap), empty history,
and expired detail. For degraded collection, check Redis connectivity, the Docker
socket proxy, container logging drivers, and source limits. Sources retry without
blocking requests. A running state indicates current collection health; it does
not certify that Docker's historical logs are complete.

Run the isolated real Docker/Redis scenario from a generated project with Redis
and deploy installed:

```bash
AEGIS_ERROR_TRACKING_DOCKER_TEST=1 uv run pytest tests/components/test_error_tracking_integration.py -q
```

It uses unique Redis namespaces and disposable source containers, verifies
closed-browser collection, grouping, exact traces, replay, failover and container
replacement, and removes its containers and keys afterward. The Redis contract
and SSE tests run only against a Redis you name, never the development stack's,
each in its own namespace:

```bash
docker run --rm -d -p 6390:6379 --name error-test-redis redis
AEGIS_ERROR_TRACKING_REDIS_URL=redis://127.0.0.1:6390 uv run pytest tests/services/test_error_store.py -q
```


## Automatic error attribution

Keep using `from app.core.log import logger`. The shared logging processor derives
`app_service` from `app/services/<name>/...` only when the name belongs to the
shared `ServiceName` registry, checked against the generator’s `ServiceSpec` list; runtime-registered plugin services are also accepted. Shared
folders such as `system` and `change_queue` are not application services.
Existing logger calls need no per-function context manager. `emitting_service`
records the service that wrote the log. For exceptions, the processor inspects
traceback frames and chained causes before formatting, allowing an AI failure
logged by an HTTP handler to retain its AI origin. Suppressed exception contexts
are not used. This is code-location attribution, not proof of the underlying
system responsible for a failure.

Scheduled job discovery retains the declaring service. The existing execution
wrappers establish scoped ownership automatically on scheduler and worker runs,
restore it after completion/failure, and preserve exception ownership for outer
handlers. Every process sets the same logging pipeline up as it boots
(``apply_saved_overrides``), workers started by their own CLI included. Arbitrary
process/thread handoffs outside those wrappers do not automatically inherit it.

Both development console logs and production JSON logs carry attribution into
retained errors. The runtime `service` and container identity remain separate
from `app_service`. The Errors checklist is the Logs one, with the same query
parameters (`service`, `container`, `app_service`), so a filter carries between
the two pages. Grouping includes the application service.
