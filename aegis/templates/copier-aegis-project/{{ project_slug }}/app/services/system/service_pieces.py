"""A service opened up (Overseer's map, ``?zoom=service_<name>``): its
pieces as the service standard names them (each standard file, its router
in the API package, each domain) and the lines between them and out of it,
read from what its modules import (``source_index``). A loose module is no
piece: the parts pattern's "Logic lives in domains" names it. No UI
framework imports."""

from dataclasses import dataclass

from app.core.ontology import Kind
from app.core.ontology.model import parse_node_id
from app.core.ontology.parts import node_of
from app.core.source_index import Module
from app.services.system.service_parts import DOMAINS, PIECES, ROUTER, Folder, piece_of

# The standard's pieces in the order they are drawn: what callers reach
# first, then the rest; its domains after them.
ORDER = [ROUTER, *dict.fromkeys(title for title, _ in PIECES.values())]
# Each part's lane by its title: every piece's, and each step's a service
# may lack (its slot, dashed).
LANE_OF = {title: lane for title, lane in PIECES.values()} | {
    ROUTER: "entry",
    "Tests": "probe",
}


@dataclass(frozen=True)
class Piece:
    key: str  # its map key: ``piece:queries``, ``piece:domains.tags``
    title: str
    lane: str  # where it is drawn (``LANE_OF``; a domain's is ``domains``)
    modules: tuple[str, ...]
    paths: tuple[str, ...]


def _named(folder: Folder, module: Module) -> tuple[str, str, str] | None:
    """The piece ``module`` belongs to, as (name, title, lane); None loose."""
    words = folder.words(module)
    if words[0] == DOMAINS and len(words) > 1:
        title = words[1].replace("_", " ").capitalize()
        return f"{DOMAINS}.{words[1]}", title, DOMAINS
    if (found := piece_of(words[0])) is None:
        return None
    title, lane = found
    return title.lower().replace(" ", "_"), title, lane


def pieces(folder: Folder) -> list[Piece]:
    """``folder``'s pieces, its router first and its domains last."""
    held: dict[str, tuple[str, str, list[Module]]] = {}
    if folder.routers:
        held["router"] = (ROUTER, LANE_OF[ROUTER], list(folder.routers))
    for module in folder.modules:
        if named := _named(folder, module):
            name, title, lane = named
            held.setdefault(name, (title, lane, []))[2].append(module)
    found = [
        Piece(
            f"piece:{name}",
            title,
            lane,
            tuple(m.name for m in modules),
            tuple(m.path for m in modules),
        )
        for name, (title, lane, modules) in held.items()
    ]

    def rank(piece: Piece) -> tuple[int, str]:
        if piece.lane == DOMAINS:
            return len(ORDER), piece.key
        return ORDER.index(piece.title), ""

    return sorted(found, key=rank)


def links(folder: Folder, found: list[Piece], ids: set[str]) -> dict[str, list[str]]:
    """What each piece imports: the other pieces, in their order, then the
    parts (of ``ids``) outside the service, a node id each: a core client
    is the component it fronts (``ownership``). Stack code and the
    service's own sub-services are no line."""
    holder = {module: piece.key for piece in found for module in piece.modules}

    def piece_of(name: str) -> str | None:
        while name and name not in holder:
            name = name.rpartition(".")[0]
        return holder.get(name)

    order = [piece.key for piece in found]
    lines: dict[str, list[str]] = {}
    for piece in found:
        inside, outside = set(), set()
        for name in piece.modules:
            module = folder.index.get(name)
            for imported in module.imports if module else ():
                if target := piece_of(imported):
                    inside.add(target)
                elif (node := node_of(imported, folder.index, ids)) and _out(
                    node, folder.subject
                ):
                    outside.add(node)
        inside.discard(piece.key)
        lines[piece.key] = sorted(inside, key=order.index) + sorted(outside)
    return lines


def _out(node: str, subject: str) -> bool:
    """A part outside the service: a component, or another service than
    it or one of its own sub-services (``service:ai.rag``)."""
    kind, name = parse_node_id(node)
    own = kind is Kind.SERVICE and name.partition(".")[0] == parse_node_id(subject)[1]
    return kind in (Kind.COMPONENT, Kind.SERVICE) and not own
