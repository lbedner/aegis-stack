"""The Server opened up on Overseer's map (``?view=map&zoom=backend``):
what runs inside it, by registry key, what each reaches (the model's
calls, live providers), and the outside providers whose key is not set,
each with its key's set dialog one click away. And a service opened up
below it (``?zoom=service_<name>``): its pieces (``service_pieces``), what
hangs off each, and the parts they reach. Either as one request went
through it (``along_server``, ``along_service``: a replay's), nothing
else drawn."""

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any

from app.core import secrets, source_index
from app.core.constants import ComponentName
from app.core.formatting import counted
from app.core.ontology import EdgeKind, Kind, SystemModel, calls
from app.core.ontology.model import node_id, parse_node_id
from app.core.ownership import HOST
from app.core.source_index import Module
from app.services.system import service_parts, service_pieces, topology
from app.services.system.service_pieces import Piece
from app.services.system.ui import (
    get_component_title,
    is_service,
    registry_entry,
    registry_key,
)

from . import overseer_code, overseer_map, overseer_secrets

OUTSIDE = "outside:"  # an outside provider's node key, before its name
# What hangs off a piece, counted on it: the model's nodes its modules define.
HANGING = {
    Kind.ROUTE: "route",
    Kind.JOB: "job",
    Kind.TOOL: "tool",
    Kind.CHANGE: "change type",
    Kind.OBJECT: "table",
}
Lines = dict[str, list[str]]
Pair = tuple[str, str]
Tones = dict[Pair, dict[str, Any]]


@dataclass(frozen=True)
class Path:
    """The way a request went through a level: the parts, in the order it
    reached them, and the lines it went along (``along_server``); of them,
    the ones seen in traffic only (unknown: the ones the level has none
    for, as a request's are)."""

    nodes: list[str]
    links: list[Pair]
    seen: frozenset[Pair] | None = None


RAIL = 3  # ponytail: a part this many pieces use rides the rail; tune by eye
HOLDS = 12  # what a piece's hint names of what it holds; the rest counted
# What each tone ``_tones`` gives a line means: the map's key.
LINE_KEY = {"error": "Skips the facade, or a loop", "warn": "Goes back a lane"}
# What each way a line is drawn means (``_overview_map.html``), by its flag.
LINE_STYLES = {
    "queued": "Handed to the queue",
    "observed": "Seen in traffic, not in the code",
    "key": "A key it needs is not set",
}
# Each module's code nodes by kind: each one's name, and the top-level name
# defining it there (a table's class), where its code opens.
Held = dict[str, dict[Kind, list[tuple[str, str]]]]
# Each service's pieces and lines, read once a process, as the parts report
# they come from; and the model's code nodes by module, named by kind, for
# the model last read (``current``'s, one a process once built).
_read: dict[str, tuple[list[Piece], Lines]] = {}
_held: tuple[SystemModel | None, Held] = (None, {})


def registry_of(node_id: str) -> str:
    """A model node's id as the map keys it: a service by its registry key
    (a service and a component may share a name), an outside provider as
    ``outside:<name>``, a component by its name; a sub-part as its part,
    on whose card it is drawn (RAG's, AI's), and a table as the database
    holding it."""
    kind, name = parse_node_id(node_id)
    if kind is Kind.EXTERNAL:
        return OUTSIDE + name
    if kind is Kind.OBJECT:
        return ComponentName.DATABASE.value
    name = name.partition(".")[0]
    if kind is Kind.SERVICE:
        return registry_key("services", name)
    return name


def _reaches(model: SystemModel, keys: set[str]) -> dict[str, list[str]]:
    """What each of ``keys`` reaches: its code's calls (the system model)
    and the outside providers whose keys it needs now (``calls``, read
    live: a provider switched in settings is the one drawn)."""
    found: dict[str, list[str]] = {key: [] for key in keys}
    for edge in model.edges:
        if edge.kind is not EdgeKind.CALLS or edge.target.startswith(Kind.EXTERNAL):
            continue  # an outside provider's is read live, below
        if (source := registry_of(edge.source)) in found:
            found[source].append(registry_of(edge.target))
    declared = secrets.declared()
    for key in keys:
        if is_service(key):
            name = registry_entry(key)[1]
            found[key] += [OUTSIDE + p for p, _ in calls.providers(declared, name)]
    return {key: list(dict.fromkeys(targets)) for key, targets in found.items()}


def opened(
    stack: list[dict[str, Any]], model: SystemModel
) -> tuple[list[dict[str, Any]], topology.Shape]:
    """The Server opened up (``topology.zoomed``): what runs inside it, by
    its registry key, and what each reaches (``_reaches``): an installed
    component as itself, an outside provider as a plain node."""
    hosted = set(topology.shape([item["key"] for item in stack]).hosted)
    inside = [
        item | {"key": item["registry"]} for item in stack if item["key"] in hosted
    ]
    components = {item["registry"]: item for item in stack if item["key"] not in hosted}
    keys = {item["key"] for item in inside}
    links = {
        key: [
            t for t in targets if t in components or t in keys or t.startswith(OUTSIDE)
        ]
        for key, targets in _reaches(model, keys).items()
    }
    shape = topology.zoomed([item["key"] for item in inside], links)
    reached = [key for tier in shape.tiers for key in tier if key not in keys]
    return inside + [components.get(key) or _outside(key) for key in reached], shape


def subject_of(key: str) -> str:
    """A service's map key as its node: ``service_blog``, ``service:blog``."""
    return node_id(Kind.SERVICE, registry_entry(key)[1])


def pieces_of(subject: str, model: SystemModel) -> tuple[list[Piece], Lines]:
    """``subject``'s pieces and the lines out of each; none for a part with
    no folder of its own the parts pattern holds to the standard."""
    if subject not in _read:
        _read[subject] = _pieces(subject, {n.id for n in model.nodes})
    return _read[subject]


def _pieces(subject: str, ids: set[str]) -> tuple[list[Piece], Lines]:
    folder = service_pieces.folder_of(subject)
    if folder is None:
        return [], {}
    found = service_pieces.pieces(folder)
    return found, service_pieces.links(folder, found, ids)


def openable(stack: list[dict[str, Any]], model: SystemModel) -> set[str]:
    """The services in ``stack`` that open up, by map key."""
    return {
        key
        for item in stack
        if is_service(key := item["registry"]) and pieces_of(subject_of(key), model)[0]
    }


def service_opened(
    stack: list[dict[str, Any]], model: SystemModel, found: list[Piece], lines: Lines
) -> tuple[list[dict[str, Any]], list[Pair], dict[Pair, dict[str, str]]]:
    """A service opened up: its pieces, each in its lane, then the parts
    they reach (each as the Server zoom draws it), its lines, and the tone
    of each worth a look. A probe draws none, nor does a line to the Server
    it runs in; one piece using another of its lane is said in its hint (a
    line only when the two use each other: tangled); what ``RAIL`` pieces
    use rides the rail, each user badged, instead of a line from each, as
    a piece every lane may use does (Constants, Schemas)."""
    others = {item["registry"]: item for item in stack}
    held = _hanging(model)
    tables = _tables(held)
    pieces = [_piece(piece, held, tables) for piece in found]
    lane = {piece.key: piece.lane for piece in found}
    joined = {
        (source, target)
        for source, place in lane.items()
        if place != "probe"
        for line in lines.get(source, [])
        if (target := line if line in lane else registry_of(line)) != HOST
        and (target in lane or target in others)
    }
    pairs = sorted(joined)
    users = Counter(b for _, b in pairs if b not in lane)
    shared = sorted(key for key, place in lane.items() if place == "rail")
    rail = shared + sorted(key for key, used in users.items() if used >= RAIL)
    titles = {piece.key: piece.title for piece in found}
    for piece in pieces:
        key = piece["key"]
        piece["uses"] = [k for k in rail if (key, k) in joined]
        piece["badges"] = [titles.get(k) or others[k]["title"] for k in piece["uses"]]
        piece["reaches"] = [
            titles[b] for a, b in pairs if a == key and lane.get(b) == lane[key]
        ]
    links = [
        (a, b)
        for a, b in pairs
        if b not in rail and (lane.get(b) != lane[a] or (b, a) in joined)
    ]
    reached = sorted({b for _, b in links if b not in lane})
    docked = [others[key] | {"key": key, "place": "outside"} for key in reached]
    railed = [
        others[key] | {"key": key, "place": "rail"} for key in rail if key not in lane
    ]
    return pieces + docked + railed, links, _tones(links, lane, titles)


def _tones(
    links: list[Pair], lane: dict[str, str], titles: dict[str, str]
) -> dict[Pair, dict[str, str]]:
    """The lines worth a look, each with why (its tone's meaning:
    ``LINE_KEY``): a way in straight to data past the facade, and two pieces
    of a lane using each other (the only lines kept within one), red; a line
    back a lane, amber. The rest go the way a call does."""
    order = [key for key, _ in overseer_map.LANES]
    found: dict[Pair, dict[str, str]] = {}
    for a, b in links:
        here, there = lane[a], lane.get(b, "outside")
        if here == there:
            why = f"{titles[a]} and {titles[b]} use each other (a loop)"
            found[(a, b)] = {"tone": "error", "why": why}
        elif (here, there) == ("entry", "data"):
            why = f"{titles[a]} skips the facade into {titles[b]}"
            found[(a, b)] = {"tone": "error", "why": why}
        elif {here, there} <= set(order) and order.index(there) < order.index(here):
            why = f"{titles[a]} goes back a lane to {titles[b]}"
            found[(a, b)] = {"tone": "warn", "why": why}
    return found


def missing(lacks: list[str]) -> list[dict[str, Any]]:
    """A slot for each part a service lacks (the parts pattern's steps), in
    the lane it would have: a hole in the shape every service shares."""
    return [
        _node(
            f"missing:{label}",
            label,
            f"Missing: {service_parts.HAS[label][0]}",
            figure="missing",
            missing=True,
            place=service_pieces.LANE_OF[label],
        )
        for label in lacks
    ]


def _hanging(model: SystemModel) -> Held:
    """What each module defines (``HANGING``), named by kind: read once
    for ``model``, not every frame for every piece."""
    global _held
    if _held[0] is not model:
        found: Held = {}
        for n in model.nodes:
            if n.kind in HANGING and (module := getattr(n, "module", None)):
                defined = getattr(n, "class_name", n.name)
                held = found.setdefault(module, {}).setdefault(n.kind, [])
                held.append((n.name, defined))
        _held = (model, found)
    return _held[1]


def _tables(held: Held) -> dict[str, str]:
    """Each table the database has, by where it opens on Tables, for a
    service opened up whose pieces hold one; none where none does (a stack
    without the database component)."""
    if not any(Kind.OBJECT in kinds for kinds in held.values()):
        return {}
    from . import overseer_database_browser as browser  # with the database component

    return {name: browser.relationships_url(name) for name in browser.listed()}


def _piece(piece: Piece, held: Held, tables: dict[str, str]) -> dict[str, Any]:
    """A piece's node: what hangs off it counted, and named in its hint with
    its modules (the first ``HOLDS``, each opening its code, a table its
    Tables page where the database has it); a piece nothing hangs off names
    its public functions and classes instead (Deps, its dependencies)."""
    hung = {
        kind: [
            (m, *named)
            for m in piece.modules
            for named in held.get(m, {}).get(kind, [])
        ]
        for kind in HANGING
    }
    index = source_index.project()
    found = {m: index.get(m) for m in piece.modules}
    holds = [(kind, *named) for kind, names in hung.items() for named in names] or [
        (None, m, name, name)
        for m, module in found.items()
        if module is not None
        for name in module.public
    ]
    urls = {m: overseer_code.module_url(m) for m in piece.modules}
    names = [PurePosixPath(path).stem for path in piece.paths]
    files = ", ".join(n for n in names if n != "__init__")
    return _node(
        piece.key,
        piece.title,
        f"Files: {files}" if files else piece.title,
        place=piece.lane,
        url=urls[piece.modules[0]],
        figure=", ".join(
            counted(len(hung[kind]), noun)
            for kind, noun in HANGING.items()
            if hung[kind]
        )
        or None,
        holds=[
            {
                "name": name,
                "url": tables.get(name)
                if kind is Kind.OBJECT and name in tables
                else _opens(urls[m], found[m], defined),
            }
            for kind, m, name, defined in holds[:HOLDS]
        ],
        holds_more=len(holds[HOLDS:]),
    )


def _opens(url: str | None, module: Module | None, name: str) -> str | None:
    """Where ``name`` opens: at its line in ``module``, else at the module's
    top (``url``; a route, by its path, is no top-level name)."""
    line = module.defined.get(name) if url and module else None
    return overseer_code.line_url(module.path, line) if module and line else url


async def name_unkeyed(stack: list[dict[str, Any]]) -> None:
    """An outside provider a service needs a key for that is not set: the
    connection cannot be used, so the node (and the line into it) warns,
    and offers each key's set dialog (``fix``), one click away."""
    wanted = {OUTSIDE + p: names for p, names in calls.provider_keys().items()}
    if not any(item["key"] in wanted for item in stack):
        return
    # Whether each is set, not its value: nothing decrypted every frame.
    keyed = {row.name for row in await secrets.status() if row.is_set}
    for item in stack:
        unset = [n for n in wanted.get(item["key"], []) if n not in keyed]
        if item.get("role") == topology.Role.OUTSIDE and unset:
            item |= {
                "tone": "warn",
                "message": "Not usable: a key it needs is not set.",
                "fix": [{"name": n, "url": overseer_secrets.set_url(n)} for n in unset],
            }


def with_key_lines(
    stack: list[dict[str, Any]], shape: topology.Shape
) -> topology.Shape:
    """A line from where the keys live (``topology.KEYS``) to each outside
    provider whose key is not set (``name_unkeyed``): the core of why it
    cannot be used, drawn."""
    keys = {item["key"] for item in stack}
    unkeyed = [item["key"] for item in stack if item.get("fix")]
    if topology.KEYS not in keys or not unkeyed:
        return shape
    lines = [(topology.KEYS, key) for key in unkeyed]
    return replace(shape, links=[*shape.links, *lines])


def along_server(
    stack: list[dict[str, Any]],
    shape: topology.Shape,
    path: Path,
    whole: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], topology.Shape, Tones]:
    """The Server opened up as ``path`` went through it, nothing else,
    laid out afresh (a caller above what it calls), a line the model
    (``shape``) has none for marked as seen only; the way in drawn from
    the ``whole`` stack's (``_on``)."""
    found, went = _on(stack, path, whole)
    targets = {b for _, b in went}
    callers = [
        key for key in found if key not in targets or any(a == key for a, _ in went)
    ]
    only = path.seen if path.seen is not None else set(went) - set(shape.links)
    seen = {pair: {"observed": True} for pair in went if pair in only}
    calls = {key: [b for a, b in went if a == key] for key in callers}
    return list(found.values()), topology.zoomed(callers, calls), seen


def along_service(
    stack: list[dict[str, Any]],
    tones: Tones,
    path: Path,
    whole: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[Pair], Tones]:
    """A service opened up as ``path`` went through it, nothing else, its
    lines toned as ``tones``: the way in in lanes of its own ahead of it
    (``overseer_map.WAY_IN``), what it reached outside it in the last,
    none on the rail."""
    found, went = _on(stack, path, whole)
    toned = {pair: tones[pair] for pair in went if pair in tones}
    return [_laned(item) for item in found.values()], went, toned


def _on(
    stack: list[dict[str, Any]], path: Path, whole: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[Pair]]:
    """``path``'s parts as this level draws them (one from outside it, the
    way in, as the ``whole`` stack's; an outside provider as its own), and
    its lines between them."""
    items = whole | {item["key"]: item for item in stack}
    found = {
        key: items.get(key) or _outside(key)
        for key in path.nodes
        if key in items or key.startswith(OUTSIDE)
    }
    return found, [(a, b) for a, b in path.links if a in found and b in found]


def _laned(item: dict[str, Any]) -> dict[str, Any]:
    """A piece in its lane, what it uses throughout unbadged (no rail is
    drawn); the way in in its own (``overseer_map.WAY_IN``); anything else
    in the last lane, outside the service."""
    if "badges" in item:
        return item | {"badges": [], "uses": []}
    if item["key"] in topology.EDGE:
        return item | {"place": "edge"}
    return item | {"place": "server" if item["key"] == HOST else "outside"}


def title_of(key: str) -> str:
    """What a map key is called: an outside provider by its name."""
    return (
        key.removeprefix(OUTSIDE)
        if key.startswith(OUTSIDE)
        else get_component_title(key)
    )


def _outside(key: str) -> dict[str, Any]:
    """An outside provider's node: no page, no health check of ours."""
    return _node(
        key,
        title_of(key),
        topology.ROLE_LABELS[topology.Role.OUTSIDE],
        role=topology.Role.OUTSIDE,
    )


def _node(key: str, title: str, message: str, **extra: Any) -> dict[str, Any]:
    """A node of ours with no page or health check (an outside provider, a
    piece of a service, a part it lacks): ``extra`` says the rest."""
    return {
        "key": key,
        "registry": key,
        "title": title,
        "url": None,
        "status": None,
        "tone": "muted",
        "message": message,
        "glance": None,
    } | extra
