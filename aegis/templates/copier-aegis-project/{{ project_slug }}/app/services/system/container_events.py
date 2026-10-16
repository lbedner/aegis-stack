"""What happened to a container between two readings of the containers
sampler (``ui_runtime``): it restarted, it stopped, its health check failed
or recovered. Each is a point on its page's Events chart, kept with the
rest of the containers' history (``series``). A restart is the uptime
starting over: Docker's list has no restart count.
"""

from typing import Any

RESTART, EXIT, UNHEALTHY, RECOVERED = "restart", "exit", "unhealthy", "recovered"
# Each event's line on the chart: (series metric, what it says).
EVENTS = (
    (RESTART, "restarted"),
    (EXIT, "exited"),
    (UNHEALTHY, "unhealthy"),
    (RECOVERED, "recovered"),
)
STOPPED = ("exited", "dead")


def changes(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, float]:
    """The events between two readings' page tables, as series points
    (``page:name:event``); none on the first reading or for a container
    the earlier one did not have."""
    if not before:
        return {}
    found: dict[str, float] = {}
    for page, table in after.items():
        was = {row["name"]: row for row in (before.get(page) or {}).get("rows", [])}
        for row in table.get("rows", []):
            if (old := was.get(row["name"])) is not None:
                for event in _between(old, row):
                    found[f"{page}:{row['name']}:{event}"] = 1.0
    return found


def _between(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    events = []
    running = new.get("phase") == "running"
    if running and (
        old.get("phase") != "running"
        or (new.get("uptime_seconds") or 0) < (old.get("uptime_seconds") or 0)
    ):
        events.append(RESTART)
    if old.get("phase") == "running" and new.get("phase") in STOPPED:
        events.append(EXIT)
    if new.get("health") == "unhealthy" and old.get("health") != "unhealthy":
        events.append(UNHEALTHY)
    elif old.get("health") == "unhealthy" and new.get("health") == "healthy":
        events.append(RECOVERED)
    return events
