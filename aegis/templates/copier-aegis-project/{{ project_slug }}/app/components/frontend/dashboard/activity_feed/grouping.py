"""Collapsing a run of like events into one row.

A burst of the same event from the same source reads as noise; one
row saying it happened N times reads as information.
"""

from dataclasses import dataclass

from app.services.system.activity import ActivityEvent

GROUP_THRESHOLD = 2

_STATUS_SEVERITY: dict[str, int] = {
    "success": 0,
    "healthy": 0,
    "info": 1,
    "warning": 2,
    "error": 3,
    "unhealthy": 3,
}


@dataclass
class EventGroup:
    """UI-only grouping of consecutive same-component events."""

    component: str
    events: list[ActivityEvent]  # newest first (matches feed order)

    @property
    def count(self) -> int:
        return len(self.events)

    @property
    def latest_event(self) -> ActivityEvent:
        return self.events[0]

    @property
    def worst_status(self) -> str:
        """Return the most severe status in the group."""
        worst = "success"
        worst_sev = 0
        for event in self.events:
            sev = _STATUS_SEVERITY.get(event.status.lower(), 0)
            if sev > worst_sev:
                worst_sev = sev
                worst = event.status
        return worst

    @property
    def group_key(self) -> str:
        """Key based on component + count + oldest event timestamp.

        Count is included so the key changes when new events join the group,
        forcing refresh to rebuild the row instead of reusing the stale one.
        """
        oldest = self.events[-1]
        return f"{self.component}:{self.count}:{oldest.timestamp.isoformat()}"


def group_consecutive_events(
    events: list[ActivityEvent],
) -> list[ActivityEvent | EventGroup]:
    """Group consecutive same-component events into EventGroups.

    Single O(n) pass. Runs of fewer than GROUP_THRESHOLD are passed through
    as individual events.
    """
    if not events:
        return []

    result: list[ActivityEvent | EventGroup] = []
    run: list[ActivityEvent] = [events[0]]

    for event in events[1:]:
        if event.component == run[0].component:
            run.append(event)
        else:
            _flush_run(run, result)
            run = [event]

    _flush_run(run, result)
    return result


def _flush_run(
    run: list[ActivityEvent],
    result: list[ActivityEvent | EventGroup],
) -> None:
    """Flush accumulated run into result list."""
    if len(run) >= GROUP_THRESHOLD:
        result.append(EventGroup(component=run[0].component, events=run))
    else:
        result.extend(run)


def _item_key(item: ActivityEvent | EventGroup) -> str:
    """Return a stable string key for an event or group."""
    if isinstance(item, EventGroup):
        return item.group_key
    return item.timestamp.isoformat()
