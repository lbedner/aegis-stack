"""A path staged as the hops a replay plays: a route's code path (``dry``,
``route``), or a flow's stops joined along the lines the model declares
(``joined``), each hop a beat after the one before and no timing of its
own. Shaped as a kept request is (``kept_requests.RequestHops``), so
whatever plays a request (Overseer's replay, a path card) plays these the
same way."""

from collections.abc import Iterable, Sequence
from itertools import pairwise

from app.core.constants import ComponentName
from app.core.edges import DATABASE, SERVER
from app.core.ontology import Kind, graph
from app.core.ontology.model import Edge, EdgeKind, SystemModel, parse_node_id
from app.services.system import dry_path
from app.services.system.dry_path import DryPath
from app.services.system.kept_requests import RequestHop, RequestHops
from app.services.system.ui import registry_key

BEAT_MS = 100.0  # a staged hop's length, and the gap to the next
# What a flow's line can be: a call or a need, the way it points; a part
# holding a sub-part or a table, either way.
FOLLOWED = frozenset({EdgeKind.CALLS, EdgeKind.DEPENDS_ON})
OUTSIDE = "outside:"  # an outside provider's map key, before its name
# Code the map draws as a box of its own, keyed by its node id
# (``queue:system``): what each is, under its name.
CODE = {Kind.QUEUE: "Worker queue", Kind.TASK: "Worker task"}
# What the map places: a part, an outside provider, a table (as the
# database holding it), and ``CODE``.
PLACED = frozenset({Kind.COMPONENT, Kind.SERVICE, Kind.EXTERNAL, Kind.OBJECT, *CODE})
SAID = 12  # the most a refusal names of what a stop does reach


def registry_of(node_id: str) -> str:
    """A model node's id as the map keys it: a service by its registry key
    (a service and a component may share a name), an outside provider as
    ``outside:<name>``, a component by its name; a sub-part as its part,
    on whose card it is drawn (RAG's, AI's), a table as the database
    holding it, and a worker's queue or task as itself (``CODE``)."""
    kind, name = parse_node_id(node_id)
    if kind is Kind.EXTERNAL:
        return OUTSIDE + name
    if kind is Kind.OBJECT:
        return ComponentName.DATABASE.value
    if kind in CODE:
        return node_id
    name = name.partition(".")[0]
    if kind is Kind.SERVICE:
        return registry_key("services", name)
    return name


def wired(model: SystemModel, node_id: str) -> dict[tuple[str, str], list[Edge]]:
    """``node_id``'s wiring (``graph.wiring``) as the map draws it: each
    pair of map keys a line joins, with its edges; a line within one box,
    or to what the map places nothing for, left out. Empty, a wiring card
    has nothing to draw."""
    pairs: dict[tuple[str, str], list[Edge]] = {}
    for edge in graph.wiring(model, node_id):
        ends = edge.source, edge.target
        if all(parse_node_id(end)[0] in PLACED for end in ends):
            a, b = map(registry_of, ends)
            if a != b:
                pairs.setdefault((a, b), []).append(edge)
    return pairs


def joined(model: SystemModel, stops: Sequence[str]) -> RequestHops:
    """``stops`` (model node ids, in order) as hops, each joined to the
    next by the shortest way along the lines ``model`` has (declared, or
    seen in traffic where it is the running one; ``_lines``), never one
    it has none for; a stop not in it, or none reaches, is refused saying
    what to name instead."""
    lines = _lines(model)
    chains = []
    for start, end in pairwise(stops):
        found = graph.paths(lines, start, end, directed=True)
        if not found:
            reached = sorted({e.target for e in lines.edges if e.source == start})
            raise ValueError(
                f"Nothing on the map takes {start} to {end}; {start} reaches: "
                f"{', '.join(reached[:SAID]) or 'nothing'}."
            )
        here = start
        for edge in found[0]:
            # A table calls nothing: leaving one is its read returning.
            if parse_node_id(here)[0] is not Kind.OBJECT:
                chains.append(_read(here, edge.target))
            here = edge.target
    return _staged(chains, method="", path="")


def _lines(model: SystemModel) -> SystemModel:
    """``model`` with only the lines a flow can take between parts the map
    places: its calls and needs as they point, a part and what it holds
    both ways, and the Server to each part it runs (sharing its
    container)."""
    kinds = {node.id: node.kind for node in model.nodes}
    placed = {key for key, kind in kinds.items() if kind in PLACED}
    host = {e.source: e.target for e in model.edges if e.kind is EdgeKind.RUNS_ON}
    lines = [
        Edge(source=SERVER, target=key, kind=EdgeKind.CALLS)
        for key, container in host.items()
        if key != SERVER and key in placed and container == host.get(SERVER)
    ]
    for edge in model.edges:
        if edge.source not in placed or edge.target not in placed:
            continue
        if edge.kind in FOLLOWED:
            lines.append(edge)
        elif edge.kind is EdgeKind.CONTAINS:
            lines += [
                edge,
                edge.model_copy(update={"source": edge.target, "target": edge.source}),
            ]
    return model.model_copy(update={"edges": tuple(lines)})


def dry(walked: DryPath) -> RequestHops:
    """``walked`` as hops: its handler's part entered from the server, then
    each edge it collapses to, a table read a hop into the database
    naming the table, as a kept request's query is."""
    entry = next((hop.node for hop in walked.hops if hop.node), None)
    chains: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    if entry:
        chains.append(((SERVER, entry), ()))
    # What only a loop over a registry reaches (every part's health check)
    # is what is registered when it runs: the card stops where the loop is.
    chains += [_read(s.source, s.target) for s in walked.edges if not s.fanned]
    method, _, path = walked.route.partition(" ")
    return _staged(chains, method=method, path=path)


def _read(source: str, target: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """A line as a hop the map can place: into a table (an object, no part
    of the map's), the database reading it, named."""
    kind, name = parse_node_id(target)
    if kind is Kind.OBJECT:
        return (source, DATABASE), (name,)
    return (source, target), ()


async def route(key: str) -> RequestHops:
    """The route behind ``key`` (``"GET /api/v1/..."``), walked dry."""
    return dry(await dry_path.of(key))


def paced(recording: RequestHops, hops: Iterable[RequestHop]) -> RequestHops:
    """``recording`` playing ``hops`` a beat apart, the way a staged path
    plays (its own and the card's folded copy alike)."""
    beats = tuple(
        hop.model_copy(update={"at_ms": index * BEAT_MS, "ms": BEAT_MS})
        for index, hop in enumerate(hops)
    )
    return recording.model_copy(
        update={"hops": beats, "hop_count": len(beats), "ms": len(beats) * BEAT_MS}
    )


def _staged(
    chains: Sequence[tuple[tuple[str, ...], tuple[str, ...]]], *, method: str, path: str
) -> RequestHops:
    hops = (
        RequestHop(
            chain=chain, at_ms=0, ms=BEAT_MS, error=False, tables=tables, lines=()
        )
        for chain, tables in chains
    )
    shell = RequestHops(
        id="",
        method=method,
        path=path,
        route=path,
        status=200,
        ms=0,
        hop_count=0,
        dropped=0,
        hops=(),
        staged=True,
    )
    return paced(shell, hops)
