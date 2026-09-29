"""Context for the Overseer Blog page's sections.

The Flet blog modal's tabs (Overview, Posts, Editor, Tags) in Aegis
Pulse's shape: a posts list filtered by status with publish and archive on
each row, and an editor for one post. Everything reads and writes through
``BlogService`` on the request's session. Registered only in projects with
the blog service (see ``overseer_sections``).
"""

from typing import Any

from app.core.formatting import format_relative_time
from app.services.blog.constants import BlogPostStatus
from app.services.blog.schemas import BlogPostResponse
from app.services.blog.service import BlogService
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest, page_url
from .rendering import drawer_state, status_cell, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Content", {"posts": "Posts", "tags": "Tags"}),
)

PAGE = page_url("services", "blog")
PARTIALS = "/partials/overseer/blog"
PAGE_SIZE = 50
STATUS_TONES = {
    BlogPostStatus.DRAFT: "warn",
    BlogPostStatus.PUBLISHED: "ok",
    BlogPostStatus.ARCHIVED: "muted",
}
STATUS_CHIPS = (
    (None, "All"),
    (BlogPostStatus.DRAFT, "Drafts"),
    (BlogPostStatus.PUBLISHED, "Published"),
    (BlogPostStatus.ARCHIVED, "Archived"),
)


DRAWER_PARAM = "post"
NEW = "new"


def editor_url(post_id: int | str = NEW, **filters: str | None) -> str:
    """The posts list with this post (or a new one) open in the drawer."""
    return with_query(f"{PAGE}/posts", **filters, **{DRAWER_PARAM: str(post_id)})


def tag_text(post: BlogPostResponse) -> str:
    """A post's tags as the editor's field shows them."""
    return ", ".join(tag.name for tag in post.tags)


def parse_tags(raw: str) -> list[str]:
    """The editor's tags field: comma or space separated."""
    return [part for part in raw.replace(",", " ").split() if part]


def _post_row(post: BlogPostResponse, **filters: str | None) -> dict[str, Any]:
    status = str(post.status)
    return {
        "id": post.id,
        "title": {"label": post.title, "url": editor_url(post.id, **filters)},
        "status": status_cell(status.title(), STATUS_TONES.get(status, "muted")),
        "is_published": status == BlogPostStatus.PUBLISHED,
        "tags": tag_text(post) or None,
        "updated": format_relative_time(post.updated_at),
        "published": format_relative_time(post.published_at)
        if post.published_at
        else None,
    }


async def _overview(service: BlogService) -> dict[str, Any]:
    summary = await service.get_health_summary()
    recent, _ = await service.list_posts(page_size=5)
    return {
        "figures": [
            {"label": "Posts", "value": summary.total_posts},
            {
                "label": "Drafts",
                "value": summary.draft_posts,
                "caption": f"{summary.stale_draft_count} stale"
                if summary.stale_draft_count
                else None,
            },
            {"label": "Published", "value": summary.published_posts},
            {"label": "Archived", "value": summary.archived_posts},
            {"label": "Tags", "value": summary.tag_count},
        ],
        "recent": [_post_row(p) for p in recent],
    }


async def _posts(
    service: BlogService, query: dict[str, str], path: str
) -> dict[str, Any]:
    status = query.get("status") or None
    if status not in {s for s, _ in STATUS_CHIPS}:
        status = None
    posts, total = await service.list_posts(page_size=PAGE_SIZE, status=status)
    wanted = query.get(DRAWER_PARAM) or ""
    shown = wanted if wanted == NEW or wanted.isdigit() else None
    return drawer_state(
        DRAWER_PARAM, f"{PARTIALS}/posts/{shown}/drawer" if shown else None
    ) | {
        "status": status,
        "chips": [
            {
                "label": label,
                "url": path + (f"?status={s}" if s else ""),
                "active": s == status,
            }
            for s, label in STATUS_CHIPS
        ],
        "rows": [_post_row(p, status=status) for p in posts],
        "total": total,
    }


async def editor_context(service: BlogService, post_id: int | None) -> dict[str, Any]:
    """The drawer's editor: the post, or a new draft when ``post_id`` is None."""
    post = await service.get_post(post_id) if post_id is not None else None
    return {
        "partials": PARTIALS,
        "post": post,
        "tags": tag_text(post) if post else "",
        "save_url": f"{PARTIALS}/posts/{post.id}" if post else f"{PARTIALS}/posts",
        "status": status_cell(
            str(post.status).title(), STATUS_TONES.get(str(post.status), "muted")
        )
        if post
        else None,
    }


async def _tags(service: BlogService) -> dict[str, Any]:
    return {
        "tags": [
            {
                "id": tag.id,
                "name": tag.name,
                "slug": tag.slug,
                "created": format_relative_time(tag.created_at),
                "delete_url": f"{PARTIALS}/tags/{tag.id}/confirm-delete",
            }
            for tag in await service.list_tags()
        ],
        "create_url": f"{PARTIALS}/tags",
    }


async def section_context(
    section: str, blog: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    service = BlogService(req.db)
    context: dict[str, Any] = {"partials": PARTIALS, "new_post_url": editor_url()}
    if section == "overview":
        return context | await _overview(service)
    if section == "posts":
        return context | await _posts(service, dict(req.query), req.path)
    return context | await _tags(service)
