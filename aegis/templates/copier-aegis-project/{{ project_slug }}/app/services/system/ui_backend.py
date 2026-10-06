"""What the backend detail views show, for every frontend.

Shared by the Flet backend modal and the web Overseer's Server page so both
group, order and summarise the same way. No UI framework imports.
"""

from typing import Any

UNTAGGED = "Untagged"


def route_groups(
    routes: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Routes grouped by first tag, alphabetically, untagged last; each by path."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for route in routes:
        tags = route.get("tags") or [UNTAGGED]
        groups.setdefault(tags[0], []).append(route)
    names = sorted(name for name in groups if name != UNTAGGED)
    if UNTAGGED in groups:
        names.append(UNTAGGED)
    return [
        (name, sorted(groups[name], key=lambda r: str(r.get("path", ""))))
        for name in names
    ]


def endpoints_by_traffic(
    endpoints: dict[str, dict[str, Any]],
) -> list[tuple[str, str, dict[str, Any]]]:
    """``(method, path, stats)`` per ``"<METHOD> <path>"`` key, busiest first."""
    rows = []
    for key, stats in endpoints.items():
        method, _, path = key.partition(" ")
        rows.append((method, path or key, stats or {}))
    return sorted(rows, key=lambda row: int(row[2].get("count", 0) or 0), reverse=True)


def load_test_summary(runs: list[dict[str, Any]]) -> dict[str, float]:
    """Mean throughput and p95, and total failures, across load-test runs."""

    def metric(run: dict[str, Any], key: str) -> float:
        value = (run.get("metrics") or {}).get(key)
        return float(value) if isinstance(value, int | float) else 0.0

    count = len(runs)
    return {
        "runs": count,
        "throughput": sum(metric(r, "overall_throughput") for r in runs) / count
        if count
        else 0.0,
        "p95": sum(metric(r, "latency_ms_p95") for r in runs) / count if count else 0.0,
        "failures": int(sum(metric(r, "tasks_failed") for r in runs)),
    }


def _lifecycle_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """One hook or middleware: its name, module, and inspector details."""
    module = str(entry.get("module", ""))
    details: dict[str, Any] = {}
    if description := str(entry.get("description", "") or ""):
        details["Description"] = description
    if module:
        details["Module"] = module
    config = entry.get("config")
    if isinstance(config, dict):
        details.update(config)
    return {
        "name": str(entry.get("type") or entry.get("name") or "unknown"),
        "module": module,
        "security": bool(entry.get("is_security", False)),
        "details": details,
    }


def lifecycle(metadata: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Startup hooks, middleware (outermost first) and shutdown hooks."""
    hooks = metadata.get("lifecycle") or {}
    sources = {
        "startup": hooks.get("startup_hooks") or [],
        "middleware": metadata.get("middleware_stack") or [],
        "shutdown": hooks.get("shutdown_hooks") or [],
    }
    return {
        key: [_lifecycle_entry(e) for e in entries] for key, entries in sources.items()
    }


def dominant_source_message(dominant: dict[str, Any]) -> str:
    """The warning shown when one source IP dominates traffic."""
    share = int(round(float(dominant.get("share", 0.0) or 0.0) * 100))
    requests = int(dominant.get("requests", 0) or 0)
    return (
        f"One source is dominating: {dominant.get('ip')} - "
        f"{share}% of traffic ({requests:,} requests)"
    )


def endpoints_apart(routes: int, endpoints: int) -> int | None:
    """The endpoints (each route's methods counted), or None where they
    would repeat the routes (every route one method): the Server's tile in
    both UIs and its health check's message show them only apart."""
    return endpoints if endpoints != routes else None


def method_summary(metadata: dict[str, Any]) -> str:
    """Route counts per HTTP method, e.g. ``29 GET, 11 POST``."""
    counts = metadata.get("method_counts") or {}
    return ", ".join(f"{count} {method}" for method, count in counts.items())
