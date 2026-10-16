"""What the Redis detail views show, for every frontend.

Built from the cache health check's metadata. Colours are semantic names
(green, yellow, red), which each frontend maps to its own theme.
"""

from datetime import datetime
from typing import Any

from app.services.system import redis_keys
from app.services.system.models import SlowlogEntry, SlowQuery

SLOWLOG_CRITICAL_MS = 1000
SLOWLOG_WARNING_MS = 100


def uptime(seconds: int) -> str:
    """``90061`` -> ``"1d 1h 1m"``."""
    days, rest = divmod(int(seconds or 0), 86400)
    return f"{days}d {rest // 3600}h {rest % 3600 // 60}m"


def hit_rate_color(rate: float) -> str:
    """Green from 90%, yellow from 70%, red below."""
    if rate >= 90:
        return "green"
    return "yellow" if rate >= 70 else "red"


def slowlog_color(duration_ms: float) -> str:
    """Red from a second, yellow from 100ms, green below."""
    if duration_ms >= SLOWLOG_CRITICAL_MS:
        return "red"
    return "yellow" if duration_ms >= SLOWLOG_WARNING_MS else "green"


# Script calls, shown by the keys they touched rather than the script.
SCRIPTS = {"EVAL", "EVALSHA", "EVAL_RO", "EVALSHA_RO", "FCALL", "FCALL_RO"}


def slow_command(command: str, keys: list[str]) -> str:
    """A SLOWLOG command, readable: a script call names the keys it touched
    (``keys``, as Redis named them), and UUIDs in keys are cut to their first
    block."""
    parts = command.split()
    if not parts:
        return command
    cmd = parts[0].upper()
    if cmd in SCRIPTS:
        return f"{cmd} (Lua) on {' '.join(keys) or 'unknown'}"
    return " ".join([cmd, *(_short_uuids(p) for p in parts[1:])])


def _short_uuids(part: str) -> str:
    if len(part) <= 24 or "-" not in part:
        return part
    return ":".join(
        f"{seg[:8]}..." if len(seg) == 36 and seg.count("-") == 4 else seg
        for seg in part.split(":")
    )


def _when(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return str(timestamp)


def slow_queries(metadata: dict[str, Any]) -> list[SlowQuery]:
    """The slow log (the cache health check's ``slowlog_entries``), slowest
    first, each command with what it touched: its first key (as Redis
    named them) and that key's family."""
    entries = sorted(
        (SlowlogEntry.model_validate(e) for e in metadata.get("slowlog_entries") or []),
        key=lambda e: e.duration_ms,
        reverse=True,
    )
    rows = []
    for e in entries:
        key = next(iter(e.keys), None)
        family = redis_keys.family_of(key, e.db)
        rows.append(
            SlowQuery(
                when=_when(e.timestamp),
                duration_ms=e.duration_ms,
                color=slowlog_color(e.duration_ms),
                command=slow_command(e.command, e.keys),
                full=e.command,
                key=key,
                family=family.name if family else None,
            )
        )
    return rows
