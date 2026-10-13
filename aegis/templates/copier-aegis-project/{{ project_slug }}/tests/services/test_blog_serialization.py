"""Tests for blog service serialization (export/import format conversion)."""

from datetime import datetime
import json
import zipfile

import pytest

from app.services.blog.constants import BlogPostStatus
from app.services.blog.domains.transfer.formats import (
    json_to_posts,
    markdown_to_post,
    post_to_markdown,
    posts_to_json,
    posts_to_zip,
    zip_to_posts,
)
from app.services.blog.schemas import ExportedPost


class TestPostToMarkdown:
    """Tests for post_to_markdown serialization."""

    def test_post_to_markdown_basic(self) -> None:
        """Render a basic post as markdown with YAML frontmatter."""
        post = ExportedPost(
            title="Hello World",
            slug="hello-world",
            content="# Hello\n\nThis is the content.",
        )
        result = post_to_markdown(post)

        assert "title: Hello World" in result
        assert "slug: hello-world" in result
        assert "# Hello" in result
        assert "This is the content." in result

    def test_post_to_markdown_with_all_fields(self) -> None:
        """Include all optional fields in frontmatter."""
        now = datetime.fromisoformat("2024-01-15T10:30:00")
        post = ExportedPost(
            title="Complete Post",
            slug="complete",
            excerpt="Short intro",
            content="Full content",
            status=BlogPostStatus.PUBLISHED,
            author_name="Alice",
            created_at=now,
            updated_at=now,
            published_at=now,
            seo_title="SEO Title",
            seo_description="Meta description",
            hero_image_url="/images/hero.jpg",
            tag_slugs=["news", "release"],
        )
        result = post_to_markdown(post)

        assert "title: Complete Post" in result
        assert "slug: complete" in result
        assert "status: published" in result
        assert "author_name: Alice" in result
        assert "excerpt: Short intro" in result
        assert "seo_title: SEO Title" in result
        assert "seo_description: Meta description" in result
        assert "hero_image_url: /images/hero.jpg" in result
        assert "tags:" in result
        assert "news" in result
        assert "release" in result
        assert "2024-01-15T10:30:00" in result

    def test_post_to_markdown_syndication_fields(self) -> None:
        """canonical_url + syndicate_targets land in frontmatter."""
        post = ExportedPost(
            title="Syndicated",
            slug="syndicated",
            content="body",
            syndicate_targets=["devto", "hashnode"],
            canonical_url="https://pulse.example.com/blog/syndicated",
        )
        result = post_to_markdown(post)

        assert "canonical_url: https://pulse.example.com/blog/syndicated" in result
        assert "syndicate_targets:" in result
        assert "devto" in result
        assert "hashnode" in result


class TestMarkdownToPost:
    """Tests for markdown_to_post parsing."""

    def test_markdown_to_post_basic(self) -> None:
        """Parse a basic markdown file with frontmatter."""
        markdown = """---
title: Hello
slug: hello
status: published
---
# Content here"""
        result = markdown_to_post(markdown)

        assert result.title == "Hello"
        assert result.slug == "hello"
        assert result.status == BlogPostStatus.PUBLISHED
        assert "# Content here" in result.content

    def test_markdown_to_post_hugo_aliases(self) -> None:
        """Accept Hugo-style frontmatter aliases."""
        markdown = """---
title: Hugo Post
date: 2024-01-15
description: Meta desc
image: /cover.jpg
draft: false
---
Content"""
        result = markdown_to_post(markdown)

        assert result.title == "Hugo Post"
        assert result.seo_description == "Meta desc"
        assert result.hero_image_url == "/cover.jpg"
        assert result.status == BlogPostStatus.PUBLISHED
        assert result.published_at is not None

    def test_markdown_to_post_jekyll_draft(self) -> None:
        """Parse Jekyll draft: true -> draft status."""
        markdown = """---
title: Draft Post
draft: true
---
Content"""
        result = markdown_to_post(markdown)

        assert result.status == BlogPostStatus.DRAFT

    def test_markdown_to_post_astro_aliases(self) -> None:
        """Accept Astro-style field aliases."""
        markdown = """---
title: Astro Post
pubDate: 2024-02-20
coverImage: /astro-cover.jpg
---
Content"""
        result = markdown_to_post(markdown)

        assert result.title == "Astro Post"
        assert result.published_at is not None
        assert result.hero_image_url == "/astro-cover.jpg"

    def test_markdown_to_post_comma_separated_tags(self) -> None:
        """Parse tags as comma-separated string."""
        markdown = """---
title: Tagged Post
tags: "news, release, feature"
---
Content"""
        result = markdown_to_post(markdown)

        assert set(result.tag_slugs) == {"news", "release", "feature"}

    def test_markdown_to_post_array_tags(self) -> None:
        """Parse tags as an array."""
        markdown = """---
title: Tagged Post
tags:
  - News
  - Release
---
Content"""
        result = markdown_to_post(markdown)

        assert set(result.tag_slugs) == {"news", "release"}

    def test_markdown_to_post_slug_fallback(self) -> None:
        """Use fallback_slug when frontmatter has no slug."""
        markdown = """---
title: No Slug Post
---
Content"""
        result = markdown_to_post(markdown, fallback_slug="2024-01-15-my-post")

        assert result.slug == "my-post"

    def test_markdown_to_post_jekyll_date_prefix_stripped(self) -> None:
        """Remove Jekyll date prefix from fallback slug."""
        markdown = "---\ntitle: Post\n---\nContent"
        result = markdown_to_post(markdown, fallback_slug="2024-01-15-hello-world")

        assert result.slug == "hello-world"

    def test_markdown_to_post_no_title_fallback(self) -> None:
        """Derive title from slug when no title provided."""
        markdown = """---
slug: derived-title
---
Content"""
        result = markdown_to_post(markdown)

        assert result.title == "Derived Title"

    def test_markdown_to_post_empty_no_crash(self) -> None:
        """Handle markdown with minimal/missing fields."""
        markdown = "---\n---\nContent"
        result = markdown_to_post(markdown)

        assert result.title
        assert result.content == "Content"


class TestRoundTrip:
    """Round-trip serialization tests."""

    def test_post_markdown_roundtrip(self) -> None:
        """post_to_markdown -> markdown_to_post preserves data."""
        original = ExportedPost(
            title="Round Trip",
            slug="round-trip",
            excerpt="Short",
            content="Full content\nwith multiple lines",
            status=BlogPostStatus.PUBLISHED,
            tag_slugs=["a", "b"],
        )

        markdown = post_to_markdown(original)
        result = markdown_to_post(markdown)

        assert result.title == original.title
        assert result.slug == original.slug
        assert result.excerpt == original.excerpt
        assert result.content == original.content
        assert result.status == original.status
        assert set(result.tag_slugs) == set(original.tag_slugs)

    def test_syndication_roundtrip(self) -> None:
        """syndicate_targets + canonical_url survive markdown round-trip."""
        original = ExportedPost(
            title="Syndicated",
            slug="syndicated",
            content="body",
            syndicate_targets=["devto", "hashnode"],
            canonical_url="https://pulse.example.com/blog/syndicated",
        )

        result = markdown_to_post(post_to_markdown(original))

        assert set(result.syndicate_targets or []) == {"devto", "hashnode"}
        assert result.canonical_url == original.canonical_url


class TestPostsToJson:
    """Tests for JSON serialization."""

    def test_posts_to_json_valid(self) -> None:
        """Serialize posts list to JSON."""
        posts = [
            ExportedPost(title="First", slug="first", content="1"),
            ExportedPost(title="Second", slug="second", content="2"),
        ]

        result = posts_to_json(posts)
        parsed = json.loads(result)

        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["title"] == "First"
        assert parsed[1]["slug"] == "second"

    def test_json_to_posts_valid(self) -> None:
        """Parse JSON into posts list."""
        json_str = json.dumps([
            {
                "title": "One",
                "slug": "one",
                "content": "1",
                "status": "draft",
                "tag_slugs": [],
            },
            {
                "title": "Two",
                "slug": "two",
                "content": "2",
                "status": "published",
                "tag_slugs": ["tag1"],
            },
        ])

        result = json_to_posts(json_str)

        assert len(result) == 2
        assert result[0].title == "One"
        assert result[1].tag_slugs == ["tag1"]

    def test_json_roundtrip(self) -> None:
        """posts_to_json -> json_to_posts is lossless."""
        original = [
            ExportedPost(
                title="Test",
                slug="test",
                content="content",
                status=BlogPostStatus.PUBLISHED,
                tag_slugs=["x", "y"],
            ),
        ]

        json_str = posts_to_json(original)
        result = json_to_posts(json_str)

        assert len(result) == 1
        assert result[0].title == original[0].title
        assert result[0].slug == original[0].slug
        assert result[0].content == original[0].content
        assert result[0].status == original[0].status
        assert set(result[0].tag_slugs) == set(original[0].tag_slugs)

    def test_json_to_posts_invalid_not_array(self) -> None:
        """Reject JSON that is not an array."""
        with pytest.raises(ValueError, match="Expected a JSON array"):
            json_to_posts('{"title": "Single"}')


class TestPostsToZip:
    """Tests for zip archive serialization."""

    def test_posts_to_zip_creates_valid_zip(self) -> None:
        """Bundle posts into a valid zip archive."""
        posts = [
            ExportedPost(title="First", slug="first", content="1"),
            ExportedPost(title="Second", slug="second", content="2"),
        ]

        result = posts_to_zip(posts)

        with zipfile.ZipFile(__import__('io').BytesIO(result)) as zf:
            names = zf.namelist()
            assert "first.md" in names
            assert "second.md" in names

    def test_posts_to_zip_content_valid_markdown(self) -> None:
        """Zip entries contain valid markdown."""
        posts = [
            ExportedPost(
                title="Test",
                slug="test",
                content="# Hello",
                tag_slugs=["tag1"],
            ),
        ]

        result = posts_to_zip(posts)

        with zipfile.ZipFile(__import__('io').BytesIO(result)) as zf:
            content = zf.read("test.md").decode("utf-8")
            assert "title: Test" in content
            assert "slug: test" in content
            assert "# Hello" in content

    def test_posts_to_zip_collision_handling(self) -> None:
        """Deduplicate post slugs with numeric suffix."""
        posts = [
            ExportedPost(title="Same", slug="same", content="1"),
            ExportedPost(title="Also Same", slug="same", content="2"),
            ExportedPost(title="Still Same", slug="same", content="3"),
        ]

        result = posts_to_zip(posts)

        with zipfile.ZipFile(__import__('io').BytesIO(result)) as zf:
            names = sorted(zf.namelist())
            assert names == ["same-2.md", "same-3.md", "same.md"]


class TestZipToPosts:
    """Tests for zip archive deserialization."""

    def test_zip_to_posts_reads_all_markdown_files(self) -> None:
        """Extract all .md files from zip."""
        import io

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("first.md", "---\ntitle: First\nslug: first\n---\nContent 1")
            zf.writestr("second.md", "---\ntitle: Second\nslug: second\n---\nContent 2")
            zf.writestr("readme.txt", "Ignore this")

        result = zip_to_posts(buf.getvalue())

        assert len(result) == 2
        titles = {p.title for p in result}
        assert titles == {"First", "Second"}

    def test_zip_to_posts_slug_fallback(self) -> None:
        """Use filename as fallback slug when missing from frontmatter."""
        import io

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "2024-01-15-my-post.md",
                "---\ntitle: No Slug\n---\nContent",
            )

        result = zip_to_posts(buf.getvalue())

        assert result[0].slug == "my-post"

    def test_zip_roundtrip(self) -> None:
        """posts_to_zip -> zip_to_posts preserves posts."""
        original = [
            ExportedPost(
                title="A",
                slug="a",
                content="content-a",
                tag_slugs=["tag1"],
            ),
            ExportedPost(
                title="B",
                slug="b",
                content="content-b",
                tag_slugs=["tag2"],
            ),
        ]

        zipped = posts_to_zip(original)
        result = zip_to_posts(zipped)

        assert len(result) == 2
        result_by_slug = {p.slug: p for p in result}
        assert result_by_slug["a"].title == "A"
        assert result_by_slug["b"].title == "B"
