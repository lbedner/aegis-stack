"""What the Redis detail views show, for every frontend.

Built from the cache health check's metadata. Colours are semantic names
(green, yellow, red), which each frontend maps to its own theme.
"""

from datetime import datetime
from typing import Any

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


def slow_command(command: str) -> str:
    """A SLOWLOG command, readable: Lua calls name their keys, and UUIDs in
    keys are cut to their first block."""
    parts = command.split()
    if not parts:
        return command
    cmd = parts[0].upper()
    if cmd == "EVALSHA" and len(parts) >= 4:
        keys = parts[3 : 3 + int(parts[2])] if parts[2].isdigit() else []
        return f"EVALSHA (Lua) on {' '.join(keys) or 'unknown'}"
    return " ".join([cmd, *(_short_uuids(p) for p in parts[1:])])


def _short_uuids(part: str) -> str:
    if len(part) <= 24 or "-" not in part:
        return part
    return ":".join(
        f"{seg[:8]}..." if len(seg) == 36 and seg.count("-") == 4 else seg
        for seg in part.split(":")
    )


def _when(timestamp: Any) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError, TypeError):
        return str(timestamp)


def slow_queries(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """The slow log, slowest first."""
    entries = sorted(
        metadata.get("slowlog_entries") or [],
        key=lambda e: e.get("duration_ms", 0),
        reverse=True,
    )
    return [
        {
            "when": _when(e.get("timestamp", 0)),
            "duration_ms": e.get("duration_ms", 0),
            "color": slowlog_color(e.get("duration_ms", 0)),
            "command": slow_command(e.get("command", "")),
            "full": e.get("command", ""),
        }
        for e in entries
    ]
