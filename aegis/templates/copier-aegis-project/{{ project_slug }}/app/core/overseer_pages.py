"""The Overseer pages services bring, declared by the service that owns them.

A service with a page of its own declares it in
``app/services/<service>/overseer.py`` as ``OVERSEER``, an ``OverseerPage``;
Overseer lists it under the service, its templates in
``pages/overseer/<service>/``, and mounts its partials behind the Overseer
gate. Found on disk through ``app.core.discovery``, so an app's own service
needs no edit to the framework's files. The page is named by import path,
so a service never imports the web frontend.
"""

from collections.abc import Callable
from dataclasses import dataclass
import importlib

from fastapi import APIRouter

from app.core.discovery import declared_by


@dataclass(frozen=True)
class OverseerPage:
    """A service's Overseer page.

    ``module`` exposes ``SECTIONS`` and ``section_context`` (as
    ``overseer_sections.SectionedPage`` takes them); ``partials``, if any,
    exposes the ``router`` of its htmx fragments; ``when`` says whether
    this stack shows it (a page for a dev stack only).
    """

    module: str
    partials: str | None = None
    when: Callable[[], bool] = lambda: True


def service_pages() -> list[tuple[str, OverseerPage]]:
    """Each service's ``OVERSEER`` this stack shows, with the service's
    name, in service name order."""
    import app.services as services

    return [
        (owner, page)
        for owner, page in declared_by(services, "overseer", "OVERSEER")
        if page.when()
    ]


def include_partials(router: APIRouter) -> None:
    """Mount each shown page's partials on ``router`` (the Overseer's, so
    they pass its gate)."""
    for _, page in service_pages():
        if page.partials:
            router.include_router(importlib.import_module(page.partials).router)
