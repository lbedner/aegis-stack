"""Format conversion for blog export/import.

No DB access here. Pure transformation between ``ExportedPost`` /
``ImportedPost`` and on-disk formats: markdown+frontmatter, JSON, and
zip archives of markdown files.

Lenient on import: accepts Hugo/Jekyll/Astro frontmatter aliases so a
foreign ``posts/`` directory can be dropped in directly. Strict on
export: writes the canonical Aegis field names.
"""

from __future__ import annotations

from datetime import date, datetime
import io
import json
import re
from typing import Any
import zipfile

import frontmatter

from app.services.blog.constants import BlogPostStatus
from app.services.blog.domains.posts.slugs import slugify
from app.services.blog.schemas import ExportedPost, ImportedPost

_JEKYLL_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def _coerce_datetime(value: Any) -> datetime | None:
    """Best-effort parse of a frontmatter date value."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _coerce_tags(value: Any) -> list[str]:
    """Accept tags as a list, comma-separated string, or single string."""
    if value is None:
        return []
    if isinstance(value, list):
        return [slugify(str(t)) for t in value if str(t).strip()]
    if isinstance(value, str):
        return [slugify(t) for t in value.split(",") if t.strip()]
    return []


def _coerce_status(meta: dict[str, Any]) -> str:
    """Resolve status from explicit field or Hugo/Jekyll ``draft`` boolean."""
    explicit = meta.get("status")
    if isinstance(explicit, str) and explicit in BlogPostStatus.ALL:
        return explicit
    draft = meta.get("draft")
    if draft is True:
        return BlogPostStatus.DRAFT
    if draft is False:
        return BlogPostStatus.PUBLISHED
    return BlogPostStatus.DRAFT


def _first(meta: dict[str, Any], *keys: str) -> Any:
    """Return the first present value among ``keys``."""
    for key in keys:
        if key in meta and meta[key] is not None:
            return meta[key]
    return None


def post_to_markdown(post: ExportedPost) -> str:
    """Render a post as a markdown file with YAML frontmatter."""
    meta: dict[str, Any] = {
        "title": post.title,
        "slug": post.slug,
        "status": post.status,
    }
    if post.author_name:
        meta["author_name"] = post.author_name
    if post.tag_slugs:
        meta["tags"] = list(post.tag_slugs)
    if post.excerpt:
        meta["excerpt"] = post.excerpt
    if post.seo_title:
        meta["seo_title"] = post.seo_title
    if post.seo_description:
        meta["seo_description"] = post.seo_description
    if post.hero_image_url:
        meta["hero_image_url"] = post.hero_image_url
    if post.syndicate_targets:
        meta["syndicate_targets"] = list(post.syndicate_targets)
    # Origin URL so syndicated copies point rel=canonical back here.
    # Dev.to and Hashnode read this frontmatter key natively.
    if post.canonical_url:
        meta["canonical_url"] = post.canonical_url
    if post.created_at:
        meta["created_at"] = post.created_at.isoformat()
    if post.updated_at:
        meta["updated_at"] = post.updated_at.isoformat()
    if post.published_at:
        meta["published_at"] = post.published_at.isoformat()

    fm = frontmatter.Post(post.content or "", **meta)
    return frontmatter.dumps(fm)


def markdown_to_post(text: str, *, fallback_slug: str | None = None) -> ImportedPost:
    """Parse a markdown file with frontmatter into an ``ImportedPost``.

    Lenient: accepts Hugo/Jekyll/Astro aliases for common fields. Unknown
    keys are silently dropped.
    """
    fm = frontmatter.loads(text)
    meta = dict(fm.metadata)

    title = str(_first(meta, "title") or "").strip()
    slug_raw = _first(meta, "slug")
    if slug_raw:
        slug = slugify(str(slug_raw))
    elif fallback_slug:
        slug = slugify(_JEKYLL_DATE_PREFIX.sub("", fallback_slug))
    else:
        slug = slugify(title or "")

    if not title:
        # Last-resort title derived from slug so DB constraint passes
        title = slug.replace("-", " ").title()

    return ImportedPost(
        title=title,
        slug=slug,
        excerpt=_first(meta, "excerpt"),
        content=fm.content,
        status=_coerce_status(meta),
        author_name=_first(meta, "author_name", "author"),
        created_at=_coerce_datetime(_first(meta, "created_at")),
        updated_at=_coerce_datetime(_first(meta, "updated_at")),
        published_at=_coerce_datetime(
            _first(meta, "published_at", "publishDate", "pubDate", "date")
        ),
        seo_title=_first(meta, "seo_title"),
        seo_description=_first(meta, "seo_description", "description"),
        hero_image_url=_first(meta, "hero_image_url", "image", "cover", "coverImage"),
        syndicate_targets=_coerce_tags(_first(meta, "syndicate_targets")) or None,
        canonical_url=_first(meta, "canonical_url", "canonical", "canonicalUrl"),
        tag_slugs=_coerce_tags(_first(meta, "tags")),
    )


def posts_to_json(posts: list[ExportedPost]) -> str:
    """Render posts as a single pretty-printed JSON document."""
    payload = [p.model_dump(mode="json") for p in posts]
    return json.dumps(payload, indent=2, sort_keys=False)


def json_to_posts(text: str) -> list[ImportedPost]:
    """Parse a JSON document produced by ``posts_to_json``."""
    raw = json.loads(text)
    if not isinstance(raw, list):
        raise ValueError("Expected a JSON array of posts")
    return [ImportedPost.model_validate(item) for item in raw]


def posts_to_zip(posts: list[ExportedPost]) -> bytes:
    """Bundle posts into a zip archive (one .md per post, named by slug)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen: set[str] = set()
        for post in posts:
            base = post.slug or "post"
            name = f"{base}.md"
            counter = 1
            while name in seen:
                counter += 1
                name = f"{base}-{counter}.md"
            seen.add(name)
            zf.writestr(name, post_to_markdown(post))
    return buf.getvalue()


def zip_to_posts(data: bytes) -> list[ImportedPost]:
    """Read a zip archive, returning one ``ImportedPost`` per .md entry."""
    posts: list[ImportedPost] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".md"):
                continue
            body = zf.read(info).decode("utf-8")
            stem = info.filename.rsplit("/", 1)[-1].removesuffix(".md")
            posts.append(markdown_to_post(body, fallback_slug=stem))
    return posts
