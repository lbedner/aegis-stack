"""What the document store holds, as figures (``app.core.aggregates``):
how many documents carry each tag, never which."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ranges
from app.core.aggregates import Aggregate
from app.core.figures import FIGURES
from app.services.documents.queries import tag_counts


class DocumentTags(BaseModel):
    """Live documents stored in the window, by tag."""

    model_config = FIGURES

    by_tag: dict[str, int]


async def tags(session: AsyncSession, days: int | None) -> DocumentTags:
    found = await tag_counts(session, since=ranges.start(days))
    return DocumentTags(by_tag=dict(found))


AGGREGATES = (Aggregate("tags", "Documents by tag", tags),)
