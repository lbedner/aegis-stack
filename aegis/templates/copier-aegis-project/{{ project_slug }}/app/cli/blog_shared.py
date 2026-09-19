"""Helpers every blog command leans on: ids, dates, errors."""

from app.cli import theme

console = theme.console()


def _ex(*lines: str) -> str:
    """Render an indented Examples block for a command epilog.

    Rich (typer's default help renderer) collapses single newlines into
    soft wraps. Joining examples with a blank line keeps each on its own
    visual line.
    """
    body = "\n\n".join(lines)
    return f"Examples:\n\n{body}"


def _format_dt(value: object) -> str:
    """Render a datetime cell, falling back to a dim dash."""
    if value is None:
        return "[dim]-[/dim]"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")  # type: ignore[union-attr]
    return str(value)


def _status_color(status: str) -> str:
    return {
        "draft": theme.WARNING,
        "published": theme.ACCENT,
        "archived": "dim",
    }.get(status, "dim")


async def _resolve_post_id(service: object, slug: str) -> int | None:
    """Find a post id by slug across all statuses (paginated scan)."""
    page = 1
    while page <= _RESOLVE_PAGE_LIMIT:
        posts, total = await service.list_posts(  # type: ignore[attr-defined]
            page=page, page_size=_RESOLVE_PAGE_SIZE
        )
        for post in posts:
            if post.slug == slug:
                return post.id
        if page * _RESOLVE_PAGE_SIZE >= total:
            return None
        page += 1
    return None


async def _resolve_tag_id(service: object, slug: str) -> int | None:
    """Find a tag id by slug."""
    tags = await service.list_tags()  # type: ignore[attr-defined]
    for tag in tags:
        if tag.slug == slug:
            return tag.id
    return None


_PAGE_SIZE_MAX = 100


_RESOLVE_PAGE_SIZE = 100


_RESOLVE_PAGE_LIMIT = 50
