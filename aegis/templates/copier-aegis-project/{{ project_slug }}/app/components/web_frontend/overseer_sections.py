"""Which Overseer pages have a sub-menu, and where each section comes from.

A page listed here gets a second sidebar of grouped sections beside the main
one (``pages/overseer/_subnav.html``), with each section's content in
``pages/overseer/<folder>/_<section>.html``. Any other installed entry gets
the generic status page.
"""

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

from app.services.system.models import ComponentStatus

from . import (
    overseer_auth,
    overseer_database,
    overseer_patterns,
    overseer_redis,
    overseer_scheduler,
    overseer_server,
    overseer_web_frontend,
    overseer_worker,
)
from .overseer_nav import SectionRequest

# Grouped sections: (heading or None, {section key: label}). The first
# section is the page's own URL.
Sections = tuple[tuple[str | None, dict[str, str]], ...]


class SectionedPage(NamedTuple):
    folder: str
    sections: Sections
    # (section, component, request) -> template context
    context: Callable[[str, ComponentStatus, SectionRequest], Awaitable[dict[str, Any]]]
    live: bool = False

    @property
    def labels(self) -> dict[str, str]:
        return {
            key: label for _, group in self.sections for key, label in group.items()
        }


SECTIONED_PAGES: dict[tuple[str, str], SectionedPage] = {
    ("patterns", "patterns"): SectionedPage(
        "patterns", overseer_patterns.SECTIONS, overseer_patterns.section_context
    ),
    ("components", "backend"): SectionedPage(
        "server", overseer_server.SECTIONS, overseer_server.section_context, live=True
    ),
    ("components", "web_frontend"): SectionedPage(
        "web_frontend",
        overseer_web_frontend.SECTIONS,
        overseer_web_frontend.section_context,
    ),
    ("services", "auth"): SectionedPage(
        "auth", overseer_auth.SECTIONS, overseer_auth.section_context
    ),
    ("components", "scheduler"): SectionedPage(
        "scheduler", overseer_scheduler.SECTIONS, overseer_scheduler.section_context
    ),
    ("components", "database"): SectionedPage(
        "database", overseer_database.SECTIONS, overseer_database.section_context
    ),
    ("components", "cache"): SectionedPage(
        "redis", overseer_redis.SECTIONS, overseer_redis.section_context
    ),
    ("components", "worker"): SectionedPage(
        "worker", overseer_worker.SECTIONS, overseer_worker.section_context
    ),
}
