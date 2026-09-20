"""Attaching tags to a post, creating the ones that are new."""

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .models import (
    BlogPostTag,
    BlogTag,
)
from .slugs import slugify


async def get_or_create_tag(db: AsyncSession, raw_slug: str) -> BlogTag:
    slug = slugify(raw_slug)
    result = await db.exec(select(BlogTag).where(BlogTag.slug == slug))
    existing = result.first()
    if existing:
        return existing

    name = raw_slug.strip() or slug.replace("-", " ").title()
    tag = BlogTag(name=name, slug=slug)
    db.add(tag)
    await db.flush()
    return tag


async def set_post_tags(db: AsyncSession, post_id: int, tag_slugs: list[str]) -> None:
    await db.exec(delete(BlogPostTag).where(BlogPostTag.post_id == post_id))
    seen: set[str] = set()
    for raw_slug in tag_slugs:
        slug = slugify(raw_slug)
        if slug in seen:
            continue
        seen.add(slug)
        tag = await get_or_create_tag(db, raw_slug)
        db.add(
            BlogPostTag(
                post_id=post_id,
                tag_id=tag.id,  # type: ignore[arg-type]
            )
        )
    await db.flush()
