"""The stack's shape, as Overseer's Map draws it: what runs as its own
process, in tiers (the edge, the app, its data), the connections between
them, and everything that runs inside the webserver instead (the services,
the web frontend). Drawn from what is installed, so a stack without Redis
has no Cache and no line to it. No UI framework imports.
"""

from collections.abc import Sequence
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


def causes(failing: set[str]) -> dict[str, list[str]]:
    """Each of the ``failing`` parts that depends on another failing one
    (``LINKS``, followed down), and the failing parts at the bottom of it:
    the Database down names the Database on the Server and on the Ingress in
    front of it. A part failing on its own is left out."""

    def roots(name: str) -> list[str]:
        below = [b for a, b in LINKS if a == name and b in failing]
        return list(dict.fromkeys(r for b in below for r in roots(b) or [b]))

    return {name: found for name in sorted(failing) if (found := roots(name))}
