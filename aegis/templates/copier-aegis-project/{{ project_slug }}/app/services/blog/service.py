"""Blog service business logic."""

import re
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.formatting import slugify as core_slugify
from app.core.config import settings
from app.core.time import utcnow

from .constants import STALE_DRAFT_DAYS, BlogPostStatus, ImportConflictPolicy
from .models import (
    BlogHealthSummary,
    BlogPost,
    BlogPostTag,
    BlogStatus,
    BlogTag,
)
from .schemas import (
    BlogImportError,
    BlogPostCreate,
    BlogPostResponse,
    BlogPostUpdate,
    BlogTagCreate,
    BlogTagResponse,
    BlogTagUpdate,
    ExportedPost,
    ImportedPost,
    ImportResult,
)


def slugify(value: str) -> str:
    """The shared slug shape, with the blog's fallback for empty titles."""
    return core_slugify(value) or "post"


def _normalize_tag_slug(value: str) -> str:
    return slugify(value)


class BlogService:
    """CRUD and workflow operations for blog posts and tags."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_public_posts(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
    ) -> tuple[list[BlogPostResponse], int]:
        """List published posts for public readers."""
        return await self.list_posts(
            page=page,
            page_size=page_size,
            status=BlogPostStatus.PUBLISHED,
            tag=tag,
        )

    async def list_posts(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        tag: str | None = None,
    ) -> tuple[list[BlogPostResponse], int]:
        """List posts with optional status and tag filtering."""
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        query = select(BlogPost).order_by(BlogPost.created_at.desc())
        count_query = select(func.count()).select_from(BlogPost)

        if status:
            query = query.where(BlogPost.status == status)
            count_query = count_query.where(BlogPost.status == status)

        if tag:
            tag_slug = _normalize_tag_slug(tag)
            query = (
                query.join(BlogPostTag, BlogPost.id == BlogPostTag.post_id)
                .join(BlogTag, BlogTag.id == BlogPostTag.tag_id)
                .where(BlogTag.slug == tag_slug)
            )
            count_query = (
                count_query.join(BlogPostTag, BlogPost.id == BlogPostTag.post_id)
                .join(BlogTag, BlogTag.id == BlogPostTag.tag_id)
                .where(BlogTag.slug == tag_slug)
            )

        total_result = await self.db.exec(count_query)
        total = int(total_result.one() or 0)

        result = await self.db.exec(
            query.offset((page - 1) * page_size).limit(page_size)
        )
        posts = list(result.all())
        responses = [await self._post_response(post) for post in posts]
        return responses, total

    async def get_public_post_by_slug(self, slug: str) -> BlogPostResponse | None:
        """Get a published post by slug."""
        post = await self._get_post_by_slug(slug, status=BlogPostStatus.PUBLISHED)
        return await self._post_response(post) if post else None

    async def get_post(self, post_id: int) -> BlogPostResponse | None:
        """Get a post by id regardless of status."""
        post = await self._get_post_model(post_id)
        return await self._post_response(post) if post else None

    async def create_post(
        self,
        payload: BlogPostCreate,
        *,
        author_id: int | None = None,
        author_name: str | None = None,
    ) -> BlogPostResponse:
        """Create a draft blog post."""
        slug = slugify(payload.slug or payload.title)
        await self._ensure_slug_available(slug)

        now = utcnow()
        post = BlogPost(
            title=payload.title,
            slug=slug,
            excerpt=payload.excerpt,
            content=payload.content,
            status=BlogStatus.DRAFT,
            author_id=author_id,
            author_name=author_name,
            created_at=now,
            updated_at=now,
            seo_title=payload.seo_title,
            seo_description=payload.seo_description,
            hero_image_url=payload.hero_image_url,
            # Empty list == not syndicated; collapse to NULL so the column
            # has a single "empty" representation (no NULL-vs-[] ambiguity
            # in queries).
            syndicate_targets=payload.syndicate_targets or None,
        )
        self.db.add(post)
        await self.db.flush()
        await self._set_post_tags(post.id, payload.tag_slugs)  # type: ignore[arg-type]
        await self.db.refresh(post)
        return await self._post_response(post)

    async def update_post(
        self,
        post_id: int,
        payload: BlogPostUpdate,
    ) -> BlogPostResponse | None:
        """Update a post and optionally replace its tag assignments."""
        post = await self._get_post_model(post_id)
        if post is None:
            return None

        if payload.title is not None:
            post.title = payload.title
        if payload.slug is not None:
            new_slug = slugify(payload.slug)
            await self._ensure_slug_available(new_slug, exclude_post_id=post_id)
            post.slug = new_slug
        if payload.excerpt is not None:
            post.excerpt = payload.excerpt
        if payload.content is not None:
            post.content = payload.content
        if payload.seo_title is not None:
            post.seo_title = payload.seo_title
        if payload.seo_description is not None:
            post.seo_description = payload.seo_description
        if payload.hero_image_url is not None:
            post.hero_image_url = payload.hero_image_url
        if payload.syndicate_targets is not None:
            # ``[]`` clears targets (stored as NULL); ``None`` leaves them
            # untouched for partial updates.
            post.syndicate_targets = payload.syndicate_targets or None

        post.updated_at = utcnow()
        self.db.add(post)
        if payload.tag_slugs is not None:
            await self._set_post_tags(post_id, payload.tag_slugs)
        await self.db.flush()
        await self.db.refresh(post)
        return await self._post_response(post)

    async def publish_post(self, post_id: int) -> BlogPostResponse | None:
        """Publish a post."""
        post = await self._get_post_model(post_id)
        if post is None:
            return None
        now = utcnow()
        post.status = BlogStatus.PUBLISHED
        post.published_at = post.published_at or now
        post.updated_at = now
        self.db.add(post)
        await self.db.flush()
        await self.db.refresh(post)
        return await self._post_response(post)

    async def archive_post(self, post_id: int) -> BlogPostResponse | None:
        """Archive a post."""
        post = await self._get_post_model(post_id)
        if post is None:
            return None
        post.status = BlogStatus.ARCHIVED
        post.updated_at = utcnow()
        self.db.add(post)
        await self.db.flush()
        await self.db.refresh(post)
        return await self._post_response(post)

    async def delete_post(self, post_id: int) -> bool:
        """Delete a post and its tag links."""
        post = await self._get_post_model(post_id)
        if post is None:
            return False
        await self.db.exec(delete(BlogPostTag).where(BlogPostTag.post_id == post_id))
        await self.db.delete(post)
        await self.db.flush()
        return True

    async def list_tags(self) -> list[BlogTagResponse]:
        """List all tags."""
        result = await self.db.exec(select(BlogTag).order_by(BlogTag.name))
        return [self._tag_response(tag) for tag in result.all()]

    async def create_tag(self, payload: BlogTagCreate) -> BlogTagResponse:
        """Create a tag."""
        slug = slugify(payload.slug or payload.name)
        await self._ensure_tag_available(name=payload.name, slug=slug)
        tag = BlogTag(name=payload.name, slug=slug)
        self.db.add(tag)
        await self.db.flush()
        await self.db.refresh(tag)
        return self._tag_response(tag)

    async def update_tag(
        self, tag_id: int, payload: BlogTagUpdate
    ) -> BlogTagResponse | None:
        """Update a tag."""
        tag = await self._get_tag_model(tag_id)
        if tag is None:
            return None
        new_name = payload.name if payload.name is not None else tag.name
        new_slug = slugify(payload.slug) if payload.slug is not None else tag.slug
        await self._ensure_tag_available(
            name=new_name, slug=new_slug, exclude_tag_id=tag_id
        )
        tag.name = new_name
        tag.slug = new_slug
        self.db.add(tag)
        await self.db.flush()
        await self.db.refresh(tag)
        return self._tag_response(tag)

    async def delete_tag(self, tag_id: int) -> bool:
        """Delete a tag and remove all post associations."""
        tag = await self._get_tag_model(tag_id)
        if tag is None:
            return False
        await self.db.exec(delete(BlogPostTag).where(BlogPostTag.tag_id == tag_id))
        await self.db.delete(tag)
        await self.db.flush()
        return True

    async def get_health_summary(self) -> BlogHealthSummary:
        """Return counts and latest activity for health metadata."""
        total = await self._count_posts()
        draft = await self._count_posts(BlogPostStatus.DRAFT)
        published = await self._count_posts(BlogPostStatus.PUBLISHED)
        archived = await self._count_posts(BlogPostStatus.ARCHIVED)

        tag_count_result = await self.db.exec(select(func.count()).select_from(BlogTag))
        tag_count = int(tag_count_result.one() or 0)

        stale_cutoff = utcnow() - timedelta(days=STALE_DRAFT_DAYS)
        stale_result = await self.db.exec(
            select(func.count())
            .select_from(BlogPost)
            .where(BlogPost.status == BlogPostStatus.DRAFT)
            .where(BlogPost.updated_at < stale_cutoff)
        )
        stale_draft_count = int(stale_result.one() or 0)

        latest_result = await self.db.exec(
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

    async def export_posts(
        self,
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

        result = await self.db.exec(query)
        posts = list(result.all())

        out: list[ExportedPost] = []
        for post in posts:
            tags = await self._get_post_tags(post.id) if post.id is not None else []  # type: ignore[arg-type]
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

    async def import_posts(
        self,
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
                existing = await self._get_post_by_slug_any_status(slug)

                if existing is not None:
                    if on_conflict == ImportConflictPolicy.SKIP:
                        result.skipped += 1
                        continue
                    if on_conflict == ImportConflictPolicy.FAIL:
                        raise ValueError(
                            f"Post slug already exists: {slug}"
                        )
                    # OVERWRITE
                    self._apply_imported_fields(existing, incoming, now=now)
                    self.db.add(existing)
                    await self.db.flush()
                    await self._set_post_tags(
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
                    status=self._coerce_import_status(incoming.status),
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
                self.db.add(created)
                await self.db.flush()
                await self._set_post_tags(
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

    @staticmethod
    def _coerce_import_status(value: str | None) -> str:
        if value in BlogPostStatus.ALL:
            return value  # type: ignore[return-value]
        return BlogPostStatus.DRAFT

    def _apply_imported_fields(
        self,
        post: BlogPost,
        payload: ImportedPost,
        *,
        now: datetime,
    ) -> None:
        post.title = payload.title
        post.excerpt = payload.excerpt
        post.content = payload.content or ""
        post.status = self._coerce_import_status(payload.status)
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
        # ``canonical_url`` is not persisted — see import_posts create path.

    async def _get_post_by_slug_any_status(self, slug: str) -> BlogPost | None:
        result = await self.db.exec(
            select(BlogPost).where(BlogPost.slug == slug)
        )
        return result.first()

    async def _count_posts(self, status: str | None = None) -> int:
        query = select(func.count()).select_from(BlogPost)
        if status:
            query = query.where(BlogPost.status == status)
        result = await self.db.exec(query)
        return int(result.one() or 0)

    async def _get_post_model(self, post_id: int) -> BlogPost | None:
        result = await self.db.exec(select(BlogPost).where(BlogPost.id == post_id))
        return result.first()

    async def _get_tag_model(self, tag_id: int) -> BlogTag | None:
        result = await self.db.exec(select(BlogTag).where(BlogTag.id == tag_id))
        return result.first()

    async def _get_post_by_slug(
        self, slug: str, *, status: str | None = None
    ) -> BlogPost | None:
        query = select(BlogPost).where(BlogPost.slug == slugify(slug))
        if status:
            query = query.where(BlogPost.status == status)
        result = await self.db.exec(query)
        return result.first()

    async def _ensure_slug_available(
        self, slug: str, *, exclude_post_id: int | None = None
    ) -> None:
        query = select(BlogPost).where(BlogPost.slug == slug)
        if exclude_post_id is not None:
            query = query.where(BlogPost.id != exclude_post_id)
        result = await self.db.exec(query)
        if result.first():
            raise ValueError(f"Post slug already exists: {slug}")

    async def _ensure_tag_available(
        self,
        *,
        name: str,
        slug: str,
        exclude_tag_id: int | None = None,
    ) -> None:
        query = select(BlogTag).where((BlogTag.slug == slug) | (BlogTag.name == name))
        if exclude_tag_id is not None:
            query = query.where(BlogTag.id != exclude_tag_id)
        result = await self.db.exec(query)
        if result.first():
            raise ValueError(f"Tag already exists: {slug}")

    async def _get_or_create_tag(self, raw_slug: str) -> BlogTag:
        slug = _normalize_tag_slug(raw_slug)
        result = await self.db.exec(select(BlogTag).where(BlogTag.slug == slug))
        existing = result.first()
        if existing:
            return existing

        name = raw_slug.strip() or slug.replace("-", " ").title()
        tag = BlogTag(name=name, slug=slug)
        self.db.add(tag)
        await self.db.flush()
        await self.db.refresh(tag)
        return tag

    async def _set_post_tags(self, post_id: int, tag_slugs: list[str]) -> None:
        await self.db.exec(delete(BlogPostTag).where(BlogPostTag.post_id == post_id))
        seen: set[str] = set()
        for raw_slug in tag_slugs:
            slug = _normalize_tag_slug(raw_slug)
            if slug in seen:
                continue
            seen.add(slug)
            tag = await self._get_or_create_tag(raw_slug)
            self.db.add(
                BlogPostTag(
                    post_id=post_id,
                    tag_id=tag.id,  # type: ignore[arg-type]
                )
            )
        await self.db.flush()

    async def _get_post_tags(self, post_id: int) -> list[BlogTag]:
        result = await self.db.exec(
            select(BlogTag)
            .join(BlogPostTag, BlogTag.id == BlogPostTag.tag_id)
            .where(BlogPostTag.post_id == post_id)
            .order_by(BlogTag.name)
        )
        return list(result.all())

    async def _post_response(self, post: BlogPost) -> BlogPostResponse:
        tags = await self._get_post_tags(post.id) if post.id is not None else []  # type: ignore[arg-type]
        return BlogPostResponse(
            id=post.id,  # type: ignore[arg-type]
            title=post.title,
            slug=post.slug,
            excerpt=post.excerpt,
            content=post.content,
            status=str(post.status),
            author_id=post.author_id,
            author_name=post.author_name,
            created_at=post.created_at,
            updated_at=post.updated_at,
            published_at=post.published_at,
            seo_title=post.seo_title,
            seo_description=post.seo_description,
            hero_image_url=post.hero_image_url,
            syndicate_targets=post.syndicate_targets,
            tags=[self._tag_response(tag) for tag in tags],
        )

    @staticmethod
    def _tag_response(tag: BlogTag) -> BlogTagResponse:
        return BlogTagResponse(
            id=tag.id,  # type: ignore[arg-type]
            name=tag.name,
            slug=tag.slug,
            created_at=tag.created_at,
        )
