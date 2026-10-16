"""A container's row in a page's table, as both UIs show it: its state,
uptime and image, and its live figures, whole (``memory``) and in parts
(``memory_used``), each against what the container has of it."""

from typing import Any

from app.core import thresholds
from app.core.config import settings
from app.core.formatting import format_bytes, format_percentage, format_span
from app.core.runtime import Instance, Stats
from app.services.system.container_events import STOPPED


def row(instance: Instance, stats: Stats | None) -> dict[str, Any]:
    """One instance's row; a stopped one (no stats) has the same keys."""
    return {
        "name": instance.name,
        "id": instance.id,
        **_state(instance),
        # Its parts too, for a view that shows them apart (htmx's cards).
        "phase": instance.state,
        "health": instance.health or "",
        "restarts": "-" if instance.restarts is None else str(instance.restarts),
        "uptime": format_span(instance.uptime_seconds) or "-",
        # What the next reading compares with (``container_events``).
        "uptime_seconds": instance.uptime_seconds,
        "image": " ".join(p for p in (instance.image, instance.build) if p) or "-",
    } | _figures(stats)


def _state(instance: Instance) -> dict[str, str]:
    """Its word and status (read like ``cpu_status``): stopped is down; a
    failing healthcheck while it serves, or starting, is a warning."""
    if instance.state in STOPPED:
        code = instance.exit_code
        word = instance.state if code is None else f"{instance.state} ({code})"
        return {"state": word, "state_status": "unhealthy"}
    sick = instance.health == "unhealthy"
    fine = instance.state == "running" and not sick
    word = "unhealthy" if sick else instance.state
    return {"state": word, "state_status": "healthy" if fine else "warning"}


# A stopped container's live figures: none.
_LIVE = (
    "cpu_value",
    "memory_value",
    "memory_percent",
    "cpu_status",
    "memory_status",
    "cpu_capacity",
    "memory_capacity",
)
_FIGURES = (
    "cpu",
    "memory",
    "network",
    "disk",
    "memory_used",
    "network_in",
    "network_out",
    "disk_read",
    "disk_write",
)


def _figures(stats: Stats | None) -> dict[str, Any]:
    """A row's live figures, whole (``memory``) and in parts (``memory_used``)."""
    if stats is None:
        return (
            dict.fromkeys(_FIGURES, "-") | dict.fromkeys(_LIVE) | {"memory_limit": ""}
        )
    used, limit = format_bytes(stats.memory_used), stats.memory_limit
    rx, tx = format_bytes(stats.network_rx), format_bytes(stats.network_tx)
    read, write = format_bytes(stats.disk_read), format_bytes(stats.disk_write)
    return {
        "cpu": "-"
        if stats.cpu_percent is None
        else format_percentage(stats.cpu_percent),
        "memory": f"{used} / {format_bytes(limit)}" if limit else used,
        "network": f"in {rx}, out {tx}",
        "disk": f"read {read}, write {write}",
        "memory_used": used,
        # The raw figures, for what sums them (``ui_resources``).
        "cpu_value": stats.cpu_percent,
        "memory_value": stats.memory_used,
        # Creeping toward the limit is what kills a container.
        "memory_percent": round(stats.memory_used / limit * 100, 1) if limit else None,
        "memory_limit": format_bytes(limit) if limit else "",
        "network_in": rx,
        "network_out": tx,
        "disk_read": read,
        "disk_write": write,
        # Each figure against what the container has of it, by the host
        # checks' rule, and that capacity (for the charts' threshold lines).
        "cpu_status": _status(
            stats.cpu_percent, stats.cpus * 100, "CPU_THRESHOLD_PERCENT"
        ),
        "memory_status": _status(stats.memory_used, limit, "MEMORY_THRESHOLD_PERCENT"),
        "cpu_capacity": stats.cpus * 100,
        "memory_capacity": limit,
    }


def _status(value: float | None, capacity: float | None, setting: str) -> str | None:
    """``value``'s share of ``capacity`` against the ``setting`` alert share."""
    if value is None or not capacity:
        return None
    return thresholds.status(value / capacity * 100, getattr(settings, setting)).value
