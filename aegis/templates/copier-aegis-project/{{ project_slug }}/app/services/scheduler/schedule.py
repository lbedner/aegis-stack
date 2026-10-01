"""How a scheduled job's trigger reads, for every scheduler backend.

The persistent backend reads jobs from the job store and the in-memory one
from the live scheduler; both describe a trigger here, so the dashboard says
the same thing about the same job either way.
"""

from typing import Any, Literal

TriggerKind = Literal["interval", "cron", "date", "unknown"]


def _every(seconds: float) -> str:
    if seconds < 60:
        return f"Every {int(seconds)}s"
    if seconds < 3600:
        return f"Every {int(seconds / 60)}m"
    if seconds < 86400:
        hours = seconds / 3600
        return f"Every {int(hours)}h" if hours == int(hours) else f"Every {hours:.1f}h"
    return f"Every {int(seconds / 86400)}d"


def _cron(trigger: Any) -> str:
    parts = [f"{field.name}={field}" for field in trigger.fields if str(field) != "*"]
    return "Cron: " + ", ".join(parts) if parts else "Cron: * * * * *"


def describe_trigger(trigger: Any) -> str:
    """A trigger in words: "Every 5m", "Cron: hour=2, minute=0", "Once at ..."."""
    if not trigger:
        return "Unknown"
    kind = type(trigger).__name__
    if kind == "IntervalTrigger" and hasattr(trigger, "interval"):
        return _every(trigger.interval.total_seconds())
    if kind == "CronTrigger" and hasattr(trigger, "fields"):
        return _cron(trigger)
    if kind == "DateTrigger" and hasattr(trigger, "run_date"):
        return f"Once at {trigger.run_date.strftime('%Y-%m-%d %H:%M:%S')}"
    return kind.replace("Trigger", "")


def trigger_kind(trigger: Any) -> TriggerKind:
    """``interval``, ``cron``, ``date``, or ``unknown``."""
    name = type(trigger).__name__ if trigger else ""
    if "Interval" in name:
        return "interval"
    if "Cron" in name:
        return "cron"
    if "Date" in name:
        return "date"
    return "unknown"
