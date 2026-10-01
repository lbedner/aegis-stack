"""Navigation for the server-rendered Overseer.

Use the same registered health tree as the Flet dashboard. This keeps the
left rail limited to components and services actually in the project,
including plugin-provided entries.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha1
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import BaseRoute

from app.models.user import User
from app.services.system.health import last_system_status, registered_health_names
from app.services.system.models import (
    ComponentStatus,
    ComponentStatusType,
    SystemStatus,
)
from app.services.system.ui import get_component_title

ORDER = {
    "components": (
        "backend",
        "web_frontend",
        "frontend",
        "database",
        "worker",
        "scheduler",
        "cache",
        "storage",
        "ingress",
        "observability",
        "ollama",
    ),
    "services": (
        "auth",
        "ai",
        "comms",
        "documents",
        "insights",
        "payment",
        "finance",
        "blog",
    ),
}


def _shown(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


@dataclass(frozen=True)
class SectionRequest:
    """What a page section's context builder may read about the request."""

    viewer: User
    db: AsyncSession
    query: Mapping[str, str]
    path: str
    # The app's routes, for pages that describe the app itself.
    routes: Sequence[BaseRoute] = ()
    # The viewer's own sign-in session (the access token's ``sid``).
    session_id: str | None = None


@dataclass(frozen=True)
class NavItem:
    group: str
    name: str
    title: str
    url: str
    status: str
    component: ComponentStatus

    @property
    def checks(self) -> list[tuple[str, str]]:
        """Each sub-check's name and state, for the status page."""
        return [
            (name.replace("_", " ").title(), check.status.value.title())
            for name, check in (self.component.sub_components or {}).items()
        ]

    @property
    def details(self) -> list[tuple[str, str]]:
        """What the health check published, for the generic page: plain
        values only (nested data belongs on a page of its own), and not the
        ``type`` bookkeeping every check sets."""
        return [
            (key.replace("_", " ").capitalize(), _shown(value))
            for key, value in (self.component.metadata or {}).items()
            if key != "type" and isinstance(value, str | int | float | bool)
        ]

    @property
    def event(self) -> str:
        """Stable, SSE-safe event name even for plugin-provided keys."""
        digest = sha1(self.name.encode(), usedforsecurity=False).hexdigest()[:12]
        return f"status-{self.group}-{digest}"


def page_url(group: str, name: str) -> str:
    """An installed entry's Overseer page."""
    return f"/overseer/{group}/{quote(name, safe='')}"


def build_navigation(status: SystemStatus | None) -> dict[str, list[NavItem]]:
    """Flatten the Flet dashboard's components/services groups for the rail."""
    aegis = status.components.get("aegis") if status else None
    groups = aegis.sub_components if aegis else {}
    registered = registered_health_names()
    result: dict[str, list[NavItem]] = {"components": [], "services": []}
    for group in result:
        parent = groups.get(group)
        children = parent.sub_components if parent else {}
        order = ORDER[group]
        names = set(registered[group]) | set(children)
        for name in sorted(
            names,
            key=lambda key: (order.index(key) if key in order else len(order), key),
        ):
            component = children.get(name) or ComponentStatus(
                name=name,
                status=ComponentStatusType.INFO,
                message="Checking status…",
            )
            result[group].append(
                NavItem(
                    group=group,
                    name=name,
                    title=get_component_title(
                        name if group == "components" else f"service_{name}"
                    ),
                    url=page_url(group, name),
                    status=component.status.value,
                    component=component,
                )
            )
    return result


def find_item(
    navigation: dict[str, list[NavItem]], group: str, name: str
) -> NavItem | None:
    """The installed entry ``group``/``name``, if there is one."""
    return next((e for e in navigation.get(group, ()) if e.name == name), None)


def find_installed(group: str, name: str) -> NavItem | None:
    """``find_item`` against the latest health snapshot, for routes that need
    one entry rather than the whole sidebar."""
    return find_item(build_navigation(last_system_status()), group, name)
