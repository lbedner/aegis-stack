"""Health check for the blog service."""

import logging

from app.core.db import get_async_session
from app.services.system.models import ComponentStatus, ComponentStatusType

from .service import BlogService
from .constants import BLOG_COMPONENT_NAME

logger = logging.getLogger(__name__)


async def check_blog_service_health() -> ComponentStatus:
    """Check blog storage and publish workflow health."""
    try:
        async with get_async_session() as session:
            service = BlogService(session)
            summary = await service.get_health_summary()
            metadata = summary.model_dump(mode="json")

        if summary.total_posts == 0:
            return ComponentStatus(
                name=BLOG_COMPONENT_NAME,
                status=ComponentStatusType.INFO,
                message="No posts yet",
                metadata=metadata,
            )

        status = (
            ComponentStatusType.WARNING
            if summary.stale_draft_count
            else ComponentStatusType.HEALTHY
        )
        message = f"{summary.published_posts} published, {summary.draft_posts} drafts"
        if summary.stale_draft_count:
            message = f"{message}; {summary.stale_draft_count} stale drafts"

        return ComponentStatus(
            name=BLOG_COMPONENT_NAME,
            status=status,
            message=message,
            metadata=metadata,
        )

    except Exception as e:
        logger.error("Blog health check failed: %s", e)
        return ComponentStatus(
            name=BLOG_COMPONENT_NAME,
            status=ComponentStatusType.UNHEALTHY,
            message=f"Health check error: {e}",
            metadata={"error": str(e)},
        )
