"""Database models for the blog service."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import JSON, CheckConstraint, Column, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

from .constants import BlogPostStatus



class BlogStatus(StrEnum):
    """Allowed post statuses."""

    DRAFT = BlogPostStatus.DRAFT
    PUBLISHED = BlogPostStatus.PUBLISHED
    ARCHIVED = BlogPostStatus.ARCHIVED


class BlogPost(SQLModel, table=True):
    """Markdown blog post."""

    __tablename__ = "blog_post"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_blog_post_status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=200)
    slug: str = Field(max_length=220, unique=True, index=True)
    excerpt: str | None = Field(default=None, max_length=500)
    content: str = Field(sa_column=Column(Text, nullable=False))
    status: BlogStatus = Field(
        default=BlogStatus.DRAFT,
        sa_column=Column("status", String(16), nullable=False, index=True),
    )
    author_id: int | None = Field(default=None, index=True)
    author_name: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = Field(default=None, index=True)
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=320)
    hero_image_url: str | None = Field(default=None, max_length=1024)
    # Platforms this post is syndicated to (slugs: "devto", "hashnode",
    # "medium"). Record-keeping for the syndication workflow; the export
    # frontmatter carries it so platform tooling can route the post. NULL =
    # not syndicated anywhere.
    syndicate_targets: list[str] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )


class BlogTag(SQLModel, table=True):
    """Tag used to classify blog posts."""

    __tablename__ = "blog_tag"
    __table_args__ = (
        UniqueConstraint("name", name="uq_blog_tag_name"),
        UniqueConstraint("slug", name="uq_blog_tag_slug"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=80, index=True)
    slug: str = Field(max_length=100, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class BlogPostTag(SQLModel, table=True):
    """Many-to-many join between posts and tags."""

    __tablename__ = "blog_post_tag"

    post_id: int = Field(foreign_key="blog_post.id", primary_key=True, index=True)
    tag_id: int = Field(foreign_key="blog_tag.id", primary_key=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class BlogHealthSummary(BaseModel):
    """Typed summary used by the blog health check and dashboard."""

    total_posts: int
    draft_posts: int
    published_posts: int
    archived_posts: int
    tag_count: int
    stale_draft_count: int
    latest_published_post: dict[str, Any] | None = None
