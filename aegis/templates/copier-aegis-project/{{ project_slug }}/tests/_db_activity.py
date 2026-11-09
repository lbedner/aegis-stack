"""Slow & locked records, for a test: described and kept as ``_record``
describes and keeps one (``db_activity.describe``, ``db_activity.store``)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core import db_activity


def event(
    caller: str,
    *,
    seconds: float | None = 2.5,
    ago: float = 0,
    kind: str = "slow",
    process: str = "worker:7",
) -> dict[str, Any]:
    at = datetime.now(UTC) - timedelta(seconds=ago)
    return db_activity.describe(kind, seconds, process, caller, at)


async def kept(*events: dict[str, Any]) -> None:
    """Kept oldest first, as they happened."""
    for entry in sorted(events, key=lambda e: e["at"]):
        await db_activity.store(entry)
