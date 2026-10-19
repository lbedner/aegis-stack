"""A route's dry path: every hop it can take, read from the code without
sending a request (``walk``). Anchored at runtime on the route FastAPI
built (``anchor``: its handler, and the dependencies it injects, each
typing the parameter it fills), then static (``trace``, ``dry_walk``):
each body's calls, followed through names, modules, typed locals and
``self`` (``dry_names``), project code only, each function once.

Where the walk cannot see further it stops at that line and says why
(``Reason``); what no static walk sees is ``UNSEEN``. The hops also
collapse to the nodes they join (``edges``), for a reader of the model."""

from collections.abc import Iterable, Mapping
from functools import cache
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from app.core import exposure, secrets, source_index
from app.core.ontology import calls
from app.core.ontology.model import Mode
from app.core.source_index import Index, within

from .dry_names import symbol_of
from .dry_walk import REASONS, UNSEEN, Entry, Frozen, Hop, HopKind, Need, Stop, Walker
from .patterns import SERVICE_PACKAGE, label, returns

# What callers read from here, defined beside the walk.
__all__ = [
    "REASONS",
    "UNSEEN",
    "DryPath",
    "Entry",
    "Need",
    "anchor",
    "entry_of",
    "find",
    "reaches_service",
    "trace",
    "walk",
]


class Step(Frozen):
    """Hops collapsed to the nodes they join, as the map draws them."""

    source: str
    target: str
    kind: HopKind
    mode: Mode


class DryPath(Frozen):
    route: str
    hops: tuple[Hop, ...]
    edges: tuple[Step, ...]
    stops: tuple[Stop, ...]


def find(routes: Iterable[BaseRoute], key: str) -> APIRoute | None:
    """The route behind a ``"<METHOD> <path>"`` key, or None."""
    method, _, path = key.partition(" ")
    return next(
        (
            r
            for r in routes
            if isinstance(r, APIRoute) and r.path == path and method in r.methods
        ),
        None,
    )


def anchor(route: APIRoute) -> Entry:
    """The route as FastAPI resolved it: its handler and its dependencies."""
    handler = symbol_of(route.endpoint)
    if handler is None:
        raise ValueError(f"{label(route)} has no handler the walk can find")
    return Entry(label(route), handler, _needs(route.dependant))


def entry_of(func: Any, name: str) -> Entry | None:
    """``func`` as a walk's start (a task, a job), or None where the walk
    cannot find its source."""
    handler = symbol_of(func)
    return Entry(name, handler) if handler else None


@cache
def reaches_service(entry: Entry | None, index: Index | None = None) -> bool:
    """Whether ``entry``'s walk (through ``index``, the project's) reaches
    ``app.services`` past its own handler: a function, class or table of
    one, however far down. What the patterns' Service step reads, once an
    entry (its rows and its thin rule ask too)."""
    return entry is not None and any(
        hop.kind != HopKind.HANDLER and within(hop.symbol, SERVICE_PACKAGE)
        for hop in trace(entry, index, set()).hops
    )


def _needs(dependant: Dependant) -> tuple[Need, ...]:
    found = []
    for d in dependant.dependencies:
        if (symbol := symbol_of(d.call)) is None:
            continue
        given = returns(d.call)
        typed = symbol_of(given) if isinstance(given, type) else None
        found.append(Need(symbol, d.name, typed, _needs(d)))
    return tuple(found)


def walk(route: APIRoute) -> DryPath:
    """``route``'s dry path, its hops on the running app's model nodes.
    Raises ValueError while the source is hidden (``exposure.shown``):
    every hop is a line of it."""
    from app.core.ontology import current

    if not exposure.shown(exposure.CODE):
        raise ValueError("The source is hidden here: turn on Overseer > Code.")
    return trace(anchor(route), ids={n.id for n in current().nodes})


def trace(
    entry: Entry,
    index: Index | None = None,
    ids: set[str] | None = None,
    providers: Mapping[str, list[str]] | None = None,
) -> DryPath:
    """``entry`` walked through ``index`` (the project's): hops on the
    nodes of ``ids`` (a part's own, given none), outside providers by the
    package holding their keys (``calls.by_package``, given none)."""
    walker = Walker(
        index or source_index.project(),
        ids,
        calls.by_package(secrets.declared()) if providers is None else providers,
    )
    walker.start(entry)
    return DryPath(
        route=entry.route,
        hops=tuple(walker.hops),
        edges=_edges(walker.hops),
        stops=tuple(walker.stops),
    )


def _edges(hops: list[Hop]) -> tuple[Step, ...]:
    by_id = {h.id: h for h in hops}
    found: dict[tuple[str, str, HopKind], Step] = {}
    for hop in hops:
        parent = by_id.get(hop.parent) if hop.parent else None
        source = parent.node if parent else None
        if source and hop.node and source != hop.node:
            key = (source, hop.node, hop.kind)
            step = Step(source=source, target=hop.node, kind=hop.kind, mode=hop.mode)
            found.setdefault(key, step)
    return tuple(found.values())
