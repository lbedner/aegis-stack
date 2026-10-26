"""What the research service holds, as figures (``app.core.aggregates``):
how many items each source found, of each kind, never which."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ranges
from app.core.aggregates import Aggregate, tally
from app.core.figures import FIGURES
from app.services.research.queries import item_counts


class ResearchItems(BaseModel):
    """Live items fetched in the window, by source and by kind."""

    model_config = FIGURES

    by_source: dict[str, int]
    by_kind: dict[str, int]


async def items(session: AsyncSession, days: int | None) -> ResearchItems:
    rows = await item_counts(session, ranges.start(days))
    by_source, by_kind = tally(rows, 2)
    return ResearchItems(by_source=by_source, by_kind=by_kind)


AGGREGATES = (Aggregate("items", "Research finds by source and kind", items),)
