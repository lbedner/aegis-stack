"""A component's health as the worst of its own check and what the
containers behind it say: Docker's healthcheck failing on one (Traefik
answering its API while Docker's healthcheck on it fails is degraded, not
healthy, so it reads as a warning), or one's memory past its alert share
(``MEMORY_THRESHOLD_PERCENT``: unhealthy, as its red bar says) or nearing
it (a warning). Not CPU: one reading over is a spike, not a fault, and an
unhealthy component sends a health alert. A check already as bad keeps its
own reason, the more specific one.

It reads the containers sampler's last reading (``ui_runtime``), so the
health walk waits on no Docker call; before the first reading, or with no
deploy target, nothing changes. Docker's healthcheck output is not read:
the socket proxy refuses container inspect, which would also hand over
every container's environment. No UI framework imports.
"""

from collections.abc import Iterator
from typing import Any

from app.core import series
from app.services.system import ui_runtime

from .models import ComponentStatus, ComponentStatusType

_TROUBLED = (ComponentStatusType.WARNING, ComponentStatusType.UNHEALTHY)
_Trouble = tuple[ComponentStatusType, str]


async def overlay(checks: dict[str, ComponentStatus]) -> dict[str, ComponentStatus]:
    """``checks`` (by health component name), each one raised to the worst
    its containers say."""
    tables = await series.latest(ui_runtime.SAMPLER) or {}
    troubles: dict[str, list[_Trouble]] = {}
    for page, view in tables.items():
        troubles.setdefault(ui_runtime.component_of(page), []).extend(
            trouble for row in view["rows"] for trouble in _troubles(row)
        )
    return {
        name: _worst(check, troubles.get(name, [])) for name, check in checks.items()
    }


def _troubles(row: dict[str, Any]) -> Iterator[_Trouble]:
    name = row["name"]
    if row["health"] == "unhealthy":
        yield ComponentStatusType.WARNING, f"Docker's healthcheck fails on {name}"
    if (memory := row.get("memory_status")) in _TROUBLED:
        figure = ui_runtime.FIGURES[ui_runtime.MEMORY]
        yield ComponentStatusType(memory), f"{figure} high on {name}"


def _worst(check: ComponentStatus, troubles: list[_Trouble]) -> ComponentStatus:
    from .health import propagate_status  # health imports this module

    worst = propagate_status([check.status, *(status for status, _ in troubles)])
    if worst == check.status:
        return check
    reasons = "; ".join(reason for status, reason in troubles if status == worst)
    return check.model_copy(update={"status": worst, "message": reasons})
