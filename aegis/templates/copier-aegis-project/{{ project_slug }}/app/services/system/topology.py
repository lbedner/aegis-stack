"""The stack's shape, as Overseer's Map draws it: what runs as its own
process, in tiers (the edge, the app, its data), the connections between
them, and everything that runs inside the webserver instead (the services,
the web frontend). Drawn from what is installed, so a stack without Redis
has no Cache and no line to it. ``zoomed`` is the Server opened up: what
runs inside it, and what that reaches (the system model's calls). Each
part's place is its own declaration (``parts.PARTS``). No UI framework
imports.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.core.ontology.parts import INSIDE, PLACED, QUEUE, placement
from app.core.ownership import TAKES


class Role(StrEnum):
    """What a part is on the map, where it is not compute (a box): data in
    its own shape, the same size, and an outside provider as a pill."""

    STORE = "store"
    QUEUE = "queue"
    BUCKET = "bucket"
    OUTSIDE = "outside"


# Every part the map can place, as each declares itself (``parts.PARTS``:
# its row, its shape, its lines, ``ontology.parts.PLACED``), the worker's
# queue among them. None of it is kept here.
_ORDERED = sorted(PLACED, key=placement)
# Each tier's processes, by health name, in drawing order: the edge, the
# app, its data.
TIERS = tuple(tuple(n for n in _ORDERED if PLACED[n].tier == t) for t in range(3))
# Who talks to whom: requests in through the ingress; the app's processes
# to their stores; work handed to the queue, and taken from it.
LINKS = tuple((n, d) for tier in TIERS for n in tier for d in PLACED[n].depends_on)
# A part that takes from another rather than calls it: in the way work
# flows (``flow``), the line runs the other way.
PULLS = frozenset(TAKES.items())
# Where every key lives: a line from it is a key it holds for another part.
KEYS = next(n for n in _ORDERED if PLACED[n].holds_keys)
ROLES: dict[str, Role] = {n: Role(p.role) for n, p in PLACED.items() if p.role}
# Each shape, named for the map's key.
ROLE_LABELS: dict[Role, str] = {
    Role.STORE: "Store",
    Role.QUEUE: "Queue",
    Role.BUCKET: "Object storage",
    Role.OUTSIDE: "Outside the stack",
}


@dataclass(frozen=True)
class Shape:
    tiers: list[list[str]]
    links: list[tuple[str, str]]
    hosted: list[str]


def shape(installed: Sequence[str]) -> Shape:
    """``installed`` (health component names, in the sidebar's order) as
    tiers, the connections whose both ends are there, and the rest."""
    present = set(installed)
    placed = {name for tier in TIERS for name in tier}
    tiers = [[name for name in tier if name in present] for tier in TIERS]
    return Shape(
        tiers=[tier for tier in tiers if tier],
        links=[(a, b) for a, b in LINKS if a in present and b in present],
        hosted=[name for name in installed if name not in placed],
    )


def queued(a: str, b: str) -> bool:
    """Whether the line from ``a`` to ``b`` is queued work: handed to the
    queue, or taken from it, never waited on."""
    return QUEUE in (a, b)


def flow(installed: Sequence[str]) -> Shape:
    """The way work moves through the stack's own processes and stores, a
    tier each step (``zoomed``'s rule): who takes work from the queue drawn
    after it (``PULLS``), so the queue sits between who hands work over and
    the worker. What runs inside the webserver is left in it."""
    found = shape(installed)
    pairs = [(b, a) if (a, b) in PULLS else (a, b) for a, b in found.links]
    placed = [key for tier in found.tiers for key in tier]
    return zoomed(placed, {key: [b for a, b in pairs if a == key] for key in placed})


def zoomed(inside: Sequence[str], links: Mapping[str, Sequence[str]]) -> Shape:
    """The Server opened up: what runs inside it (``inside``) in tiers, a
    caller above what it calls (Documents above AI above RAG), then a last
    tier of everything they reach outside it; each tier under what reaches
    it (``_under_callers``)."""
    present = set(inside)
    calls = {key: [t for t in links.get(key, ()) if t in present] for key in inside}
    depth: dict[str, int] = {}

    def below(key: str, seen: frozenset[str] = frozenset()) -> int:
        """The longest chain of calls under ``key`` (a cycle ends one)."""
        if key not in depth:
            under = [t for t in calls[key] if t not in seen]
            depth[key] = 1 + max((below(t, seen | {key}) for t in under), default=-1)
        return depth[key]

    levels = sorted({below(key) for key in inside}, reverse=True)
    tiers = [[key for key in inside if depth[key] == level] for level in levels]
    reached = {t for key in inside for t in links.get(key, ()) if t not in present}
    if reached:
        tiers.append(sorted(reached, key=lambda t: (":" in t, t)))
    pairs = [(key, t) for key in inside for t in links.get(key, ())]
    return Shape(tiers=_under_callers(tiers, pairs), links=pairs, hosted=[])


def _under_callers(
    tiers: list[list[str]], links: list[tuple[str, str]]
) -> list[list[str]]:
    """Each tier after the first in the order that keeps lines short: a
    node at the average place (0 to 1 across) of the nodes above linking to
    it; one nothing above reaches keeps its place, after those."""
    place: dict[str, float] = {}
    ordered = []
    for tier in tiers:

        def pull(key: str) -> tuple[int, float]:
            above = [place[a] for a, b in links if b == key and a in place]
            return (0, sum(above) / len(above)) if above else (1, 0.0)

        tier = sorted(tier, key=pull) if place else tier
        place |= {key: (i + 0.5) / len(tier) for i, key in enumerate(tier)}
        ordered.append(tier)
    return ordered


def causes(
    failing: set[str], links: Sequence[tuple[str, str]] = LINKS
) -> dict[str, list[str]]:
    """Each of the ``failing`` parts that depends on another failing one
    (``links``, followed down), and the failing parts at the bottom of it:
    the Database down names the Database on the Server and on the Ingress in
    front of it. A part failing on its own is left out; one inside another
    (``INSIDE``) fails with it."""
    followed = [*links, *INSIDE.items()]

    def roots(name: str, seen: frozenset[str]) -> list[str]:
        """``name``'s failing roots; a part already on the way ends it (two
        that depend on each other are each other's cause)."""
        seen = seen | {name}
        below = [b for a, b in followed if a == name and b in failing and b not in seen]
        return list(dict.fromkeys(r for b in below for r in roots(b, seen) or [b]))

    return {
        name: found for name in sorted(failing) if (found := roots(name, frozenset()))
    }
