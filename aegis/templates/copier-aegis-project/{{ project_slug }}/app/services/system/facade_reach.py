"""Who imports a service past its facade (``service.py``), for the parts
pattern: another service (``through-facade``), or one of its own ways in
(``own-facade``): its router, a tool or a job, the CLI, a page. Read from
what modules import (``source_index``), never imported."""

from collections.abc import Callable, Iterable
from functools import cache

from app.core import ownership
from app.core.source_index import Index, Module, within
from app.services.system.patterns import SERVICE_PACKAGE

DOMAINS = "domains"
# What a service keeps to itself: another service importing one reaches
# past its facade (service.py; its schemas and deps are public too).
INTERNALS = frozenset({DOMAINS, "adapters", "queries", "models"})
# What its own ways in reach only through its facade: running its adapters
# (a job syncing a provider) is their work, not a step past it.
OWN_INTERNALS = INTERNALS - {"adapters"}
# One import a module makes: the module, its line, the name it imports.
Import = tuple[Module, int, str]


def _imports(
    modules: Iterable[Module], internal: Callable[[str], bool]
) -> list[Import]:
    """Each import in ``modules`` of a name ``internal`` holds, at the
    first line it is used on."""
    return [
        (m, min(m.uses.get((local,), (1,))), name)
        for m in modules
        for local, (source, member) in m.imported.items()
        if internal(name := f"{source}.{member}" if member else source)
    ]


def lines(found: list[Import]) -> list[str]:
    """``found`` as a finding's evidence: ``path:line``, one line once, in
    its modules' order, then by line."""
    order: dict[str, int] = {}
    for m, _, _ in found:
        order.setdefault(m.path, len(order))
    held = sorted({(m.path, n) for m, n, _ in found}, key=lambda f: (order[f[0]], f[1]))
    return [f"{path}:{n}" for path, n in held]


def reaching(
    modules: list[Module], services: dict[str, str | None], service: str | None
) -> list[str]:
    """Each line in ``modules`` (a folder's and its routers') importing
    another service's ``INTERNALS``."""

    def internal(name: str) -> bool:
        words = name.split(".")
        if service is None or words[:2] != ["app", "services"]:
            return False
        theirs = services.get(words[2]) if len(words) > 3 else None
        return theirs not in (None, service) and words[3] in INTERNALS

    return lines(_imports(modules, internal))


@cache
def _outside(index: Index) -> dict[str, list[Module]]:
    """App code outside the services, by each services package it imports
    (``app.services.meetings``): one read of the project, not one a folder.
    ponytail: kept for the index's life, as the parts report is."""
    found: dict[str, list[Module]] = {}
    for m in sorted(index.naming(f"{SERVICE_PACKAGE}."), key=lambda m: m.name):
        if not within(m.name, "app") or within(m.name, SERVICE_PACKAGE):
            continue
        named = {".".join(n.split(".")[:3]) for n in m.imports}
        for package in {n for n in named if within(n, SERVICE_PACKAGE)}:
            found.setdefault(package, []).append(m)
    return found


def skips(
    index: Index, package: str, service: str | None, entry: list[Module]
) -> list[Import]:
    """Each import of ``package``'s own ``OWN_INTERNALS`` by a way in: one
    of ``entry`` (its router, its tools and jobs), then app code outside the
    services no other service owns (the CLI, a page). Another service's is
    ``reaching``'s."""
    names = {m.name for m in entry}
    outside = [m for m in _outside(index).get(package, []) if m.name not in names]

    def own(name: str) -> bool:
        words = name.removeprefix(f"{package}.").split(".")
        return within(name, package) and words[0] in OWN_INTERNALS

    found = _imports([*entry, *outside], own)
    others = {
        name
        for name in {m.name for m, _, _ in found} - names
        if (mine := ownership.owner(name, index))
        and mine.kind == ownership.SERVICE
        and mine.name != service
    }
    return [i for i in found if i[0].name not in others]
