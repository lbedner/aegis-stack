"""
Ephemeral in-memory request-performance middleware.

Every HTTP request through the FastAPI app is timed and bucketed by
its resolved route pattern (``/users/{id}``, not ``/users/123``).
Stats live in a module-level singleton ``metrics_service`` with
bounded memory: ``deque(maxlen=100)`` of recent durations per
endpoint, plus running totals for count / sum / min / max so the
all-time average doesn't degrade as old samples fall off.

The data is intentionally non-persistent — it survives a process,
not a restart. The observability component (Logfire / OTEL) is the
durable / cross-process answer; this is the "what's slow right now"
view that Overseer renders without any external service.

Auto-discovered by ``backend_hooks`` because the file lives in
``app/components/backend/middleware/`` and exposes
``register_middleware(app)``.
"""

from __future__ import annotations

import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core import edges
from app.core.log import logger

# Recent-sample cap. 100 datapoints is enough for percentile math
# without holding more than a few KB of floats per endpoint.
_RECENT_SAMPLES = 100


@dataclass
class EndpointMetrics:
    """Per-endpoint counters + recent-samples window.

    ``count``, ``total_ms``, ``min_ms``, ``max_ms`` are unbounded
    totals over the process lifetime. ``recent_ms`` is the
    ``maxlen=100`` window used for percentile math, which is
    inherently a "last N requests" measure.
    """

    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0
    recent_ms: deque[float] = field(default_factory=lambda: deque(maxlen=_RECENT_SAMPLES))
    last_request_at: datetime | None = None

    def record(self, duration_ms: float) -> None:
        self.count += 1
        self.total_ms += duration_ms
        if duration_ms < self.min_ms:
            self.min_ms = duration_ms
        if duration_ms > self.max_ms:
            self.max_ms = duration_ms
        self.recent_ms.append(duration_ms)
        self.last_request_at = datetime.now(UTC)

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0

    @property
    def median_ms(self) -> float:
        if not self.recent_ms:
            return 0.0
        return statistics.median(self.recent_ms)

    @property
    def p95_ms(self) -> float:
        # ``method="inclusive"`` keeps the result bounded by the observed
        # min/max. The default (exclusive) can extrapolate past
        # ``max_ms`` for tiny windows, which surfaces "impossible"
        # percentiles on the Performance tab when an endpoint has only
        # been hit a couple of times.
        if len(self.recent_ms) < 2:
            return self.max_ms if self.recent_ms else 0.0
        return statistics.quantiles(self.recent_ms, n=20, method="inclusive")[18]

    @property
    def p99_ms(self) -> float:
        if len(self.recent_ms) < 2:
            return self.max_ms if self.recent_ms else 0.0
        return statistics.quantiles(self.recent_ms, n=100, method="inclusive")[98]


class RequestMetricsService:
    """In-memory per-route metric store. Singleton (see module-level
    ``metrics_service``); imported directly by the middleware and the
    metrics API. Tests reset via the autouse fixture in the metrics
    test files.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, EndpointMetrics] = defaultdict(EndpointMetrics)

    def record(self, method: str, route_pattern: str, duration_ms: float) -> None:
        """Append a duration sample to ``method route_pattern``'s bucket."""
        self._metrics[f"{method} {route_pattern}"].record(duration_ms)

    def reset(self) -> None:
        """Drop every bucket. Test-only entry point."""
        self._metrics.clear()

    def get_summary_stats(self) -> dict[str, Any]:
        """Cross-endpoint summary used by the dashboard card."""
        if not self._metrics:
            return {
                "total_requests": 0,
                "tracked_endpoints": 0,
                "avg_ms": 0.0,
                "p95_ms": 0.0,
                "slowest_endpoint": None,
            }

        # Pool every recent sample for one global p95. Cheap — at most
        # ``tracked_endpoints * _RECENT_SAMPLES`` floats.
        all_recent: list[float] = []
        for m in self._metrics.values():
            all_recent.extend(m.recent_ms)

        total_requests = sum(m.count for m in self._metrics.values())
        avg_ms = (
            sum(m.total_ms for m in self._metrics.values()) / total_requests
            if total_requests
            else 0.0
        )
        p95_ms = (
            statistics.quantiles(all_recent, n=20, method="inclusive")[18]
            if len(all_recent) >= 2
            else (all_recent[0] if all_recent else 0.0)
        )

        slowest_key, slowest = max(
            self._metrics.items(), key=lambda kv: kv[1].avg_ms
        )
        return {
            "total_requests": total_requests,
            "tracked_endpoints": len(self._metrics),
            "avg_ms": round(avg_ms, 2),
            "p95_ms": round(p95_ms, 2),
            "slowest_endpoint": {
                "endpoint": slowest_key,
                "avg_ms": round(slowest.avg_ms, 2),
            },
        }

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """Per-endpoint detail; the metrics API serializes this."""
        return {
            key: {
                "count": m.count,
                "avg_ms": round(m.avg_ms, 2),
                "min_ms": round(m.min_ms if m.min_ms != float("inf") else 0.0, 2),
                "max_ms": round(m.max_ms, 2),
                "median_ms": round(m.median_ms, 2),
                "p95_ms": round(m.p95_ms, 2),
                "p99_ms": round(m.p99_ms, 2),
                "last_request_at": (
                    m.last_request_at.isoformat() if m.last_request_at else None
                ),
            }
            for key, m in self._metrics.items()
        }


# Singleton — imported directly by middleware, API, and health.
metrics_service = RequestMetricsService()


# Stable label for requests that didn't match any FastAPI route (true
# 404s, raw asset paths). Without this, every novel garbage URL would
# allocate its own metric key — a scanner could grow the dict
# unboundedly.
_UNMATCHED_ROUTE = "__unmatched__"

# Endpoints that exist to *view* the metrics. Recording them means
# opening the Performance tab inflates its own numbers, and the
# summary tile drifts away from the per-endpoint table mid-view.
_SELF_REFERENTIAL_ROUTES = frozenset({
    "/api/v1/metrics/summary",
    "/api/v1/metrics/endpoints",
})


def _route_pattern(request: Request) -> str:
    """Return the parametrized path (``/users/{id}``) for the request,
    or a stable ``__unmatched__`` sentinel when no FastAPI route matched.
    """
    route = request.scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path
    return _UNMATCHED_ROUTE


class PerformanceMiddleware(BaseHTTPMiddleware):
    """Wraps every HTTP request, times it, and records into ``metrics_service``.

    Class-based on purpose: ``@app.middleware("http")`` registers a
    bare function under the hood as ``BaseHTTPMiddleware(dispatch=fn)``,
    and the project's middleware inspector serializes ``kwargs`` into
    its metadata. A function in that dict trips Pydantic's JSON encoder
    on the ``/health/`` response. A class with no kwargs has nothing
    function-shaped to leak.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            # Time and record in ``finally`` so 500s (where ``call_next``
            # raised) still appear on the Performance tab — that's
            # exactly the data you want when something is breaking.
            duration_ms = (time.perf_counter() - start) * 1000.0
            try:
                pattern = _route_pattern(request)
                if pattern not in _SELF_REFERENTIAL_ROUTES:
                    metrics_service.record(
                        request.method, pattern, duration_ms
                    )
                    if endpoint := request.scope.get("endpoint"):
                        failed = response is None or response.status_code >= 500
                        edges.into(
                            endpoint, source=edges.SERVER, ms=duration_ms, error=failed
                        )
            except Exception as e:
                # Never block the response on bookkeeping.
                logger.debug(f"PerformanceMiddleware: record failed: {e}")
            # Header only lands on the happy path — there is no response
            # object to mutate when ``call_next`` raised.
            if response is not None:
                response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"


def register_middleware(app: FastAPI) -> None:
    """Install the request-timing middleware.

    ``add_middleware`` makes it outermost (Starlette wraps each new
    layer around the existing app), so the duration captured is true
    wall time including every downstream middleware.
    """
    app.add_middleware(PerformanceMiddleware)
    logger.info("Performance middleware registered")
