"""Reads that span a page of posts rather than one. Writes stay in
``service.py``.

Both of these replaced a per-row query: tags were fetched one post at a
time while building a listing, and the health summary issued one COUNT
per status. A 20-post page cost 22 queries and ``page_size`` allows 100.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.blog.models import BlogPost, BlogPostTag, BlogTag


async def tags_for_posts(
    db: AsyncSession, post_ids: list[int | None]
) -> dict[int, list[BlogTag]]:
    """Every listed post's tags in one query, grouped by post id.

    A post with no tags is absent from the mapping rather than present
    with an empty list, so callers use ``.get(post_id, [])``.
    """
    ids = [post_id for post_id in post_ids if post_id is not None]
    if not ids:
        return {}
    result = await db.exec(
        select(BlogPostTag.post_id, BlogTag)
        .join(BlogTag, BlogTag.id == BlogPostTag.tag_id)
        .where(BlogPostTag.post_id.in_(ids))  # type: ignore[attr-defined]
        .order_by(BlogTag.name)
    )
    grouped: dict[int, list[BlogTag]] = {}
    for post_id, tag in result.all():
        grouped.setdefault(post_id, []).append(tag)
    return grouped


async def count_posts_by_status(db: AsyncSession) -> dict[str, int]:
    """One row per status, rather than one COUNT per status."""
    result = await db.exec(
        select(BlogPost.status, func.count()).group_by(BlogPost.status)  # type: ignore[arg-type]
    )
    return {str(status): int(count) for status, count in result.all()}
