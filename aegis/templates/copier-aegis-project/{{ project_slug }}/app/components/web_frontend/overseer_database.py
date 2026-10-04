"""Context for the Overseer Database page's sections.

The same four views as the Flet database modal's tabs, built by the same helpers
(``app.services.system.ui_database``) from the health check's metadata.
"""

from typing import Any

from app.core.config import settings
from app.services.system import ui_database
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_database_subtitle

from .overseer_nav import SectionRequest

SECTIONS = (
    (
        None,
        {
            "overview": "Overview",
            "schema": "Schema",
            "migrations": "Migrations",
            "engine": "Engine",
            "activity": "Activity",
        },
    ),
)


async def section_context(
    section: str, database: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs beyond the database status."""
    metadata = database.metadata or {}
    context: dict[str, Any] = {"subtitle": get_database_subtitle(metadata)}
    if section == "overview":
        url = ui_database.display_url(str(metadata.get("url", "Unknown")))
        context["overview"] = ui_database.overview(metadata) | {"url": url}
    elif section == "schema":
        context["tables"] = ui_database.tables(metadata)
    elif section == "migrations":
        context["migrations"] = ui_database.migrations(metadata)
    elif section == "engine":
        context["settings"] = ui_database.settings(metadata)
    elif section == "activity":
        context["activity"] = ui_database.activity(metadata)
        context["threshold"] = settings.DATABASE_SLOW_TRANSACTION_SECONDS
    return context
