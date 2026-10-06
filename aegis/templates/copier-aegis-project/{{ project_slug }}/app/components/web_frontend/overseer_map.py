"""Overseer's home as a map (``?view=map``): the stack's shape
(``topology``) laid out in tiers, top to bottom, each process a node at a
fixed place (so it draws the same every time and nothing overlaps), the
connections as lines between them, and what runs in the webserver as chips
in the Server's node. Nodes are as wide as the busiest tier leaves room
for, so a small stack draws large. Positions are worked out here; the page
only draws."""

from typing import Any

from app.services.system import topology

WIDTH = 1000  # the lines' coordinate width (the map is as wide as the page)
NODE_HEIGHT = 136
CHIP_ROW = 34  # each row of chips the Server's node grows by
CHIPS_PER_ROW = 2  # room for a name in full, and its cost to load
TIER_GAP = 96
# Each node's share of the width its tier gives it, the rest a gutter; and
# the most a node takes (percent of the map), however small the stack.
FILL = 0.8
MAX_NODE_WIDTH = 28.0


def layout(stack: list[dict[str, Any]]) -> dict[str, Any]:
    """``overview()``'s entries as placed nodes, the lines between them,
    and the map's height."""
    items = {item["key"]: item for item in stack}
    found = topology.shape(list(items))
    hosted = [items[key] for key in found.hosted]
    chips = -(-len(hosted) // CHIPS_PER_ROW) * CHIP_ROW
    busiest = max((len(tier) for tier in found.tiers), default=1)
    nodes, place, top = [], {}, 0
    for tier in found.tiers:
        height = NODE_HEIGHT + (chips if topology.HOST in tier else 0)
        for index, key in enumerate(tier):
            x = (index + 0.5) / len(tier) * WIDTH
            place[key] = (x, top, height)
            nodes.append(
                items[key]
                | {"left": x / WIDTH * 100, "top": top, "height": height}
                | {"hosted": hosted if key == topology.HOST else []}
            )
        top += height + TIER_GAP
    return {
        "map_nodes": nodes,
        "map_links": [_line(place[a], place[b], a, items[b]) for a, b in found.links],
        "map_height": max(top - TIER_GAP, 0),
        "map_width": WIDTH,
        "map_node_width": min(FILL * 100 / busiest, MAX_NODE_WIDTH),
    }


def _line(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    source: str,
    target: dict[str, Any],
) -> dict[str, str]:
    """A curve from the bottom of one node to the top of the next, in the
    tone of the one it leads to: a call fails when what it calls does, so a
    failing part's lines into healthy ones stay plain."""
    (x1, y1, h1), (x2, y2, _) = start, end
    y1 += h1
    middle = (y1 + y2) / 2
    return {
        "d": f"M {x1:.0f} {y1:.0f} C {x1:.0f} {middle:.0f}, {x2:.0f} {middle:.0f}, {x2:.0f} {y2:.0f}",
        "tone": target["tone"],
        "start": source,
        "end": target["key"],
    }
