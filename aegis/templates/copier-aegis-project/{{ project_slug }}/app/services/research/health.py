"""Health check for research (dashboard ComponentStatus): how many watches
and items across every owner, the last run, and the sources installed. A
failure here is reported by the health walk itself."""

from app.core.db import get_async_session
from app.core.formatting import counted
from app.services.research.registry import installed_sources
from app.services.research.service import research_counts
from app.services.system.models import ComponentStatus, ComponentStatusType

RESEARCH_COMPONENT_NAME = "research"


async def check_research_service_health() -> ComponentStatus:
    async with get_async_session() as session:
        counts = await research_counts(session)
    metadata = {**counts, "sources": [s.name for s in installed_sources()]}
    if not metadata["sources"]:
        return ComponentStatus(
            name=RESEARCH_COMPONENT_NAME,
            status=ComponentStatusType.INFO,
            message="No sources installed: add one (aegis-stack-hackernews)",
            metadata=metadata,
        )
    return ComponentStatus(
        name=RESEARCH_COMPONENT_NAME,
        status=ComponentStatusType.HEALTHY,
        message=f"{counted(counts['watches'], 'watch', 'watches')}, "
        f"{counted(counts['items'], 'item')}",
        metadata=metadata,
    )
