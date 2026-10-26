"""What the blog holds, as figures (``app.core.aggregates``): how many
posts are in each status, never which."""

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ranges
from app.core.aggregates import Aggregate
from app.core.figures import FIGURES
from app.services.blog.queries import count_posts_by_status


class BlogPosts(BaseModel):
    """Posts written in the window, by status."""

    model_config = FIGURES

    by_status: dict[str, int]


async def posts(session: AsyncSession, days: int | None) -> BlogPosts:
    found = await count_posts_by_status(session, since=ranges.start(days))
    return BlogPosts(by_status=found)


AGGREGATES = (Aggregate("posts", "Blog posts by status", posts),)
