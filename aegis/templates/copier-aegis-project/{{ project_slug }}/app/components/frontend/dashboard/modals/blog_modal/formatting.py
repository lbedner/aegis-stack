"""Small conversions the blog panels share."""

from datetime import UTC, datetime
from typing import Any

import flet as ft
from app.components.frontend.theme import AegisTheme as Theme


def _status_color(status: str) -> str:
    colors = {
        "draft": Theme.Colors.WARNING,
        "published": Theme.Colors.SUCCESS,
        "archived": ft.Colors.ON_SURFACE_VARIANT,
    }
    return colors.get(status, ft.Colors.ON_SURFACE_VARIANT)


def _format_date(value: str | None) -> str:
    """Render an ISO timestamp as a human-readable relative or absolute date.

    Recent timestamps render as "just now" / "5m ago" / "3h ago" / "2d ago";
    anything older than a week falls back to "Mon D, YYYY" (e.g. "May 7, 2026").
    """
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value.split("T", 1)[0]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - dt).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 7 * 86400:
        return f"{seconds // 86400}d ago"
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _post_tag_slugs(post: dict[str, Any]) -> list[str]:
    tags = post.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [
        str(tag.get("slug"))
        for tag in tags
        if isinstance(tag, dict) and tag.get("slug")
    ]
