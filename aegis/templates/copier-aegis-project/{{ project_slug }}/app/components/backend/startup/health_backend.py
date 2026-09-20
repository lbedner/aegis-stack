"""The backend's own health check: routes, middleware, lifecycle, timings.

Two shapes come out of here, because the question differs. Under
pytest the app may never have been introspected, so "healthy" means
"the component imported" and any metadata is a bonus. In production the
check runs inside the running app, so executing at all proves liveness
and the metadata is the point.
"""

import os
from typing import Any

from app.core.log import logger
from app.services.backend.middleware_inspector import MiddlewareMetadata
from app.services.backend.route_inspector import RouteMetadata
from app.services.system.models import ComponentStatus, ComponentStatusType

from .health_metadata import lifecycle, route_and_middleware

_TEST_NOTE = "Backend component loaded successfully"


def _in_test_environment() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST") or "pytest" in os.getenv("_", ""))


def _healthy(message: str, metadata: dict[str, Any]) -> ComponentStatus:
    return ComponentStatus(
        name="backend",
        status=ComponentStatusType.HEALTHY,
        message=message,
        response_time_ms=None,
        metadata=metadata,
    )


def _request_metrics() -> tuple[dict[str, Any], dict[str, Any]]:
    """Local request-metrics summary (ephemeral, in-memory).

    The service is always-on and singleton; populated by the performance
    middleware. Empty until the first request lands. The summary is the
    cross-endpoint roll-up shown on the Server card; the per-endpoint
    detail is what the modal's Performance tab consumes.
    """
    try:
        from app.components.backend.middleware.performance import metrics_service

        return metrics_service.get_summary_stats(), metrics_service.get_all_metrics()
    except Exception:
        return {}, {}


def _test_mode_status(
    route_metadata: RouteMetadata | None,
    middleware_metadata: MiddlewareMetadata | None,
) -> ComponentStatus:
    """Healthy either way; the metadata is whatever introspection managed."""
    if route_metadata is None or middleware_metadata is None:
        return _healthy(
            "FastAPI backend available (test mode)",
            {
                "type": "component_check",
                "environment": "test",
                "note": _TEST_NOTE,
                "route_introspection": "unavailable",
                "middleware_introspection": "unavailable",
            },
        )

    # Create message with both route and middleware info
    message_parts = [f"{route_metadata.total_routes} routes"]
    if middleware_metadata.security_count > 0:
        message_parts.append(f"{middleware_metadata.security_count} security layers")

    return _healthy(
        f"FastAPI backend available (test mode): {', '.join(message_parts)}",
        {
            "type": "component_check",
            "environment": "test",
            "note": _TEST_NOTE,
            **route_metadata.model_dump_for_metadata(),
            **middleware_metadata.model_dump_for_metadata(),
        },
    )


def _active_message(
    route_metadata: RouteMetadata, middleware_metadata: MiddlewareMetadata
) -> str:
    """e.g. ``FastAPI backend active: 19 routes, 1 security layers, (16 GET, 3 POST)``."""
    method_summary = ", ".join(
        f"{count} {method}"
        for method, count in sorted(route_metadata.method_counts.items())
    )

    message_parts = [f"{route_metadata.total_routes} routes"]
    if route_metadata.total_endpoints != route_metadata.total_routes:
        message_parts.append(f"{route_metadata.total_endpoints} endpoints")
    if middleware_metadata.security_count > 0:
        message_parts.append(f"{middleware_metadata.security_count} security layers")
    if method_summary:
        message_parts.append(f"({method_summary})")

    return f"FastAPI backend active: {', '.join(message_parts)}"


def _production_status(
    route_metadata: RouteMetadata | None,
    middleware_metadata: MiddlewareMetadata | None,
) -> ComponentStatus:
    """Running is proven by this code executing; the rest is detail."""
    if route_metadata is None or middleware_metadata is None:
        return _healthy(
            "FastAPI backend active (introspection unavailable)",
            {
                "type": "internal_component_check",
                "note": "Backend is running but route/middleware metadata unavailable",
                "check_method": "internal_execution",
            },
        )

    performance_summary, performance_endpoints = _request_metrics()
    return _healthy(
        _active_message(route_metadata, middleware_metadata),
        {
            "type": "internal_component_check",
            "note": "Backend is running since this health check executed",
            "check_method": "internal_execution",
            **route_metadata.model_dump_for_metadata(),
            **middleware_metadata.model_dump_for_metadata(),
            "lifecycle": lifecycle(),
            "performance": performance_summary,
            "performance_endpoints": performance_endpoints,
        },
    )


async def backend_component_health() -> ComponentStatus:
    """
    FastAPI backend health check with route and middleware introspection.

    In test environment, reports as healthy since the app is loaded.
    In production, uses internal check to avoid circular dependency.
    Includes comprehensive route and middleware metadata for dashboard display.
    """
    if _in_test_environment():
        try:
            return _test_mode_status(*route_and_middleware())
        except Exception as e:
            logger.warning(
                f"Could not get route and middleware metadata in test mode: {e}"
            )
            return _healthy(
                "FastAPI backend available (test mode)",
                {
                    "type": "component_check",
                    "environment": "test",
                    "note": _TEST_NOTE,
                    "route_introspection_error": str(e),
                    "middleware_introspection_error": str(e),
                },
            )

    try:
        return _production_status(*route_and_middleware(warn_when_cold=True))
    except Exception as e:
        return ComponentStatus(
            name="backend",
            status=ComponentStatusType.UNHEALTHY,
            message=f"Backend component check failed: {str(e)}",
            response_time_ms=None,
            metadata={
                "type": "internal_component_check",
                "error": "import_or_execution_error",
                "error_details": str(e),
            },
        )
