"""What the meetings service holds, as figures (``app.core.aggregates``):
how many meetings are in each status and on each platform, never which."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ranges
from app.core.aggregates import Aggregate, tally
from app.core.figures import FIGURES
from app.services.meetings.queries import status_platform_counts


class Meetings(BaseModel):
    """Meetings asked for in the window, by status and by platform."""

    model_config = FIGURES

    by_status: dict[str, int]
    by_platform: dict[str, int]


async def meetings(session: AsyncSession, days: int | None) -> Meetings:
    rows = await status_platform_counts(session, ranges.start(days))
    by_status, by_platform = tally(rows, 2)
    return Meetings(by_status=by_status, by_platform=by_platform)


AGGREGATES = (Aggregate("meetings", "Meetings by status and platform", meetings),)
