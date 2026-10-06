"""A component's health as the worse of its own check and Docker's
healthcheck on the containers behind it. The two can disagree: Traefik
answering its API while Docker's healthcheck on it fails is degraded, not
healthy, so it reads as a warning. A check that already fails keeps its own
reason, the more specific one.

It reads the containers sampler's last reading (``ui_runtime``), so the
health walk waits on no Docker call; before the first reading, or with no
deploy target, nothing changes. Docker's healthcheck output is not read:
the socket proxy refuses container inspect, which would also hand over
every container's environment. No UI framework imports.
"""

from app.core import series
from app.services.system import ui_runtime

from .models import ComponentStatus, ComponentStatusType

# What Docker's failing healthcheck leaves a passing check at.
_PASSING = (ComponentStatusType.HEALTHY, ComponentStatusType.INFO)


async def overlay(checks: dict[str, ComponentStatus]) -> dict[str, ComponentStatus]:
    """``checks`` (by health component name), each one with a container
    Docker calls unhealthy at least a warning."""
    tables = await series.latest(ui_runtime.SAMPLER) or {}
    sick = {
        ui_runtime.component_of(page): names
        for page, view in tables.items()
        if (names := [r["name"] for r in view["rows"] if r["health"] == "unhealthy"])
    }
    return {
        name: _flagged(check, sick[name]) if name in sick else check
        for name, check in checks.items()
    }


def _flagged(check: ComponentStatus, containers: list[str]) -> ComponentStatus:
    if check.status not in _PASSING:
        return check
    names = ", ".join(containers)
    return check.model_copy(
        update={
            "status": ComponentStatusType.WARNING,
            "message": f"Docker's healthcheck fails on {names}",
        }
    )
