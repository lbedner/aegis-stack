"""Where a run's results are kept: Redis when there is one, memory otherwise."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.services.load_test.api.models import (
    APILoadTestResult,
)
from app.services.load_test.common.storage import RedisResultStore


def _build_redis_client() -> Any | None:
    """Construct a redis.asyncio client from project config; ``None`` if
    Redis isn't configured/available."""
    try:
        import redis.asyncio as aioredis

        from app.core.config import settings

        redis_url = getattr(settings, "redis_url_effective", None)
        if not redis_url:
            return None
        return aioredis.from_url(redis_url)
    except Exception:
        return None


def _make_store() -> RedisResultStore[APILoadTestResult] | None:
    """Construct a Redis-backed store; ``None`` if Redis isn't available.

    Mockable seam: tests patch this (or the service class) to skip the
    storage path entirely. The redis client is owned by ``_with_store``,
    not by the store itself, so it can be closed cleanly at the end of
    the operation.
    """
    client = _build_redis_client()
    if client is None:
        return None
    return RedisResultStore(
        redis=client,
        key_prefix="api_load_test",
        result_model=APILoadTestResult,
    )


T = TypeVar("T")


async def _with_store(
    op: Callable[[RedisResultStore[APILoadTestResult] | None], Awaitable[T]],
) -> T:
    """Run ``op`` with a store, ensuring the underlying redis client is
    closed cleanly inside the event loop.

    Without this, the redis client's ``__del__`` fires during interpreter
    shutdown when the asyncio loop has already closed, producing an ugly
    ``RuntimeError: Event loop is closed`` traceback.
    """
    store = _make_store()
    try:
        return await op(store)
    finally:
        if store is not None:
            await store.aclose()
