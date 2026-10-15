"""Navigation for the server-rendered Overseer.

Use the same registered health tree as the Flet dashboard. This keeps the
left rail limited to components and services actually in the project,
including plugin-provided entries.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from urllib.parse import quote

from starlette.routing import BaseRoute

from app.core.ontology.parts import placement
from app.core.ownership import component_of
from app.core.parts import Category
from app.services.system.health import last_system_status, registered_health_names
from app.services.system.models import (
    ComponentStatus,
    ComponentStatusType,
    SystemStatus,
)
from app.services.system.ui import get_component_title, registry_key

from .overseer_access import Db, Viewer

# Records what a section did with the app's data, as the viewer, from where
# they asked (``audit_admin_action``): an event, how it went, its detail,
# and what it was done to.
Audit = Callable[..., Awaitable[None]]


def _shown(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


@dataclass(frozen=True)
class SectionRequest:
    """What a page section's context builder may read about the request."""

    viewer: Viewer  # None without auth
    db: Db  # None without the database component
    query: Mapping[str, str]
    path: str
    audit: Audit
    # The app's routes, for pages that describe the app itself.
    routes: Sequence[BaseRoute] = ()
    # The viewer's own sign-in session (the access token's ``sid``), and when
    # its session cookie runs out and renews from the refresh token.
    session_id: str | None = None
    session_expires: datetime | None = None
    # The element an htmx swap replaces (``HX-Target``), so a section can
    # leave out what the swap discards; None for a whole page.
    target: str | None = None


@dataclass(frozen=True)
class NavItem:
    group: str
    name: str
    title: str
    url: str
    status: str
    component: ComponentStatus
    # The concern an Overseer page of its own serves in the sidebar; a
    # part's is its declared one (``ontology.parts.concern_of``).
    concern: Category | None = None

    @property
    def checks(self) -> list[tuple[str, str]]:
        """Each sub-check's name and state, for the status page."""
        return [
            (name.replace("_", " ").title(), check.status.value)
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
        names = set(registered[group]) | set(children)
        # In each part's declared order (``ontology.parts.placement``).
        for name in sorted(names, key=placement):
            component = children.get(name) or ComponentStatus(
                name=name,
                status=ComponentStatusType.INFO,
                message="Checking status…",
            )
            result[group].append(
                NavItem(
                    group=group,
                    name=name,
                    title=get_component_title(registry_key(group, name)),
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


def current_navigation() -> dict[str, list[NavItem]]:
    """The sidebar's entries as the latest health snapshot has them."""
    return build_navigation(last_system_status())


def find_installed(group: str, name: str) -> NavItem | None:
    """``find_item`` against the latest health snapshot, for routes that need
    one entry rather than the whole sidebar."""
    return find_item(current_navigation(), group, name)


def runtime_page_url(page: str) -> str:
    """The Overseer page a runtime page's containers show on (``redis`` is
    the Cache component's)."""
    return page_url("components", component_of(page))
