"""Turning the usage payload into what the sections read."""

from datetime import UTC, datetime
from typing import Any


def _transform_api_response(api_data: dict[str, Any]) -> dict[str, Any]:
    """Transform API response to UI-expected format.

    API field names differ slightly from what the UI components expect:
    - models[].model_id -> models[].name
    - models[].percentage -> models[].pct
    - recent_activity -> recent
    - recent_activity[].timestamp -> recent[].time (time portion only)
    """
    # Transform models
    models = []
    for m in api_data.get("models", []):
        models.append(
            {
                "name": m.get("model_id", "Unknown"),
                "vendor": m.get("vendor", "unknown"),
                "requests": m.get("requests", 0),
                "tokens": m.get("tokens", 0),
                "cost": m.get("cost", 0.0),
                "pct": m.get("percentage", 0),
            }
        )

    # Transform recent activity
    recent = []
    for r in api_data.get("recent_activity", []):
        recent.append(
            {
                "timestamp": r.get("timestamp", ""),
                "model": r.get("model", "Unknown"),
                "action": r.get("action", ""),
                "input_tokens": r.get("input_tokens", 0),
                "output_tokens": r.get("output_tokens", 0),
                "cost": r.get("cost", 0.0),
                "success": r.get("success", True),
                # ``.get`` with no default: these are nullable in the
                # ledger and a missing value must stay missing, so the
                # drawer can show a dash instead of inventing a zero.
                "duration_ms": r.get("duration_ms"),
                "cache_read_tokens": r.get("cache_read_tokens"),
                "cache_write_tokens": r.get("cache_write_tokens"),
                "tool_calls": r.get("tool_calls"),
                "user_id": r.get("user_id"),
                "error_message": r.get("error_message"),
            }
        )

    return {
        "total_tokens": api_data.get("total_tokens", 0),
        "input_tokens": api_data.get("input_tokens", 0),
        "output_tokens": api_data.get("output_tokens", 0),
        "total_cost": api_data.get("total_cost", 0.0),
        "total_requests": api_data.get("total_requests", 0),
        "success_rate": api_data.get("success_rate", 100.0),
        "models": models,
        "recent": recent,
    }


def _format_relative_time(timestamp_str: str) -> str:
    """Convert ISO timestamp to relative time (e.g., '2 minutes ago')."""
    try:
        # Parse ISO format timestamp
        if "T" in timestamp_str:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        else:
            return timestamp_str

        # Make timezone-aware if naive
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        diff = now - dt

        seconds = int(diff.total_seconds())
        if seconds < 0:
            return "just now"
        elif seconds < 60:
            return f"{seconds} seconds ago" if seconds != 1 else "1 second ago"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minutes ago" if minutes != 1 else "1 minute ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hours ago" if hours != 1 else "1 hour ago"
        else:
            days = seconds // 86400
            return f"{days} days ago" if days != 1 else "1 day ago"
    except (ValueError, AttributeError):
        return timestamp_str
