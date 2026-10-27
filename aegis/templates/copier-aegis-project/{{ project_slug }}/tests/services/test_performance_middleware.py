"""
Integration tests for the request-performance middleware.

Drives a real ``TestClient`` so the middleware actually fires; asserts
on the singleton ``metrics_service`` after each request. Resets the
service per test so counts don't leak across cases.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.backend.middleware.performance import (
    EndpointMetrics,
    metrics_service,
)


@pytest.fixture(autouse=True)
def _reset_metrics_service():
    """Drop bookkeeping between tests so each one starts clean."""
    metrics_service.reset()
    yield
    metrics_service.reset()


class TestPerformanceMiddleware:
    def test_health_request_is_recorded(self, client: TestClient) -> None:
        """Hitting ``/health/`` populates the metrics service."""
        before = metrics_service.get_summary_stats()["total_requests"]

        response = client.get("/health/")
        assert response.status_code == 200

        after = metrics_service.get_summary_stats()
        assert after["total_requests"] == before + 1
        assert after["tracked_endpoints"] >= 1

    def test_x_response_time_header_is_set(self, client: TestClient) -> None:
        """Every response carries the ``X-Response-Time`` header."""
        response = client.get("/health/")
        assert response.status_code == 200
        header = response.headers.get("x-response-time", "")
        assert header.endswith("ms")
        # Parse the number off and confirm it's a positive float.
        value_ms = float(header.removesuffix("ms"))
        assert value_ms >= 0.0

    def test_repeated_requests_accumulate_count(self, client: TestClient) -> None:
        """N requests against the same endpoint produce N samples in one bucket."""
        for _ in range(3):
            client.get("/health/")

        endpoints = metrics_service.get_all_metrics()
        # The recorded key uses the resolved route pattern, e.g.
        # ``GET /health/``. We don't pin the literal here so the assert
        # survives any future routing-prefix tweak.
        health_buckets = [
            entry
            for key, entry in endpoints.items()
            if key.startswith("GET ") and "health" in key
        ]
        assert health_buckets, f"no health bucket among {list(endpoints)}"
        assert health_buckets[0]["count"] >= 3


class TestPercentilesBoundedByMax:
    """``statistics.quantiles`` with the default exclusive method can
    return values above the observed max for tiny windows. The
    middleware must use the inclusive method so percentiles never
    exceed ``max_ms``."""

    def test_endpoint_p95_p99_at_or_below_max(self) -> None:
        m = EndpointMetrics()
        m.record(10.0)
        m.record(20.0)

        assert m.p95_ms <= m.max_ms, (
            f"p95={m.p95_ms} exceeds max={m.max_ms}"
        )
        assert m.p99_ms <= m.max_ms, (
            f"p99={m.p99_ms} exceeds max={m.max_ms}"
        )

    def test_summary_p95_at_or_below_max_observed(
        self, client: TestClient
    ) -> None:
        """Pool a tiny number of samples and confirm the global p95
        doesn't exceed any individual recorded latency."""
        # Two requests, one bucket. The pooled p95 should fall inside
        # the observed range, not above it.
        client.get("/health/")
        client.get("/health/")

        summary = metrics_service.get_summary_stats()
        # ``get_summary_stats`` rounds ``p95_ms`` to 2 decimals; compare
        # against an equivalently-rounded max so a sub-millisecond
        # difference between two near-identical samples doesn't fail
        # the bound check on rounding alone. The math itself is
        # validated unrounded in the endpoint-level test above.
        all_max = round(
            max(
                (m.max_ms for m in metrics_service._metrics.values()),
                default=0.0,
            ),
            2,
        )
        assert summary["p95_ms"] <= all_max, (
            f"summary p95={summary['p95_ms']} exceeds observed max={all_max}"
        )


class TestSelfReferentialRoutesNotRecorded:
    """Hitting ``/api/v1/metrics/*`` is how the Performance tab reads
    the data. Recording those requests would let the tab inflate its
    own numbers every time the user opens it."""

    def test_metrics_summary_not_recorded(self, client: TestClient) -> None:
        # Auth-gated endpoint, but the middleware records *regardless*
        # of response status. A 401 still gets timed under current code,
        # which is the bug.
        client.get("/api/v1/metrics/summary")

        keys = list(metrics_service.get_all_metrics())
        offending = [k for k in keys if "metrics/summary" in k]
        assert offending == [], (
            f"/api/v1/metrics/summary was recorded: {offending}"
        )

    def test_metrics_endpoints_not_recorded(self, client: TestClient) -> None:
        client.get("/api/v1/metrics/endpoints")

        keys = list(metrics_service.get_all_metrics())
        offending = [k for k in keys if "metrics/endpoints" in k]
        assert offending == [], (
            f"/api/v1/metrics/endpoints was recorded: {offending}"
        )


class TestUnmatchedRoutesShareOneBucket:
    """Without a stable fallback, every novel 404 path allocates its
    own metric key. A scanner could exhaust process memory by walking
    a wordlist of nonsense paths."""

    def test_three_distinct_garbage_paths_collapse(
        self, client: TestClient
    ) -> None:
        client.get("/this-route-does-not-exist-1")
        client.get("/this-route-does-not-exist-2")
        client.get("/this-route-does-not-exist-3")

        endpoints = metrics_service.get_all_metrics()
        # All three should land in one bucket, not three.
        unmatched_keys = [
            (key, entry)
            for key, entry in endpoints.items()
            if "this-route-does-not-exist" in key
            or "__unmatched__" in key
        ]
        assert len(unmatched_keys) == 1, (
            f"expected 1 unmatched bucket, got: {[k for k, _ in unmatched_keys]}"
        )
        assert unmatched_keys[0][1]["count"] == 3


class TestFailingRequestsAreTimed:
    """If a route raises, the timing branch in dispatch must still
    record the sample. Otherwise 500s are invisible to anyone watching
    the Performance tab — which is exactly when you'd want to see them."""

    def test_exception_is_still_recorded(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> None:
            raise RuntimeError("simulated failure")

        # The app is shared: the route is gone after the test.
        monkeypatch.setattr(app.router, "routes", list(app.router.routes))
        app.add_api_route("/__perf_test_boom", _boom, methods=["GET"])

        client = TestClient(app, raise_server_exceptions=True)
        with pytest.raises(RuntimeError):
            client.get("/__perf_test_boom")

        endpoints = metrics_service.get_all_metrics()
        boom_buckets = [
            entry
            for key, entry in endpoints.items()
            if "__perf_test_boom" in key
        ]
        assert boom_buckets, (
            f"no bucket for failing route in {list(endpoints)}"
        )
        assert boom_buckets[0]["count"] == 1
