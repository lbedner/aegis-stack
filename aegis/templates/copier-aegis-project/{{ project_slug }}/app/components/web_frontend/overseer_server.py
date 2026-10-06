"""Context for the Overseer Server page's sections.

The same six views as the Flet backend modal's tabs. Overview, Routes and Lifecycle
read the backend's health metadata; Performance, Traffic and Load Tests read
the sources behind their API routes, as of this request.
"""

from typing import Any

from app.components.backend.api.load_test_api import recent_runs
from app.components.backend.api.traffic import get_traffic_sources
from app.components.backend.middleware.performance import metrics_service
from app.core import runtime
from app.core.formatting import format_relative_time
from app.core.log import logger
from app.services.system import ui_backend, ui_cache
from app.services.system.models import ComponentStatus

from . import overseer_connections
from .overseer_nav import SectionRequest
from .rendering import status_cell

SECTIONS = (
    (None, {"overview": "Overview"}),
    (
        "Monitoring",
        {
            "performance": "Performance",
            "traffic": "Traffic",
            "cache": "Cache",
            "connections": "Connections",
            "load-tests": "Load Tests",
        },
    ),
    ("Application", {"routes": "Routes", "lifecycle": "Lifecycle"}),
)


def _one_decimal(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Round the named figures for display; the table macro prints values as-is."""
    return row | {key: f"{float(row.get(key) or 0):.1f}" for key in keys}


def _endpoint_rows(endpoints: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for method, path, stats in ui_backend.endpoints_by_traffic(endpoints):
        row = stats | {"method": method, "path": path}
        row["last"] = format_relative_time(row.get("last_request_at"))
        ms = ("min_ms", "avg_ms", "median_ms", "p95_ms", "p99_ms", "max_ms")
        rows.append(_one_decimal(row, *ms))
    return rows


def route_rows(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One table row per route: badges for auth and deprecation."""
    return [
        route
        | {
            "auth": status_cell("Auth", "warn") if route.get("requires_auth") else None,
            "state": status_cell("Deprecated", "warn")
            if route.get("deprecated")
            else None,
        }
        for route in routes
    ]


def _traffic(snapshot: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for source in snapshot.get("sources") or []:
        share = float(source.get("share") or 0) * 100
        sources.append(
            source | {"share_pct": f"{share:.0f}%", "share_detail": f"{share:.1f}%"}
        )
    dominant = snapshot.get("dominant")
    message = ui_backend.dominant_source_message(dominant) if dominant else None
    return snapshot | {"sources": sources, "dominant_message": message}


async def _load_test_runs() -> tuple[list[dict[str, Any]], bool]:
    """Recent runs, and whether the result store could be read."""
    try:
        return await recent_runs(limit=50), True
    except Exception as exc:  # the store is optional; show why it is empty
        logger.warning("Overseer could not read load-test runs", error=str(exc))
        return [], False


def _run_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten each run's configuration and metrics into one table row."""
    rows = []
    for run in runs:
        row = {
            **(run.get("configuration") or {}),
            **(run.get("metrics") or {}),
            "test_id": run.get("test_id"),
            "when": format_relative_time(run.get("start_time")),
        }
        row["error_pct"] = f"{float(row.get('failure_rate_percent') or 0):.1f}%"
        row["throughput"] = f"{float(row.get('overall_throughput') or 0):.0f}"
        row["duration"] = f"{float(row.get('total_duration_seconds') or 0):.3f}s"
        ms = ("latency_ms_p50", "latency_ms_p95", "latency_ms_p99", "latency_ms_max")
        rows.append(_one_decimal(row, *ms))
    return rows


def overview_context(backend: ComponentStatus) -> dict[str, Any]:
    """The Overview's context, shared by the page and its SSE refresh. With
    containers to read, the glance above it has the server's own figures
    and the host's are on Resources; without, the machine it runs on is
    all there is to show."""
    metadata = backend.metadata or {}
    return {
        "methods": ui_backend.method_summary(metadata),
        "endpoints": ui_backend.endpoints_apart(
            metadata.get("total_routes", 0), metadata.get("total_endpoints", 0)
        ),
        "host_figures": not runtime.deployed(),
    }


async def section_context(
    section: str, backend: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs beyond the backend status."""
    metadata = backend.metadata or {}
    if section == "overview":
        return overview_context(backend)
    if section == "cache":
        return {"cache": await ui_cache.load()}
    if section == "connections":
        return await overseer_connections.section_context(dict(req.query))
    if section == "routes":
        groups = [
            (name, route_rows(routes))
            for name, routes in ui_backend.route_groups(metadata.get("routes") or [])
        ]
        return {"route_groups": groups, "groups_open": len(groups) <= 5}
    if section == "lifecycle":
        steps = ui_backend.lifecycle(metadata)
        badge = status_cell("Security", "warn")
        return {
            "lifecycle": {
                key: [
                    entry | {"role": badge if entry["security"] else None}
                    for entry in entries
                ]
                for key, entries in steps.items()
            }
        }
    if section == "performance":
        return {
            "summary": metrics_service.get_summary_stats(),
            "endpoints": _endpoint_rows(metrics_service.get_all_metrics()),
        }
    if section == "traffic":
        return {
            "traffic": _traffic(await get_traffic_sources(window_hours=None, limit=20))
        }
    if section == "load-tests":
        runs, available = await _load_test_runs()
        return {
            "runs": _run_rows(runs),
            "run_summary": ui_backend.load_test_summary(runs),
            "runs_available": available,
        }
    return {}
