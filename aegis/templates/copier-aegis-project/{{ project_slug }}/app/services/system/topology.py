"""The stack's shape, as Overseer's Map draws it: what runs as its own
process, in tiers (the edge, the app, its data), the connections between
them, and everything that runs inside the webserver instead (the services,
the web frontend). Drawn from what is installed, so a stack without Redis
has no Cache and no line to it. ``zoomed`` is the Server opened up: what
runs inside it, and what that reaches (``service_links``). No UI framework
imports.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Each tier's processes, by their health component name, in drawing order.
TIERS: tuple[tuple[str, ...], ...] = (
    ("ingress",),
    ("backend", "worker", "scheduler"),
    ("database", "cache", "storage", "ollama"),
)
# Who talks to whom: requests in through the ingress; the app's processes
# to their stores, the cache being the worker's broker too.
LINKS: tuple[tuple[str, str], ...] = (
    ("ingress", "backend"),
    ("backend", "database"),
    ("backend", "cache"),
    ("backend", "storage"),
    ("backend", "ollama"),
    ("worker", "cache"),
    ("worker", "database"),
    ("scheduler", "database"),
    ("scheduler", "cache"),
)
HOST = "backend"  # what has no process of its own runs in the webserver
# What a caller hands work to rather than calls and waits on: a line into it
# is queued work.
QUEUED = frozenset({"worker"})
# Where every key lives: a line from it is a key it holds for another part.
KEYS = "secrets"


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
    front of it. A part failing on its own is left out."""

    def roots(name: str) -> list[str]:
        below = [b for a, b in links if a == name and b in failing]
        return list(dict.fromkeys(r for b in below for r in roots(b) or [b]))

    return {name: found for name in sorted(failing) if (found := roots(name))}
