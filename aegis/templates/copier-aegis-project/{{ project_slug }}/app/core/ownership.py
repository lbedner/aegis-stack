"""Who owns a file or a module: the one service or component it belongs to,
read from where it is and, for a route or a test, from what it imports
(``source_index``), never from a table. Only an installed owner counts: one
the app names (``ServiceName``, ``ComponentName``) or a registered health
check names. A folder is not an owner by being there.

The rules, in order, for a path under ``app``:

1. ``services/<x>/``, its ``sub`` from a ``domains/<y>/`` or ``models/<y>/``.
2. ``components/backend/api/<x>``: the service, AI domain or component of
   that name, else the one service its folder (or flat file) imports, else
   the backend.
3. ``components/<x>/``, but an Overseer page (``overseer_<x>.py``,
   ``pages/overseer/<x>/``) goes with what it shows.
4. ``core/<m>.py`` that says which component it fronts (``FRONTS``).
5. ``cli/<x>/`` or ``cli/<x>.py`` for a service of that name.

A test (``tests/``) is the owner's whose code it imports: the one service,
else the one component; importing several, it is shared (None).
"""

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from app.core import source_index
from app.core.constants import ComponentName, ServiceName

Kind = Literal["service", "component"]
SERVICE: Kind = "service"
COMPONENT: Kind = "component"
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
# The Overseer page a component shows on, where it is not named for it.
COMPONENT_PAGES = {"backend": "server", "cache": "redis", "ollama": "inference"}
_PAGE = "overseer_"


@dataclass(frozen=True)
class Owner:
    kind: Kind
    name: str
    sub: str | None = None


def component_of(page: str) -> str:
    """The component an Overseer page shows (``COMPONENT_PAGES`` the other
    way), else the page's own name."""
    return next((c for c, p in COMPONENT_PAGES.items() if p == page), page)


def installed(kind: Kind, name: object) -> bool:
    """Whether the app has this service or component: named by it, or by a
    registered health check (a plugin's), without booting the checks."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        return False
    if name in (ServiceName if kind == SERVICE else ComponentName):
        return True
    health = sys.modules.get("app.services.system.health")
    registry = getattr(health, "registered_health_names", None)
    return registry is not None and name in registry()[f"{kind}s"]


def owner(where: str, index: source_index.Index | None = None) -> Owner | None:
    """Who owns ``where``: a path (from the project's root, or any root
    holding an ``app`` folder) or a dotted module (``app.core.cache``), a
    name in one too (``app.core.cache.get_cache``). ``index`` is the
    project's source (``source_index.project``) unless given."""
    index = index or source_index.project()
    parts = _parts(where, index)
    if parts and parts[0] == "tests":
        return _tested(parts, index)
    return _owner(parts, index) if parts else None


def _parts(where: str, index: source_index.Index) -> list[str] | None:
    """``where`` as a path's parts from ``app`` (or ``tests``), or None
    when it is in neither."""
    if "/" in where or "\\" in where:
        path = where.replace("\\", "/")
        root = f"{index.root.as_posix()}/"
        parts = path.removeprefix(root).split("/")
    else:
        parts = _module_path(where, index).split("/")
    if parts[0] == "tests" and len(parts) > 1:
        return parts
    for at in range(len(parts) - 2):
        if parts[at] == "app" and parts[at + 1] in _RULES:
            return parts[at:]
    return None


def _module_path(name: str, index: source_index.Index) -> str:
    """The file a dotted name is in: the longest leading module the index
    has, else the name read as a package's."""
    pieces = name.split(".")
    for end in range(len(pieces), 1, -1):
        if (path := index.paths.get(".".join(pieces[:end]))) is not None:
            return path
    return source_index.module_paths(name)[1]


def _owner(parts: list[str], index: source_index.Index) -> Owner | None:
    return _RULES[parts[1]](parts, index)


def _named(name: str) -> Owner | None:
    """The installed service, else component, called ``name``."""
    for kind in (SERVICE, COMPONENT):
        if installed(kind, name):
            return Owner(kind, name)
    return None


def _service(parts: list[str], index: source_index.Index) -> Owner | None:
    if len(parts) < 4 or not installed(SERVICE, parts[2]):
        return None
    folders = parts[3:-1]
    sub = next(
        (
            folders[i + 1]
            for i, f in enumerate(folders[:-1])
            if f in ("domains", "models")
        ),
        None,
    )
    return Owner(SERVICE, parts[2], sub)


def _component(parts: list[str], index: source_index.Index) -> Owner | None:
    if len(parts) < 4:
        return None
    if parts[2:4] == ["backend", "api"] and len(parts) > 4:
        return _route(parts, index)
    if parts[2] == "web_frontend" and (shown := _page(parts)):
        return shown
    return Owner(COMPONENT, parts[2]) if installed(COMPONENT, parts[2]) else None


def _route(parts: list[str], index: source_index.Index) -> Owner:
    """A route's owner: by its folder's (or flat file's) name, else by the
    one service it imports, else the backend's own."""
    folder = len(parts) > 5
    name = parts[4] if folder else PurePosixPath(parts[4]).stem
    if named := _named(name):
        return named
    if installed(SERVICE, "ai") and f"app.services.ai.domains.{name}" in index:
        return Owner(SERVICE, "ai", name)
    module = ".".join(parts[:5]).removesuffix(".py")
    services = _owners(index.imports_under(module), index, SERVICE)
    return services.pop() if len(services) == 1 else Owner(COMPONENT, "backend")


def _page(parts: list[str]) -> Owner | None:
    """What an Overseer page (``overseer_auth.py``, ``pages/overseer/auth/``)
    shows: the longest installed name, or page name, it starts with."""
    if len(parts) == 4 and parts[3].startswith(_PAGE):
        word = PurePosixPath(parts[3]).stem.removeprefix(_PAGE)
    elif parts[3:6] == ["templates", "pages", "overseer"] and len(parts) > 7:
        word = parts[6]
    else:
        return None
    candidates = [word[:i] for i, c in enumerate(word) if c == "_"] + [word]
    for candidate in reversed(candidates):
        if found := _named(component_of(candidate)):
            return found
    return None


def _core(parts: list[str], index: source_index.Index) -> Owner | None:
    if len(parts) != 3:
        return None
    module = index.get(f"app.core.{PurePosixPath(parts[2]).stem}")
    fronts = module.fronts if module else None
    return Owner(COMPONENT, fronts) if fronts and installed(COMPONENT, fronts) else None


def _cli(parts: list[str], index: source_index.Index) -> Owner | None:
    name = parts[2] if len(parts) > 3 else PurePosixPath(parts[2]).stem
    return Owner(SERVICE, name) if installed(SERVICE, name) else None


_RULES = {
    "services": _service,
    "components": _component,
    "core": _core,
    "cli": _cli,
}


def _owners(
    imported: Iterable[str], index: source_index.Index, kind: Kind
) -> set[Owner]:
    """The owners of kind ``kind`` of the app's modules in ``imported``,
    each by name alone."""
    owners = (
        _owner(parts, index)
        for name in imported
        if name.startswith("app.") and (parts := _parts(name, index))
    )
    return {Owner(kind, one.name) for one in owners if one and one.kind == kind}


def _tested(parts: list[str], index: source_index.Index) -> Owner | None:
    module = index.get(source_index.module_name("/".join(parts)))
    if module is None:
        return None
    for kind in (SERVICE, COMPONENT):
        found = _owners(module.imports, index, kind)
        if found:
            return found.pop() if len(found) == 1 else None
    return None
