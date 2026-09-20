"""Blog service business logic."""

from sqlalchemy import func
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow

from . import queries as blog_queries
from .constants import BlogPostStatus, ImportConflictPolicy
from .models import (
    BlogHealthSummary,
    BlogPost,
    BlogPostTag,
    BlogStatus,
    BlogTag,
)
from .schemas import (
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
from .slugs import slugify
from .summary import blog_health_summary
from .tags import set_post_tags
from .transfer import export_posts as _export_posts
from .transfer import import_posts as _import_posts


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
            tag_slug = slugify(tag)
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
        tags_by_post = await blog_queries.tags_for_posts(self.db, [p.id for p in posts])
        responses = [
            self._build_post_response(post, tags_by_post.get(post.id, []))
            for post in posts
        ]
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
        await set_post_tags(self.db, post.id, payload.tag_slugs)  # type: ignore[arg-type]
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
            await set_post_tags(self.db, post_id, payload.tag_slugs)
        await self.db.flush()
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

        # ``canonical_url`` is not persisted — see import_posts create path.

    async def get_health_summary(self) -> BlogHealthSummary:
        """Return counts and latest activity for health metadata."""
        return await blog_health_summary(self.db)

    async def export_posts(
        self,
        *,
        slugs: list[str] | None = None,
        status: str | None = None,
    ) -> list[ExportedPost]:
        """Return all (or filtered) posts as portable, ID-free payloads."""
        return await _export_posts(self.db, slugs=slugs, status=status)

    async def import_posts(
        self,
        posts: list[ImportedPost],
        *,
        on_conflict: ImportConflictPolicy = ImportConflictPolicy.SKIP,
    ) -> ImportResult:
        """Create or update posts from portable payloads."""
        return await _import_posts(self.db, posts, on_conflict=on_conflict)

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

    async def _post_response(self, post: BlogPost) -> BlogPostResponse:
        """Single-post path. A page of one, so it reuses the batch query."""
        grouped = await blog_queries.tags_for_posts(self.db, [post.id])
        return self._build_post_response(post, grouped.get(post.id, []))

    def _build_post_response(
        self, post: BlogPost, tags: list[BlogTag]
    ) -> BlogPostResponse:
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
