"""
Unit tests for HTTP load-test Pydantic models.

Models extend the common base (``BaseLoadTestConfiguration``,
``BaseLoadTestMetrics``, ``BaseLoadTestResult``) with HTTP-specific fields:
target method/path, concurrency settings, latency percentiles, and
status-code distribution.

The shared cross-field validators from the base classes (e.g.
``tasks_completed <= tasks_sent``) are already exercised in
``test_load_test_common.py``; these tests focus on the HTTP-specific
additions and overrides.
"""

import pytest
from app.services.load_test.api.models import (
    ErrorSample,
    APILoadTestConfiguration,
    APILoadTestMetrics,
    APILoadTestResult,
    RouteInfo,
)
from pydantic import ValidationError


def _valid_metrics(**overrides) -> APILoadTestMetrics:
    defaults = {
        "tasks_sent": 100,
        "tasks_completed": 100,
        "tasks_failed": 0,
        "total_duration_seconds": 1.0,
        "overall_throughput": 100.0,
        "failure_rate_percent": 0.0,
        "completion_percentage": 100.0,
        "latency_ms_p50": 10.0,
        "latency_ms_p95": 25.0,
        "latency_ms_p99": 40.0,
        "latency_ms_max": 50.0,
        "status_codes": {200: 100},
        "errors": [],
    }
    defaults.update(overrides)
    return APILoadTestMetrics(**defaults)


def _valid_config(**overrides) -> APILoadTestConfiguration:
    defaults = {
        "method": "GET",
        "path": "/health",
        "requests": 100,
        "clients": 10,
    }
    defaults.update(overrides)
    return APILoadTestConfiguration(**defaults)


class TestAPILoadTestConfiguration:
    """Configuration validation: method, path, payload, concurrency."""

    def test_minimal_valid_config(self):
        config = _valid_config()
        assert config.method == "GET"
        assert config.path == "/health"
        assert config.requests == 100
        assert config.clients == 10
        assert config.base_url == "http://localhost:8000"
        assert config.in_process is False
        assert config.timeout_s == 30.0

    def test_method_case_normalized_to_upper(self):
        """Lowercase methods are accepted and normalized — most users type
        ``get`` not ``GET`` on the CLI."""
        config = _valid_config(method="post")
        assert config.method == "POST"

    def test_method_must_be_http_verb(self):
        with pytest.raises(ValidationError):
            _valid_config(method="FETCH")

    def test_path_must_start_with_slash(self):
        with pytest.raises(ValidationError, match="path"):
            _valid_config(path="health")

    def test_path_can_have_query_params(self):
        config = _valid_config(path="/users?limit=10")
        assert config.path == "/users?limit=10"

    def test_requests_must_be_positive(self):
        with pytest.raises(ValidationError):
            _valid_config(requests=0)

    def test_clients_must_be_positive(self):
        with pytest.raises(ValidationError):
            _valid_config(clients=0)

    def test_payload_accepts_dict(self):
        config = _valid_config(method="POST", payload={"message": "hi"})
        assert config.payload == {"message": "hi"}

    def test_payload_accepts_string(self):
        config = _valid_config(method="POST", payload='{"raw": "json"}')
        assert config.payload == '{"raw": "json"}'

    def test_payload_and_generator_are_mutually_exclusive(self):
        """Specifying both is a mistake — caller doesn't know which wins.
        Reject at validation time."""
        with pytest.raises(ValidationError, match="payload"):
            _valid_config(
                method="POST",
                payload={"a": 1},
                payload_generator="app.payloads:gen",
            )

    def test_headers_default_empty(self):
        config = _valid_config()
        assert config.headers == {}

    def test_headers_accept_dict(self):
        config = _valid_config(headers={"X-Custom": "v"})
        assert config.headers == {"X-Custom": "v"}

    def test_timeout_must_be_positive(self):
        with pytest.raises(ValidationError):
            _valid_config(timeout_s=0)
        with pytest.raises(ValidationError):
            _valid_config(timeout_s=-1)

    def test_delay_ms_can_be_zero(self):
        config = _valid_config(delay_ms=0)
        assert config.delay_ms == 0

    def test_delay_ms_cannot_be_negative(self):
        with pytest.raises(ValidationError):
            _valid_config(delay_ms=-1)

    def test_inherits_test_id_from_base(self):
        config = _valid_config(test_id="abc-123")
        assert config.test_id == "abc-123"


class TestAPILoadTestMetrics:
    """Adds latency percentiles + status-code distribution + error samples
    on top of the shared metrics base."""

    def test_valid_metrics(self):
        m = _valid_metrics()
        assert m.latency_ms_p50 == 10.0
        assert m.latency_ms_p95 == 25.0
        assert m.status_codes == {200: 100}

    def test_latency_fields_must_be_non_negative(self):
        for field in ("latency_ms_p50", "latency_ms_p95", "latency_ms_p99", "latency_ms_max"):
            with pytest.raises(ValidationError):
                _valid_metrics(**{field: -1.0})

    def test_status_codes_default_empty(self):
        m = _valid_metrics(
            tasks_sent=0,
            tasks_completed=0,
            tasks_failed=0,
            total_duration_seconds=0.0,
            overall_throughput=0.0,
            completion_percentage=0.0,
            status_codes={},
        )
        assert m.status_codes == {}

    def test_errors_default_empty(self):
        m = _valid_metrics()
        assert m.errors == []

    def test_error_samples_attach(self):
        samples = [
            ErrorSample(request_index=5, error_type="ConnectError", message="boom"),
            ErrorSample(request_index=12, error_type="Timeout", message="slow"),
        ]
        m = _valid_metrics(
            tasks_completed=98, tasks_failed=2, failure_rate_percent=2.0,
            completion_percentage=98.0, errors=samples,
        )
        assert len(m.errors) == 2
        assert m.errors[0].error_type == "ConnectError"

    def test_inherits_completed_le_sent_validator(self):
        with pytest.raises(ValidationError, match="completed"):
            _valid_metrics(tasks_sent=10, tasks_completed=11)


class TestErrorSample:
    def test_valid(self):
        e = ErrorSample(request_index=0, error_type="ConnectError", message="refused")
        assert e.request_index == 0
        assert e.error_type == "ConnectError"
        assert e.message == "refused"

    def test_request_index_non_negative(self):
        with pytest.raises(ValidationError):
            ErrorSample(request_index=-1, error_type="X", message="y")


class TestAPILoadTestResult:
    """The result envelope tightens config/metrics to the HTTP-specific
    subtypes and inherits status/error consistency from the base."""

    def _result(self, **overrides) -> APILoadTestResult:
        defaults = {
            "status": "completed",
            "test_id": "tid-1",
            "configuration": _valid_config(test_id="tid-1"),
            "metrics": _valid_metrics(),
        }
        defaults.update(overrides)
        return APILoadTestResult(**defaults)

    def test_valid_result(self):
        result = self._result()
        assert isinstance(result.configuration, APILoadTestConfiguration)
        assert isinstance(result.metrics, APILoadTestMetrics)

    def test_inherits_status_error_validator(self):
        with pytest.raises(ValidationError, match="error"):
            self._result(status="failed", error=None)

    def test_json_round_trip_preserves_http_fields(self):
        """``RedisResultStore`` round-trips results through JSON; latency
        percentiles, status codes, and error samples must survive."""
        original = self._result(
            metrics=_valid_metrics(
                latency_ms_p50=11.5, latency_ms_p95=88.2,
                status_codes={200: 95, 500: 5},
                tasks_completed=95, tasks_failed=5, failure_rate_percent=5.0,
                completion_percentage=95.0,
                errors=[ErrorSample(request_index=0, error_type="X", message="y")],
            )
        )
        blob = original.model_dump_json()
        loaded = APILoadTestResult.model_validate_json(blob)
        assert loaded.metrics.latency_ms_p50 == 11.5
        assert loaded.metrics.status_codes == {200: 95, 500: 5}
        assert loaded.metrics.errors[0].error_type == "X"


class TestRouteInfo:
    """Returned by ``discovery.list_routes``; one per (method, path) combo."""

    def test_valid(self):
        info = RouteInfo(
            method="GET", path="/api/users", requires_auth=True, tags=["users"]
        )
        assert info.method == "GET"
        assert info.requires_auth is True
        assert info.tags == ["users"]

    def test_tags_default_empty(self):
        info = RouteInfo(method="GET", path="/health", requires_auth=False)
        assert info.tags == []

    def test_path_params_default_empty(self):
        """Routes without ``{...}`` placeholders carry an empty list."""
        info = RouteInfo(method="GET", path="/health", requires_auth=False)
        assert info.path_params == []

    def test_path_params_populated(self):
        info = RouteInfo(
            method="GET",
            path="/api/v1/tasks/status/{task_id}",
            requires_auth=False,
            path_params=["task_id"],
        )
        assert info.path_params == ["task_id"]


class TestAPILoadTestConfigurationPathParams:
    """``path_params`` lets the CLI substitute ``{name}`` placeholders.

    Values are pure strings; the service interpolates them into the path
    template at request time. Missing substitutions surface as a
    ValueError from the service (tested in test_api_load_test_service.py).
    """

    def test_path_params_default_empty(self):
        config = _valid_config()
        assert config.path_params == {}

    def test_path_params_accepts_string_values(self):
        config = _valid_config(
            path="/api/v1/tasks/status/{task_id}",
            path_params={"task_id": "abc-123"},
        )
        assert config.path_params == {"task_id": "abc-123"}

    def test_path_params_roundtrip_through_json(self):
        """Stored configs ride through JSON in Redis; the dict must survive."""
        original = _valid_config(
            path="/api/v1/items/{item_id}/owner/{user_id}",
            path_params={"item_id": "42", "user_id": "u-9"},
        )
        loaded = APILoadTestConfiguration.model_validate_json(
            original.model_dump_json()
        )
        assert loaded.path_params == {"item_id": "42", "user_id": "u-9"}


class TestOnlyRedirects:
    """``/health`` answers 307 to ``/health/``: a run of it measured the
    redirect, and says so wherever it is shown."""

    def test_every_response_a_redirect(self) -> None:
        assert _valid_metrics(status_codes={307: 100}).only_redirects

    def test_some_reached_the_route(self) -> None:
        assert not _valid_metrics(status_codes={200: 99, 307: 1}).only_redirects

    def test_it_travels_with_the_result(self) -> None:
        assert _valid_metrics(status_codes={301: 5}).model_dump()["only_redirects"]
