"""The backend's health check says the same thing after the split.

``component_health`` was one 690-line module holding the registry, four
checks and three caches; the checks now live in ``health_backend`` and
``health_components`` and read the caches through accessors rather than
through ``global``. Nothing else pins the two things that move when that
goes wrong: the summary line the Server card renders, and the fact that
a check running before the startup hook fills the cache itself instead
of reporting "unavailable" forever.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest

from app.components.backend.startup import health_metadata
from app.components.backend.startup.health_backend import (
    _active_message,
    backend_component_health,
)
from app.services.system.models import ComponentStatusType


class _Route:
    """The three numbers ``_active_message`` reads off route metadata."""

    def __init__(
        self, total_routes: int, total_endpoints: int, method_counts: dict[str, int]
    ) -> None:
        self.total_routes = total_routes
        self.total_endpoints = total_endpoints
        self.method_counts = method_counts

    def model_dump_for_metadata(self) -> dict[str, Any]:
        return {"total_routes": self.total_routes}


class _Middleware:
    def __init__(self, security_count: int) -> None:
        self.security_count = security_count

    def model_dump_for_metadata(self) -> dict[str, Any]:
        return {"security_count": self.security_count}


def test_the_summary_names_routes_security_and_methods() -> None:
    message = _active_message(_Route(19, 19, {"GET": 16, "POST": 3}), _Middleware(1))
    assert message == (
        "FastAPI backend active: 19 routes, 1 security layers, (16 GET, 3 POST)"
    )


def test_endpoints_are_named_only_when_they_differ_from_routes() -> None:
    """Same number twice is noise on a card with one line to spend."""
    assert "endpoints" not in _active_message(_Route(19, 19, {}), _Middleware(0))
    assert "12 endpoints" in _active_message(_Route(19, 12, {}), _Middleware(0))


def test_security_layers_are_omitted_when_there_are_none() -> None:
    assert "security" not in _active_message(_Route(4, 4, {}), _Middleware(0))


@pytest.fixture
def cold_cache() -> Any:
    """Whatever the process already cached, forgotten for one test."""
    saved = (
        health_metadata._cached_route_metadata,
        health_metadata._cached_middleware_metadata,
    )
    health_metadata._cached_route_metadata = None
    health_metadata._cached_middleware_metadata = None
    yield
    (
        health_metadata._cached_route_metadata,
        health_metadata._cached_middleware_metadata,
    ) = saved


def test_a_cold_cache_fills_itself_rather_than_reporting_unavailable(
    cold_cache: None,
) -> None:
    """The startup hook primes this, but a check can run before it does."""
    route, middleware = health_metadata.route_and_middleware()
    assert route is not None and middleware is not None
    assert route.total_routes > 0


async def test_an_uninspectable_app_is_still_healthy(cold_cache: None) -> None:
    """No introspection is a missing detail, not a down backend."""
    with patch.object(health_metadata, "get_configured_app", return_value=None):
        status = await backend_component_health()

    assert status.status == ComponentStatusType.HEALTHY
    assert "unavailable" in status.message or "unavailable" in str(status.metadata)


async def test_production_mode_reports_lifecycle_and_performance() -> None:
    """The Server card's modal reads both keys; test mode never has them."""
    # patch.dict restores the whole environment on exit, deletion included.
    with patch.dict(os.environ, {"_": "/usr/bin/probe"}, clear=False):
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        status = await backend_component_health()

    assert status.status == ComponentStatusType.HEALTHY
    assert "lifecycle" in status.metadata
    assert "performance" in status.metadata
