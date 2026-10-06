"""Context for the Overseer Web Frontend page: its status, and its routes.

The routes are the backend's own route list (the Server page's), narrowed
to the ones the web frontend tags ``web`` or ``overseer``.
"""

from typing import Any

from app.core.constants import ComponentName
from app.services.system import ui_backend
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest, find_installed
from .overseer_server import route_rows

SECTIONS = ((None, {"overview": "Overview", "routes": "Routes"}),)
WEB_TAGS = frozenset({"web", "overseer"})


def web_routes() -> list[dict[str, Any]]:
    """The backend's routes that belong to the web frontend."""
    backend = find_installed("components", ComponentName.BACKEND)
    routes = (backend.component.metadata or {}).get("routes") if backend else None
    return [r for r in routes or [] if WEB_TAGS & set(r.get("tags") or [])]


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """The Routes section's groups; the Overview needs nothing extra."""
    if section != "routes":
        return {}
    groups = [
        (name, route_rows(routes))
        for name, routes in ui_backend.route_groups(web_routes())
    ]
    return {"route_groups": groups, "groups_open": True}
