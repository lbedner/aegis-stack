"""What the insights service holds, as figures (``app.core.aggregates``):
each source's daily metrics summed over a window, never a row's notes."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ranges
from app.core.aggregates import Aggregate
from app.core.figures import FIGURES
from app.services.insights import queries


class DailyTotals(BaseModel):
    """Each source's daily metrics (clones, views, downloads...) summed
    over the window, by source key, then metric key."""

    model_config = FIGURES

    by_source: dict[str, dict[str, float]]


async def daily(session: AsyncSession, days: int | None) -> DailyTotals:
    by_source: dict[str, dict[str, float]] = {}
    for source, metric, total in await queries.daily_totals(
        session, ranges.start(days)
    ):
        by_source.setdefault(source, {})[metric] = total
    return DailyTotals(by_source=by_source)


AGGREGATES = (
    Aggregate("daily", "Each source's daily metrics, summed over the window", daily),
)
