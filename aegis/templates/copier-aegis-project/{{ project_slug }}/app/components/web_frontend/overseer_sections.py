"""Which Overseer pages have a sub-menu, and where each section comes from.

A page listed here gets a second sidebar of grouped sections beside the main
one (``pages/overseer/_subnav.html``), with each section's content in
``pages/overseer/<folder>/_<section>.html``. Any other installed entry gets
the generic status page.
"""

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus

from . import (
    overseer_container,
    overseer_database,
    overseer_deployments,
    overseer_ingress,
    overseer_logs,
    overseer_patterns,
    overseer_redis,
    overseer_scheduler,
    overseer_secrets,
    overseer_server,
    overseer_settings,
    overseer_storage,
    overseer_web_frontend,
    overseer_worker,
)
from .overseer_nav import SectionRequest, registry_key

# Grouped sections: (heading or None, {section key: label}). The first
# section is the page's own URL.
Sections = tuple[tuple[str | None, dict[str, str]], ...]


class SectionedPage(NamedTuple):
    folder: str
    sections: Sections
    # (section, component, request) -> template context
    context: Callable[[str, ComponentStatus, SectionRequest], Awaitable[dict[str, Any]]]
    live: bool = False
    # A glance at its containers above its Overview (``overseer_container``).
    glance: bool = False
    # The data is the page (Logs, Deployments): it takes the whole canvas
    # rather than the reading column (``_shell.html``'s ``data-width``).
    workspace: bool = False

    @property
    def single(self) -> bool:
        """One section: no sub-menu, and the page heads it with its own name."""
        return len(self.labels) == 1

    @property
    def labels(self) -> dict[str, str]:
        return {
            key: label for _, group in self.sections for key, label in group.items()
        }


def _optional_pages() -> dict[tuple[str, str], SectionedPage]:
    """Pages for services and components a project may not have: each
    registered only when its module imports (the module ships with them)."""
    pages: dict[tuple[str, str], SectionedPage] = {}
    try:
        from . import overseer_auth

        pages[("services", "auth")] = SectionedPage(
            "auth", overseer_auth.SECTIONS, overseer_auth.section_context
        )
    except ImportError:  # no auth service in this project
        pass
    try:
        from . import overseer_blog

        pages[("services", "blog")] = SectionedPage(
            "blog", overseer_blog.SECTIONS, overseer_blog.section_context
        )
    except ImportError:  # no blog service in this project
        pass
    try:
        from . import overseer_documents

        pages[("services", "documents")] = SectionedPage(
            "documents", overseer_documents.SECTIONS, overseer_documents.section_context
        )
    except ImportError:  # no documents service in this project
        pass
    try:
        from . import overseer_comms

        pages[("services", "comms")] = SectionedPage(
            "comms", overseer_comms.SECTIONS, overseer_comms.section_context
        )
    except ImportError:  # no comms service in this project
        pass
    try:
        from . import overseer_payment

        pages[("services", "payment")] = SectionedPage(
            "payment", overseer_payment.SECTIONS, overseer_payment.section_context
        )
    except ImportError:  # no payment service in this project
        pass
    try:
        from . import overseer_inference

        pages[("components", "ollama")] = SectionedPage(
            "inference", overseer_inference.SECTIONS, overseer_inference.section_context
        )
    except ImportError:  # no inference component in this project
        pass
    try:
        from . import overseer_ai

        pages[("services", "ai")] = SectionedPage(
            "ai", overseer_ai.SECTIONS, overseer_ai.section_context
        )
    except ImportError:  # no AI service in this project
        pass
    return pages


# Overseer pages that are not a component or service in the health tree.
STANDALONE = {
    item.name: item
    for item in (
        overseer_patterns.ITEM,
        overseer_logs.ITEM,
        overseer_deployments.ITEM,
        overseer_secrets.ITEM,
        overseer_settings.ITEM,
    )
}


# The sections every page with a container behind it gets, in order: each
# module has a ``SECTION`` label and ``context(page, query)``.
RUNTIME_SECTIONS = (overseer_container, overseer_logs)


def _appended(
    page: SectionedPage,
    labels: dict[str, str],
    answer: Callable[[str, SectionRequest], Awaitable[dict[str, Any]]],
) -> SectionedPage:
    """The page plus trailing sections ``labels``, each answered by
    ``answer``; the page's own answer the rest."""

    async def context(
        section: str, component: ComponentStatus, req: SectionRequest
    ) -> dict[str, Any]:
        if section in labels:
            return await answer(section, req)
        return await page.context(section, component, req)

    return page._replace(sections=(*page.sections, (None, labels)), context=context)


def _with_glance(page: SectionedPage) -> SectionedPage:
    """The page with a glance at its containers above its first section."""
    first = next(iter(page.labels))

    async def context(
        section: str, component: ComponentStatus, req: SectionRequest
    ) -> dict[str, Any]:
        found = await page.context(section, component, req)
        if section == first:
            found |= await overseer_container.glance(page.folder)
        return found

    return page._replace(context=context)


def _with_runtime(name: str, page: SectionedPage) -> SectionedPage:
    """The page plus the runtime sections, when a container runs behind the
    component ``name`` (``ui_runtime.page_of``, which Flet reads too)."""
    if ui_runtime.page_of(name) != page.folder:
        return page

    async def answer(section: str, req: SectionRequest) -> dict[str, Any]:
        module = next(m for m in RUNTIME_SECTIONS if section in m.SECTION)
        return await module.context(page.folder, req.query)

    labels = {key: label for m in RUNTIME_SECTIONS for key, label in m.SECTION.items()}
    return _appended(_with_glance(page) if page.glance else page, labels, answer)


def _with_settings(key: tuple[str, str], page: SectionedPage) -> SectionedPage:
    """The page plus its own Settings section, when this stack has settings
    its component or service owns (``Configurable``)."""
    owner = registry_key(*key)
    if not overseer_settings.owns(owner):
        return page

    async def answer(section: str, req: SectionRequest) -> dict[str, Any]:
        return await overseer_settings.owned_context(owner)

    return _appended(page, overseer_settings.SECTION, answer)


_PAGES: dict[tuple[str, str], SectionedPage] = {
    ("patterns", "patterns"): SectionedPage(
        "patterns", overseer_patterns.SECTIONS, overseer_patterns.section_context
    ),
    ("logs", "logs"): SectionedPage(
        "logs", overseer_logs.SECTIONS, overseer_logs.section_context, workspace=True
    ),
    ("deployments", "deployments"): SectionedPage(
        "deployments",
        overseer_deployments.SECTIONS,
        overseer_deployments.section_context,
        workspace=True,
    ),
    ("secrets", "secrets"): SectionedPage(
        "secrets", overseer_secrets.SECTIONS, overseer_secrets.section_context
    ),
    ("settings", "settings"): SectionedPage(
        "settings", overseer_settings.SECTIONS, overseer_settings.section_context
    ),
    # The same page, on the secrets component's own entry when it is there.
    ("components", "secrets"): SectionedPage(
        "secrets", overseer_secrets.SECTIONS, overseer_secrets.section_context
    ),
    ("components", "backend"): SectionedPage(
        "server", overseer_server.SECTIONS, overseer_server.section_context, live=True
    ),
    ("components", "web_frontend"): SectionedPage(
        "web_frontend",
        overseer_web_frontend.SECTIONS,
        overseer_web_frontend.section_context,
    ),
    ("components", "scheduler"): SectionedPage(
        "scheduler",
        overseer_scheduler.SECTIONS,
        overseer_scheduler.section_context,
        glance=True,
    ),
    ("components", "database"): SectionedPage(
        "database", overseer_database.SECTIONS, overseer_database.section_context
    ),
    ("components", "cache"): SectionedPage(
        "redis", overseer_redis.SECTIONS, overseer_redis.section_context, glance=True
    ),
    ("components", "ingress"): SectionedPage(
        "ingress", overseer_ingress.SECTIONS, overseer_ingress.section_context
    ),
    ("components", "storage"): SectionedPage(
        "storage", overseer_storage.SECTIONS, overseer_storage.section_context
    ),
    ("components", "worker"): SectionedPage(
        "worker", overseer_worker.SECTIONS, overseer_worker.section_context
    ),
} | _optional_pages()

SECTIONED_PAGES = {
    key: _with_settings(key, _with_runtime(key[1], page))
    for key, page in _PAGES.items()
}

# An entry with no page of its own: its status, the generic page's body.
STATUS = ((None, {"overview": "Overview"}),)


async def _status(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    return {}


def page_for(group: str, name: str) -> SectionedPage | None:
    """The sectioned page for an entry: its own, or, for one without, its
    status as the Overview when its settings or containers add sections;
    None for the plain status page."""
    if page := SECTIONED_PAGES.get((group, name)):
        return page
    status = SectionedPage(ui_runtime.page_of(name) or name, STATUS, _status)
    found = _with_settings((group, name), _with_runtime(name, status))
    return None if found is status else found
