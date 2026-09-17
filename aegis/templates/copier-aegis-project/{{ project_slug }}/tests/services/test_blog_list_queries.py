"""Listing posts must cost the same whether the page holds one or fifty.

``list_posts`` mapped ``_post_response`` over the page, and that helper
fetches a post's tags by id - so a 20-post page issued 20 tag queries on
top of its own two, and ``page_size`` allows 100. The public ``/blog``
index pays it on every load.

The export path and the health summary had the same shape: a per-post
tag fetch in a loop, and one COUNT per status.
"""

from __future__ import annotations

import pytest
from queryspy import assert_max_queries
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.blog.schemas import BlogPostCreate
from app.services.blog.service import BlogService

POST_COUNT = 5


async def _seed(service: BlogService, count: int = POST_COUNT) -> None:
    """Posts that each carry tags, so a per-post fetch has work to do."""
    for index in range(count):
        created = await service.create_post(
            BlogPostCreate(
                title=f"Post {index}",
                content="body",
                tag_slugs=["news", f"topic-{index}"],
            )
        )
        await service.publish_post(created.id)


class TestListingIsFlat:
    @pytest.mark.asyncio
    async def test_a_page_of_posts_costs_a_fixed_number_of_queries(
        self, async_db_session: AsyncSession
    ) -> None:
        """Count, page, tags. Three, regardless of how many posts land."""
        service = BlogService(async_db_session)
        await _seed(service)

        with assert_max_queries(3):
            posts, total = await service.list_posts(page_size=50)

        assert total == POST_COUNT
        assert len(posts) == POST_COUNT

    @pytest.mark.asyncio
    async def test_every_post_still_gets_its_own_tags(
        self, async_db_session: AsyncSession
    ) -> None:
        """Grouping tags by post is where a batched fetch goes wrong:
        one query is easy, handing each post ITS rows is the part to get
        right."""
        service = BlogService(async_db_session)
        await _seed(service)

        posts, _ = await service.list_posts(page_size=50)

        by_title = {post.title: post for post in posts}
        for index in range(POST_COUNT):
            tags = {tag.slug for tag in by_title[f"Post {index}"].tags}
            assert tags == {"news", f"topic-{index}"}, (
                f"Post {index} got the wrong tags: {tags}"
            )

    @pytest.mark.asyncio
    async def test_a_post_without_tags_still_lists(
        self, async_db_session: AsyncSession
    ) -> None:
        """A grouped fetch returns no row for an untagged post, which is
        where a dict lookup raises instead of returning []."""
        service = BlogService(async_db_session)
        bare = await service.create_post(BlogPostCreate(title="Bare", content="b"))
        await service.publish_post(bare.id)

        posts, total = await service.list_posts(page_size=50)

        assert total == 1
        assert posts[0].tags == []

    @pytest.mark.asyncio
    async def test_filtering_by_tag_is_still_flat(
        self, async_db_session: AsyncSession
    ) -> None:
        """The tag filter joins the same tables the batch fetch uses."""
        service = BlogService(async_db_session)
        await _seed(service)

        with assert_max_queries(3):
            posts, total = await service.list_posts(page_size=50, tag="news")

        assert total == POST_COUNT
        assert len(posts) == POST_COUNT


class TestExportIsFlat:
    @pytest.mark.asyncio
    async def test_exporting_does_not_query_per_post(
        self, async_db_session: AsyncSession
    ) -> None:
        service = BlogService(async_db_session)
        await _seed(service)

        with assert_max_queries(2):
            exported = await service.export_posts()

        assert len(exported) == POST_COUNT

    @pytest.mark.asyncio
    async def test_exported_posts_keep_their_tags(
        self, async_db_session: AsyncSession
    ) -> None:
        service = BlogService(async_db_session)
        await _seed(service)

        exported = await service.export_posts()

        by_title = {post.title: post for post in exported}
        for index in range(POST_COUNT):
            assert set(by_title[f"Post {index}"].tag_slugs) == {
                "news",
                f"topic-{index}",
            }


class TestHealthSummaryCountsOnce:
    @pytest.mark.asyncio
    async def test_the_status_breakdown_is_one_grouped_count(
        self, async_db_session: AsyncSession
    ) -> None:
        """Was one COUNT per status: total, draft, published, archived.

        One grouped count carries all four, leaving the tag count and the
        stale-draft count as the only other queries.
        """
        service = BlogService(async_db_session)
        await _seed(service)

        with assert_max_queries(4):
            summary = await service.get_health_summary()

        assert summary.total_posts == POST_COUNT
        assert summary.published_posts == POST_COUNT
        assert summary.draft_posts == 0

    @pytest.mark.asyncio
    async def test_each_status_is_counted_into_its_own_bucket(
        self, async_db_session: AsyncSession
    ) -> None:
        """A grouped count is one row per status; mapping them back to the
        right field is the part that silently swaps under a refactor."""
        service = BlogService(async_db_session)
        await service.create_post(BlogPostCreate(title="D", content="d"))
        for index in range(2):
            published = await service.create_post(
                BlogPostCreate(title=f"P{index}", content="p")
            )
            await service.publish_post(published.id)
        archived = await service.create_post(BlogPostCreate(title="A", content="a"))
        await service.archive_post(archived.id)

        summary = await service.get_health_summary()

        assert summary.total_posts == 4
        assert summary.draft_posts == 1
        assert summary.published_posts == 2
        assert summary.archived_posts == 1
