"""Clients are per loop/request, never an import-time shared Redis pool."""

from app.core.config import settings
from app.services.system.errors.store import ErrorStore
from app.services.system.redis_keys import redis_client


def unavailable_reason() -> str | None:
    if not settings.ERROR_TRACKING_ENABLED:
        return "Error tracking is disabled by configuration."
    if not hasattr(settings, "REDIS_URL"):
        return "Error tracking needs the Redis component."
    from app.core import runtime

    if runtime.get_runtime().backend_name != "docker":
        return "Error tracking needs a Docker runtime with container logs."
    return None


def repository() -> ErrorStore:
    return ErrorStore(
        redis_client(int(getattr(settings, "REDIS_DB", 0))),
        settings.PROJECT_NAME,
        max_occurrences=settings.ERROR_TRACKING_MAX_OCCURRENCES,
        retention_seconds=settings.ERROR_TRACKING_RETENTION_SECONDS,
    )
