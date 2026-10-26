"""What the AI service has spent today, over the last 7 days and in all:
the spend its node in the ontology carries (``node_now``)."""

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, time, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.core.time import today, utcnow
from app.services.ai.domains.spend import queries
from app.services.ai.domains.spend.recording import VOICE_ACTIONS
from app.services.system.node_now import HALF_CENT, UsageWindow

Usage = dict[tuple[str, str], tuple[int, int, float]]  # by vendor and action


async def spend_windows() -> tuple[UsageWindow, ...]:
    """Today, the last 7 days and all time (what the AI node carries)."""
    starts: dict[str, datetime | None] = {
        "today": datetime.combine(today(), time.min),
        "last 7 days": utcnow() - timedelta(days=7),
        "all time": None,
    }
    async with get_async_session() as session:
        return await spend_since(starts, session)


async def spend_since(
    starts: dict[str, datetime | None], session: AsyncSession
) -> tuple[UsageWindow, ...]:
    """Each window (its label, and when it starts) with what it cost by
    vendor, by action (a voice kind by its name) and by voice or text, in
    one read."""
    usage = await queries.usage_windows(session, list(starts.values()))
    return tuple(
        _window(label, since, {key: figures[i] for key, figures in usage.items()})
        for i, (label, since) in enumerate(starts.items())
    )


def _window(label: str, since: datetime | None, usage: Usage) -> UsageWindow:
    return UsageWindow(
        label=label,
        since=since,
        total_requests=sum(requests for requests, _, _ in usage.values()),
        total_tokens=sum(tokens for _, tokens, _ in usage.values()),
        total_cost=sum(cost for _, _, cost in usage.values()),
        by_vendor=_largest(usage, lambda vendor, _: vendor),
        by_action=_largest(usage, lambda _, action: VOICE_ACTIONS.get(action, action)),
        by_mode=_largest(
            usage, lambda _, action: "voice" if action in VOICE_ACTIONS else "text"
        ),
    )


def _largest(usage: Usage, name: Callable[[str, str], str]) -> dict[str, float]:
    """The cost under each ``name`` (of a vendor and an action), largest
    first; none that rounds to no cent."""
    spent: dict[str, float] = defaultdict(float)
    for (vendor, action), (_, _, cost) in usage.items():
        spent[name(vendor, action)] += cost
    kept = [(n, cost) for n, cost in spent.items() if cost >= HALF_CENT]
    return dict(sorted(kept, key=lambda item: -item[1]))
