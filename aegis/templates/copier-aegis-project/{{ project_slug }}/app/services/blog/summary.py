"""Counts and latest activity, for the health surface."""

from datetime import timedelta

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow

from . import queries as blog_queries
from .constants import STALE_DRAFT_DAYS, BlogPostStatus
from .models import (
    BlogHealthSummary,
    BlogPost,
    BlogTag,
)


async def blog_health_summary(db: AsyncSession) -> BlogHealthSummary:
    """Return counts and latest activity for health metadata."""
    by_status = await blog_queries.count_posts_by_status(db)
    draft = by_status.get(BlogPostStatus.DRAFT, 0)
    published = by_status.get(BlogPostStatus.PUBLISHED, 0)
    archived = by_status.get(BlogPostStatus.ARCHIVED, 0)
    total = sum(by_status.values())

    tag_count_result = await db.exec(select(func.count()).select_from(BlogTag))
    tag_count = int(tag_count_result.one() or 0)

    stale_cutoff = utcnow() - timedelta(days=STALE_DRAFT_DAYS)
    stale_result = await db.exec(
        select(func.count())
        .select_from(BlogPost)
        .where(BlogPost.status == BlogPostStatus.DRAFT)
        .where(BlogPost.updated_at < stale_cutoff)
    )
    stale_draft_count = int(stale_result.one() or 0)

    latest_result = await db.exec(
        select(BlogPost)
        .where(BlogPost.status == BlogPostStatus.PUBLISHED)
        .order_by(BlogPost.published_at.desc())
        .limit(1)
    )
    latest = latest_result.first()
    latest_payload = None
    if latest:
        latest_payload = {
            "id": latest.id,
            "title": latest.title,
            "slug": latest.slug,
            "published_at": latest.published_at.isoformat()
            if latest.published_at
            else None,
        }

    return BlogHealthSummary(
        total_posts=total,
        draft_posts=draft,
        published_posts=published,
        archived_posts=archived,
        tag_count=tag_count,
        stale_draft_count=stale_draft_count,
        latest_published_post=latest_payload,
    )
