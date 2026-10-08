"""Pydantic models for HTTP load testing.

Extends the shared base models (``BaseLoadTestConfiguration``,
``BaseLoadTestMetrics``, ``BaseLoadTestResult``) with HTTP-specific
fields: target method/path, concurrency settings, latency percentiles,
status-code distribution, and sampled error details.
"""

from typing import Literal

from app.services.load_test.common.models import (
    BaseLoadTestConfiguration,
    BaseLoadTestMetrics,
    BaseLoadTestResult,
)
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

HTTPMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]


class APILoadTestConfiguration(BaseLoadTestConfiguration):
    """Configuration for a single HTTP load-test run."""

    method: HTTPMethod = Field(..., description="HTTP method")
    path: str = Field(..., description="Path to load test (must start with /)")
    base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for out-of-process runs",
    )
    requests: int = Field(..., ge=1, description="Total requests to issue")
    clients: int = Field(..., ge=1, description="Concurrent in-flight requests")
    payload: dict | str | None = Field(
        default=None,
        description="Static payload for POST/PUT/PATCH requests",
    )
    payload_generator: str | None = Field(
        default=None,
        description="Dotted import path to a callable returning a fresh payload per request",
    )
    auth_as: str | None = Field(
        default=None,
        description="Username for CLI-driven login; the service ignores this field "
        "(headers carry the resulting bearer token).",
    )
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_s: float = Field(default=30.0, gt=0, description="Per-request timeout")
    delay_ms: int = Field(default=0, ge=0, description="Per-request throttle delay")
    in_process: bool = Field(
        default=False,
        description="If True, run against the FastAPI app via ASGITransport "
        "(no network).",
    )
    path_params: dict[str, str] = Field(
        default_factory=dict,
        description="Values substituted into ``{name}`` placeholders in ``path`` "
        "before each request is issued.",
    )

    @field_validator("method", mode="before")
    @classmethod
    def _normalize_method(cls, v: object) -> object:
        if isinstance(v, str):
            return v.upper()
        return v

    @field_validator("path")
    @classmethod
    def _path_starts_with_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("path must start with /")
        return v

    @model_validator(mode="after")
    def _payload_mutex(self) -> "APILoadTestConfiguration":
        if self.payload is not None and self.payload_generator is not None:
            raise ValueError(
                "payload and payload_generator are mutually exclusive — pick one"
            )
        return self


class ErrorSample(BaseModel):
    """A single failed request, captured for diagnostics.

    The service caps these at 100 per run so a failure storm doesn't blow
    up the result blob.
    """

    request_index: int = Field(..., ge=0, description="0-based index of the request")
    error_type: str = Field(..., description="Exception class name or HTTP<status>")
    message: str = Field(..., description="Truncated error detail")


class APILoadTestMetrics(BaseLoadTestMetrics):
    """Per-run metrics with HTTP-specific latency and status data."""

    latency_ms_p50: float = Field(default=0.0, ge=0)
    latency_ms_p95: float = Field(default=0.0, ge=0)
    latency_ms_p99: float = Field(default=0.0, ge=0)
    latency_ms_max: float = Field(default=0.0, ge=0)
    status_codes: dict[int, int] = Field(
        default_factory=dict,
        description="Mapping of HTTP status code to observed count",
    )
    errors: list[ErrorSample] = Field(
        default_factory=list,
        description="Sampled failures (capped by the service)",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def only_redirects(self) -> bool:
        """Every response a 3xx: the run measured a redirect (``/health``
        answers ``/health/``), not the route it points to."""
        codes = self.status_codes
        return bool(codes) and all(300 <= int(c) < 400 for c in codes)


class APILoadTestResult(BaseLoadTestResult):
    """Result envelope with HTTP-specific config/metrics types."""

    configuration: APILoadTestConfiguration
    metrics: APILoadTestMetrics


class RouteInfo(BaseModel):
    """One discoverable FastAPI route, returned by ``discovery.list_routes``."""

    method: str = Field(..., description="HTTP method")
    path: str = Field(..., description="Route path template")
    requires_auth: bool = Field(
        ...,
        description="True iff the route depends on the caller-supplied auth callable",
    )
    tags: list[str] = Field(default_factory=list)
    path_params: list[str] = Field(
        default_factory=list,
        description="Names of ``{...}`` placeholders in ``path``; each must be "
        "supplied via ``--path-param`` (or ``APILoadTestConfiguration.path_params``) "
        "before the route can be tested.",
    )
