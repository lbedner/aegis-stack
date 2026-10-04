"""Overseer's home as a map (``?view=map``): the stack's shape
(``topology``) laid out in tiers, top to bottom, each process a node at a
fixed place (so it draws the same every time and nothing overlaps), the
connections as lines between them, and what runs in the webserver as chips
in the Server's node. Positions are worked out here; the page only draws."""

from typing import Any

from app.services.system import topology

from .filters import worst_tone

WIDTH = 1000  # the lines' coordinate width (the map is as wide as the page)
NODE_HEIGHT = 120
CHIP_ROW = 30  # each row of chips the Server's node grows by
CHIPS_PER_ROW = 3
TIER_GAP = 64


def layout(stack: list[dict[str, Any]]) -> dict[str, Any]:
    """``overview()``'s entries as placed nodes, the lines between them,
    and the map's height."""
    items = {item["key"]: item for item in stack}
    found = topology.shape(list(items))
    hosted = [items[key] for key in found.hosted]
    chips = -(-len(hosted) // CHIPS_PER_ROW) * CHIP_ROW
    nodes, place, top = [], {}, 0
    for tier in found.tiers:
        height = NODE_HEIGHT + (chips if topology.HOST in tier else 0)
        for index, key in enumerate(tier):
            x = (index + 1) / (len(tier) + 1) * WIDTH
            place[key] = (x, top, height)
            nodes.append(
                items[key]
                | {"left": x / WIDTH * 100, "top": top, "height": height}
                | {"hosted": hosted if key == topology.HOST else []}
            )
        top += height + TIER_GAP
    return {
        "map_nodes": nodes,
        "map_links": [
            _line(place[a], place[b], items[a], items[b]) for a, b in found.links
        ],
        "map_height": max(top - TIER_GAP, 0),
        "map_width": WIDTH,
    }


def _line(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    a: dict[str, Any],
    b: dict[str, Any],
) -> dict[str, str]:
    """A curve from the bottom of one node to the top of the next, in the
    worse of its two ends' tones."""
    (x1, y1, h1), (x2, y2, _) = start, end
    y1 += h1
    middle = (y1 + y2) / 2
    return {
        "d": f"M {x1:.0f} {y1:.0f} C {x1:.0f} {middle:.0f}, {x2:.0f} {middle:.0f}, {x2:.0f} {y2:.0f}",
        "tone": worst_tone((a["tone"], b["tone"])),
    }
