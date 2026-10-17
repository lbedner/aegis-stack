"""What the AI service has spent today, over the last 7 days and in all:
the spend its node in the ontology carries (``node_now``)."""

from datetime import datetime, time, timedelta

from app.core.db import get_async_session
from app.core.time import today, utcnow
from app.services.ai.domains.spend import queries
from app.services.system.node_now import UsageWindow


async def spend_windows() -> tuple[UsageWindow, ...]:
    """Each window with what it covers, read in one query."""
    starts: dict[str, datetime | None] = {
        "today": datetime.combine(today(), time.min),
        "last 7 days": utcnow() - timedelta(days=7),
        "all time": None,
    }
    async with get_async_session() as session:
        figures = await queries.usage_windows(session, list(starts.values()))
    return tuple(
        UsageWindow(
            label=label, since=since, total_requests=r, total_tokens=t, total_cost=c
        )
        for (label, since), (r, t, c) in zip(starts.items(), figures, strict=True)
    )
