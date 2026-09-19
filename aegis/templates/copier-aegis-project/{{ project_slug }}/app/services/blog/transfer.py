"""Posts out and posts back in, as portable payloads."""

from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.time import utcnow

from . import queries as blog_queries
from .constants import BlogPostStatus, ImportConflictPolicy
from .models import (
    BlogPost,
)
from .schemas import (
    BlogImportError,
    ExportedPost,
    ImportedPost,
    ImportResult,
)
from .slugs import slugify
from .tags import set_post_tags


async def export_posts(
    db: AsyncSession,
    *,
    slugs: list[str] | None = None,
    status: str | None = None,
) -> list[ExportedPost]:
    """Return all (or filtered) posts as portable, ID-free payloads.

    ``author_id`` is intentionally omitted (FK to the source project's
    user table — does not transfer cleanly across projects).
    """
    query = select(BlogPost).order_by(BlogPost.created_at.asc())
    if status:
        query = query.where(BlogPost.status == status)
    if slugs is not None:
        normalized = [slugify(s) for s in slugs]
        query = query.where(BlogPost.slug.in_(normalized))  # type: ignore[attr-defined]

    result = await db.exec(query)
    posts = list(result.all())

    tags_by_post = await blog_queries.tags_for_posts(db, [p.id for p in posts])
    out: list[ExportedPost] = []
    for post in posts:
        tags = tags_by_post.get(post.id, [])
        out.append(
            ExportedPost(
                title=post.title,
                slug=post.slug,
                excerpt=post.excerpt,
                content=post.content,
                status=str(post.status),
                author_name=post.author_name,
                created_at=post.created_at,
                updated_at=post.updated_at,
                published_at=post.published_at,
                seo_title=post.seo_title,
                seo_description=post.seo_description,
                hero_image_url=post.hero_image_url,
                syndicate_targets=post.syndicate_targets,
                # Origin URL, recomputed from PUBLIC_BASE_URL every export so
                # syndicated copies (Dev.to/Hashnode read this frontmatter
                # key) point rel=canonical back here. Built from the
                # normalized ``post.slug`` — the canonical form the
                # /blog/{slug} page resolves to.
                canonical_url=(
                    f"{settings.PUBLIC_BASE_URL.rstrip('/')}/blog/{post.slug}"
                ),
                tag_slugs=[tag.slug for tag in tags],
            )
        )
    return out


@staticmethod
def _coerce_import_status(value: str | None) -> str:
    if value in BlogPostStatus.ALL:
        return value  # type: ignore[return-value]
    return BlogPostStatus.DRAFT


def _apply_imported_fields(
    post: BlogPost,
    payload: ImportedPost,
    *,
    now: datetime,
) -> None:
    post.title = payload.title
    post.excerpt = payload.excerpt
    post.content = payload.content or ""
    post.status = _coerce_import_status(payload.status)
    if payload.author_name is not None:
        post.author_name = payload.author_name
    if payload.created_at is not None:
        post.created_at = payload.created_at
    post.updated_at = payload.updated_at or now
    post.published_at = payload.published_at
    post.seo_title = payload.seo_title
    post.seo_description = payload.seo_description
    post.hero_image_url = payload.hero_image_url
    if payload.syndicate_targets is not None:
        post.syndicate_targets = payload.syndicate_targets or None


async def _get_post_by_slug_any_status(db: AsyncSession, slug: str) -> BlogPost | None:
    result = await db.exec(select(BlogPost).where(BlogPost.slug == slug))
    return result.first()


async def import_posts(
    db: AsyncSession,
    posts: list[ImportedPost],
    *,
    on_conflict: ImportConflictPolicy = ImportConflictPolicy.SKIP,
) -> ImportResult:
    """Upsert a batch of posts. Slug is the natural key.

    Runs inside the caller's session. ``ImportConflictPolicy.FAIL``
    raises on the first collision; the surrounding transaction in
    ``get_async_session`` rolls everything back.
    """
    result = ImportResult()
    now = utcnow()

    for incoming in posts:
        try:
            slug = slugify(incoming.slug or incoming.title)
            existing = await _get_post_by_slug_any_status(db, slug)

            if existing is not None:
                if on_conflict == ImportConflictPolicy.SKIP:
                    result.skipped += 1
                    continue
                if on_conflict == ImportConflictPolicy.FAIL:
                    raise ValueError(f"Post slug already exists: {slug}")
                # OVERWRITE
                _apply_imported_fields(existing, incoming, now=now)
                db.add(existing)
                await db.flush()
                await set_post_tags(
                    db,
                    existing.id,  # type: ignore[arg-type]
                    list(incoming.tag_slugs),
                )
                result.updated += 1
                continue

            created = BlogPost(
                title=incoming.title,
                slug=slug,
                excerpt=incoming.excerpt,
                content=incoming.content or "",
                status=_coerce_import_status(incoming.status),
                author_id=None,
                author_name=incoming.author_name,
                created_at=incoming.created_at or now,
                updated_at=incoming.updated_at or now,
                published_at=incoming.published_at,
                seo_title=incoming.seo_title,
                seo_description=incoming.seo_description,
                hero_image_url=incoming.hero_image_url,
                syndicate_targets=incoming.syndicate_targets or None,
                # ``canonical_url`` from the import is intentionally
                # dropped — a foreign origin must not override the local
                # one; export recomputes it from PUBLIC_BASE_URL.
            )
            db.add(created)
            await db.flush()
            await set_post_tags(
                db,
                created.id,  # type: ignore[arg-type]
                list(incoming.tag_slugs),
            )
            result.created += 1
        except Exception as exc:
            if on_conflict == ImportConflictPolicy.FAIL:
                raise
            result.failed += 1
            result.errors.append(
                BlogImportError(slug=incoming.slug or "", message=str(exc))
            )

    return result
