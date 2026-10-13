"""Who owns a file or a module: the one service or component it belongs to,
or the stack's own code, read from where it is and, for a route or a test,
from what it imports (``source_index``), never from a table. Only a known
owner counts: a part the aegis CLI declares (``parts.PARTS``) or a
registered health check names (a plugin's). A folder is not an owner by
being there.

The rules, in order, for a path under ``app``:

1. ``services/<x>/``, its ``sub`` from a ``domains/<y>/`` or ``models/<y>/``;
   a folder that is not a service says what it is part of beside its code
   (``PART_OF = ServiceName.AI`` for rag), or that it is the stack's own
   (``PART_OF = "stack"``: system, shared, the change queue).
2. ``components/backend/api/<x>``: the service, service domain or component
   of that name, else the one service its folder (or flat file) imports, else
   the backend.
3. ``components/<x>/`` (a folder named for its CLI name too: ``inference``
   is ``ollama``), but an Overseer page (``overseer_<x>.py``,
   ``pages/overseer/<x>/``) goes with what it shows.
4. ``core/<m>.py`` that says which component it fronts (``FRONTS``).
5. ``cli/<x>/`` or ``cli/<x>.py`` for a service of that name.
6. ``integrations/``, where the app is put together: the backend's.

A test (``tests/``) is the owner's whose code it imports: the one service,
else the one component; importing several, it is shared (None).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import PurePosixPath
import re
import sys
from typing import Literal

from app.core import source_index
from app.core.parts import PARTS

Kind = Literal["service", "component", "stack"]
SERVICE: Kind = "service"
COMPONENT: Kind = "component"
STACK: Kind = "stack"  # the stack's own code, no one part's
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
# The Overseer page a component shows on, where it is not named for it.
COMPONENT_PAGES = {name: part.page for name, part in PARTS.items() if part.page}
# What has no process of its own runs in (``Part.hosts``): the backend.
HOST = next(name for name, part in PARTS.items() if part.hosts)
# Each part that takes work from another (``Part.consumes``): the worker,
# its queue. Nothing calls it: a part using it hands work to what it takes.
TAKES = {name: taken for name, part in PARTS.items() for taken in part.consumes}


def page_of_part(name: str) -> str:
    """The Overseer page a part shows on: its declared one, else its name."""
    return COMPONENT_PAGES.get(name, name)


_PAGE = "overseer_"
_SERVICES = "app.services."
# A part by its CLI name, where that is not its own (``inference``).
_BY_CLI = {part.cli: name for name, part in PARTS.items() if part.cli != name}


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
    """Whether this is a service or component: one the aegis CLI declares,
    or one a registered health check names (a plugin's), without booting
    the checks."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        return False
    if (part := PARTS.get(name)) is not None and part.kind == kind:
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
    for parts in _readings(where, index):
        found = _tested(parts, index) if parts[0] == "tests" else _owner(parts, index)
        if found is not None:
            return found
    return None


def _readings(where: str, index: source_index.Index) -> list[list[str]]:
    """``where`` as a path's parts from ``app`` (or ``tests``): a path one
    way; a dotted name as the file the index has for it, then as a package
    of its own (a service this stack does not have is not in the index)."""
    if "/" in where or "\\" in where:
        root = f"{index.root.as_posix()}/"
        paths = [where.replace("\\", "/").removeprefix(root)]
    else:
        paths = list(
            dict.fromkeys(
                (_module_path(where, index), source_index.module_paths(where)[1])
            )
        )
    return [found for path in paths if (found := _anchored(path.split("/")))]


def _anchored(parts: list[str]) -> list[str] | None:
    """``parts`` from ``app`` (or ``tests``), or None in neither."""
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
    if len(parts) < 4:
        return None
    if not installed(SERVICE, parts[2]):
        return _part_of(parts[2], index)
    folders = parts[3:-1]
    sub = next(
        (
            folders[i + 1]
            for i, f in enumerate(folders[:-1])
            if f in ("domains", "models")
        ),
        None,
    )
    # A domain that is one module (``domains/base.py``) is a sub-service as
    # much as a package is (``ontology.parts`` makes a node of either).
    stem = parts[-1].removesuffix(".jinja").removesuffix(".py")
    if sub is None and folders[-1:] == ["domains"] and stem != "__init__":
        sub = stem
    return Owner(SERVICE, parts[2], sub)


@cache
def _part_of(folder: str, index: source_index.Index) -> Owner | None:
    """What a services folder that is not a service says it is part of."""
    package = index.get(f"{_SERVICES}{folder}")
    declared = package.declared.part_of if package else None
    if declared == STACK:
        return Owner(STACK, folder)
    found = _named(declared) if declared else None
    return Owner(found.kind, found.name, folder) if found else None


def _component(parts: list[str], index: source_index.Index) -> Owner | None:
    if len(parts) < 4:
        return None
    if parts[2:4] == [HOST, "api"] and len(parts) > 4:
        return _route(parts, index)
    if parts[2] == "web_frontend" and (shown := _page(parts)):
        return shown
    name = _by_cli(parts[2])
    return Owner(COMPONENT, name) if installed(COMPONENT, name) else None


def _by_cli(folder: str) -> str:
    """The part a component folder named for its CLI name is (``inference``
    is ``ollama``), else the folder's own name."""
    return _BY_CLI.get(folder, folder)


def folders(name: str) -> tuple[str, ...]:
    """The folder names a part's code can be in: its own, then its CLI's
    (``_by_cli`` the other way)."""
    cli = PARTS[name].cli if name in PARTS else name
    return tuple(dict.fromkeys((name, cli)))


def _route(parts: list[str], index: source_index.Index) -> Owner:
    """A route's owner: by its folder's (or flat file's) name, else by the
    one service it imports, else the backend's own."""
    folder = len(parts) > 5
    name = parts[4] if folder else PurePosixPath(parts[4]).stem
    if named := _named(name):
        return named
    if domain := _domain(name, index):
        return domain
    module = ".".join(parts[:5]).removesuffix(".py")
    # Only a service's own code says which service: a module of the
    # route's own package (``api/rag/__init__`` importing ``.routes``) would
    # ask this again.
    imported = (n for n in index.imports_under(module) if n.startswith(_SERVICES))
    services = _owners(imported, index, SERVICE)
    return services.pop() if len(services) == 1 else Owner(COMPONENT, HOST)


def _domain(name: str, index: source_index.Index) -> Owner | None:
    """The installed service with a domain of that name (``ai/domains/llm``)."""
    found = (
        module.split(".")[2]
        for module in index.paths
        if module.startswith(_SERVICES)
        and module.endswith(f".domains.{name}")
        and module.count(".") == 4
    )
    service = next((s for s in found if installed(SERVICE, s)), None)
    return Owner(SERVICE, service, name) if service else None


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
    fronts = module.declared.fronts if module else None
    return Owner(COMPONENT, fronts) if fronts and installed(COMPONENT, fronts) else None


def _cli(parts: list[str], index: source_index.Index) -> Owner | None:
    name = parts[2] if len(parts) > 3 else PurePosixPath(parts[2]).stem
    return Owner(SERVICE, name) if installed(SERVICE, name) else None


_RULES = {
    "services": _service,
    "components": _component,
    "core": _core,
    "cli": _cli,
    "integrations": lambda parts, index: Owner(COMPONENT, HOST),
}


def _owners(
    imported: Iterable[str], index: source_index.Index, kind: Kind
) -> set[Owner]:
    """The owners of kind ``kind`` of the app's modules in ``imported``,
    each by name alone."""
    owners = (owner(name, index) for name in imported if name.startswith("app."))
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
