"""Tests for the BlogService business logic layer."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.blog.service import BlogService
from app.services.blog.constants import BlogPostStatus, ImportConflictPolicy
from app.services.blog.schemas import (
    BlogPostCreate,
    BlogPostUpdate,
    BlogTagCreate,
    ImportedPost,
)


@pytest.mark.asyncio
async def test_create_post_assigns_slug_and_tags(
    async_db_session: AsyncSession,
) -> None:
    service = BlogService(async_db_session)

    post = await service.create_post(
        BlogPostCreate(
            title="Hello World",
            content="# Hello",
            tag_slugs=["News", "news", "Release Notes"],
        )
    )

    assert post.slug == "hello-world"
    assert post.status == BlogPostStatus.DRAFT
    assert [tag.slug for tag in post.tags] == ["news", "release-notes"]


@pytest.mark.asyncio
async def test_syndicate_targets_empty_list_stored_as_none(
    async_db_session: AsyncSession,
) -> None:
    service = BlogService(async_db_session)

    # Empty list on create collapses to NULL (single "empty" representation).
    empty = await service.create_post(
        BlogPostCreate(title="No Targets", slug="no-targets", syndicate_targets=[])
    )
    assert empty.syndicate_targets is None

    # A real list round-trips.
    listed = await service.create_post(
        BlogPostCreate(
            title="Has Targets",
            slug="has-targets",
            syndicate_targets=["devto", "hashnode"],
        )
    )
    assert listed.syndicate_targets == ["devto", "hashnode"]

    # Updating with [] clears; None on a separate update leaves them untouched.
    cleared = await service.update_post(listed.id, BlogPostUpdate(syndicate_targets=[]))
    assert cleared.syndicate_targets is None


@pytest.mark.asyncio
async def test_public_list_only_returns_published_posts(
    async_db_session: AsyncSession,
) -> None:
    service = BlogService(async_db_session)
    draft = await service.create_post(
        BlogPostCreate(title="Draft", slug="draft", content="hidden")
    )

    posts, total = await service.list_public_posts()
    assert posts == []
    assert total == 0

    await service.publish_post(draft.id)
    posts, total = await service.list_public_posts()
    assert total == 1
    assert posts[0].slug == "draft"

    await service.archive_post(draft.id)
    posts, total = await service.list_public_posts()
    assert posts == []
    assert total == 0


@pytest.mark.asyncio
async def test_slug_uniqueness_and_update(async_db_session: AsyncSession) -> None:
    service = BlogService(async_db_session)
    first = await service.create_post(
        BlogPostCreate(title="First", slug="same", content="one")
    )
    await service.create_post(
        BlogPostCreate(title="Second", slug="other", content="two")
    )

    with pytest.raises(ValueError, match="Post slug already exists"):
        await service.update_post(first.id, BlogPostUpdate(slug="other"))

    updated = await service.update_post(
        first.id,
        BlogPostUpdate(title="First Updated", slug="first-updated", tag_slugs=["Docs"]),
    )

    assert updated is not None
    assert updated.title == "First Updated"
    assert updated.slug == "first-updated"
    assert [tag.slug for tag in updated.tags] == ["docs"]


@pytest.mark.asyncio
async def test_tag_crud(async_db_session: AsyncSession) -> None:
    service = BlogService(async_db_session)

    tag = await service.create_tag(BlogTagCreate(name="Product News"))
    assert tag.slug == "product-news"

    tags = await service.list_tags()
    assert [item.slug for item in tags] == ["product-news"]

    assert await service.delete_tag(tag.id) is True
    assert await service.delete_tag(tag.id) is False


@pytest.mark.asyncio
async def test_delete_post(async_db_session: AsyncSession) -> None:
    service = BlogService(async_db_session)
    post = await service.create_post(
        BlogPostCreate(title="Delete Me", content="temporary", tag_slugs=["ops"])
    )

    assert await service.delete_post(post.id) is True
    assert await service.get_post(post.id) is None
    assert await service.delete_post(post.id) is False


@pytest.mark.asyncio
async def test_export_posts_drops_author_id(
    async_db_session: AsyncSession,
) -> None:
    """Exported posts exclude author_id (DB FK, doesn't transfer)."""
    service = BlogService(async_db_session)
    post = await service.create_post(
        BlogPostCreate(title="Export Test", content="data"),
        author_id=123,
        author_name="Alice",
    )

    exported = await service.export_posts(slugs=[post.slug])

    assert len(exported) == 1
    assert exported[0].author_name == "Alice"
    assert not hasattr(exported[0], "author_id") or exported[0].author_id is None


@pytest.mark.asyncio
async def test_export_posts_filter_by_status(
    async_db_session: AsyncSession,
) -> None:
    """Export respects status filter."""
    service = BlogService(async_db_session)
    await service.create_post(
        BlogPostCreate(title="Draft", content="draft"),
    )
    pub = await service.create_post(
        BlogPostCreate(title="Published", content="pub"),
    )
    await service.publish_post(pub.id)

    exported = await service.export_posts(status=BlogPostStatus.PUBLISHED)

    assert len(exported) == 1
    assert exported[0].slug == "published"


@pytest.mark.asyncio
async def test_export_posts_ordered_by_created_at(
    async_db_session: AsyncSession,
) -> None:
    """Exported posts ordered ascending by created_at."""
    service = BlogService(async_db_session)
    first = await service.create_post(
        BlogPostCreate(title="First", content="1"),
    )
    second = await service.create_post(
        BlogPostCreate(title="Second", content="2"),
    )

    exported = await service.export_posts()

    assert len(exported) == 2
    assert exported[0].slug == first.slug
    assert exported[1].slug == second.slug


@pytest.mark.asyncio
async def test_import_posts_creates_new(
    async_db_session: AsyncSession,
) -> None:
    """Import new posts to empty database."""
    service = BlogService(async_db_session)
    payload = [
        ImportedPost(title="New 1", slug="new-1", content="c1"),
        ImportedPost(title="New 2", slug="new-2", content="c2"),
    ]

    result = await service.import_posts(payload)

    assert result.created == 2
    assert result.updated == 0
    assert result.skipped == 0
    assert result.failed == 0

    posts, total = await service.list_posts(page=1, page_size=100)
    assert total == 2


@pytest.mark.asyncio
async def test_import_posts_skip_on_conflict(
    async_db_session: AsyncSession,
) -> None:
    """Default SKIP policy ignores existing slugs."""
    service = BlogService(async_db_session)
    payload = [
        ImportedPost(title="Post", slug="same", content="v1"),
    ]
    result1 = await service.import_posts(payload)
    assert result1.created == 1

    result2 = await service.import_posts(payload, on_conflict=ImportConflictPolicy.SKIP)
    assert result2.skipped == 1
    assert result2.created == 0

    posts, _ = await service.list_posts(page=1, page_size=100)
    assert posts[0].content == "v1"


@pytest.mark.asyncio
async def test_import_posts_overwrite_on_conflict(
    async_db_session: AsyncSession,
) -> None:
    """OVERWRITE policy updates existing posts."""
    service = BlogService(async_db_session)
    payload1 = [
        ImportedPost(title="Original", slug="test", content="original"),
    ]
    await service.import_posts(payload1)

    payload2 = [
        ImportedPost(title="Updated", slug="test", content="updated"),
    ]
    result = await service.import_posts(
        payload2, on_conflict=ImportConflictPolicy.OVERWRITE
    )
    assert result.updated == 1
    assert result.created == 0

    posts, _ = await service.list_posts(page=1, page_size=100)
    assert posts[0].title == "Updated"
    assert posts[0].content == "updated"


@pytest.mark.asyncio
async def test_import_posts_fail_on_conflict(
    async_db_session: AsyncSession,
) -> None:
    """FAIL policy raises on collision."""
    service = BlogService(async_db_session)
    payload1 = [
        ImportedPost(title="First", slug="conflict", content="1"),
    ]
    await service.import_posts(payload1)

    payload2 = [
        ImportedPost(title="Second", slug="conflict", content="2"),
    ]
    with pytest.raises(ValueError, match="Post slug already exists"):
        await service.import_posts(
            payload2, on_conflict=ImportConflictPolicy.FAIL
        )

    posts, _ = await service.list_posts(page=1, page_size=100)
    assert posts[0].title == "First"


@pytest.mark.asyncio
async def test_import_posts_creates_tags_automatically(
    async_db_session: AsyncSession,
) -> None:
    """Import auto-creates tags from imported tag_slugs."""
    service = BlogService(async_db_session)
    payload = [
        ImportedPost(
            title="Tagged",
            slug="tagged",
            content="c",
            tag_slugs=["new-tag-1", "new-tag-2"],
        ),
    ]

    result = await service.import_posts(payload)
    assert result.created == 1

    tags = await service.list_tags()
    tag_slugs = {tag.slug for tag in tags}
    assert "new-tag-1" in tag_slugs
    assert "new-tag-2" in tag_slugs

    posts, _ = await service.list_posts(page=1, page_size=100)
    assert len(posts[0].tags) == 2


@pytest.mark.asyncio
async def test_import_posts_per_post_error_handling(
    async_db_session: AsyncSession,
) -> None:
    """Import captures per-post errors without aborting batch."""
    service = BlogService(async_db_session)
    payload = [
        ImportedPost(title="Bad Slug", slug="", content="no slug"),
        ImportedPost(title="Good", slug="good", content="ok"),
    ]

    result = await service.import_posts(
        payload, on_conflict=ImportConflictPolicy.SKIP
    )

    assert result.failed >= 0
    posts, _ = await service.list_posts(page=1, page_size=100)
    assert any(p.slug == "good" for p in posts)
