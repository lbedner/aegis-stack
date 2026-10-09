"""Overseer's home as a map (``?view=map``): the stack's shape
(``topology``) laid out in tiers, top to bottom, each process a node at a
fixed place (so it draws the same every time and nothing overlaps), the
connections as lines between them, and what runs in the webserver as chips
in the Server's node. Each row's nodes are as wide as the row leaves
room for: a busy row's slimmer, the rest wider, a small stack large. Positions are worked out here; the page
only draws."""

from typing import Any

from app.services.system import topology

WIDTH = 1000  # the lines' coordinate width (the map is as wide as the page)
NODE_HEIGHT = 136
CHIP_ROW = 34  # each row of chips the Server's node grows by
CHIPS_PER_ROW = 2  # room for a name in full, and its cost to load
TIER_GAP = 96
# Each node's share of the width its row gives it, the rest a gutter; and
# the most a node takes (percent of the map), however small the stack.
FILL = 0.8
MAX_NODE_WIDTH = 28.0
ROW = 5  # the most nodes side by side; a wider tier wraps onto more rows
# A compact map (the Server opened up, the Flow): one-line nodes, more to a
# row. Data in a shape that one line would flatten to a slab (a cylinder, a
# bucket) stands taller, and opened up, narrower.
COMPACT_HEIGHT = 52
COMPACT_ROW = 8
SHAPE_HEIGHT = 80
TALL = frozenset({topology.Role.STORE, topology.Role.BUCKET})
# Across (the Flow): a column a tier, the gap between nodes in one, a
# node's share of its column (the rest is the lines'), and room under the
# map for the last nodes' hints, which the sideways scroll would clip.
ACROSS_GAP = 28
ACROSS_FILL = 0.55
HINT_ROOM = 88


def layout(
    stack: list[dict[str, Any]],
    shape: topology.Shape | None = None,
    *,
    compact: bool = False,
    across: bool = False,
) -> dict[str, Any]:
    """``overview()``'s entries as placed nodes, the lines between them,
    and the map's height; in ``shape`` (the stack's own by default: the
    Server opened up is ``topology.zoomed``), ``compact`` for one-line
    nodes, ``across`` for tiers left to right (compact)."""
    items = {item["key"]: item for item in stack}
    found = shape or topology.shape(list(items))
    nodes, place, height = (_across if across else _down)(
        items, found, compact or across
    )
    half = nodes[0]["width"] / 100 * WIDTH / 2 if across and nodes else None
    return {
        "map_nodes": nodes,
        "map_links": [
            _line(place[a], place[b], a, items[b], half) for a, b in found.links
        ],
        "map_height": height,
        "map_width": WIDTH,
        "map_compact": compact or across,
        "map_across": across,
    }


Placed = tuple[list[dict[str, Any]], dict[str, tuple[float, float, float]], float]


def _down(
    items: dict[str, dict[str, Any]], found: topology.Shape, compact: bool
) -> Placed:
    """Each tier a row (wrapping past ``ROW``), top to bottom; the Server's
    node grows a row of chips per two services inside it."""
    hosted = [items[key] for key in found.hosted]
    chips = -(-len(hosted) // CHIPS_PER_ROW) * CHIP_ROW
    per_row, node_height = (
        (COMPACT_ROW, COMPACT_HEIGHT) if compact else (ROW, NODE_HEIGHT)
    )
    rows = [
        tier[i : i + per_row]
        for tier in found.tiers
        for i in range(0, len(tier), per_row)
    ]
    nodes, place, top = [], {}, 0
    for number, row in enumerate(rows):
        extra = chips if topology.HOST in row else 0
        heights = {k: _height(items[k], node_height, compact) + extra for k in row}
        # The map scrolls sideways, so it clips what runs past its bottom:
        # the last row's hints open above it.
        last = number == len(rows) - 1 and len(rows) > 1
        width = min(FILL * 100 / len(row), MAX_NODE_WIDTH)
        for index, key in enumerate(row):
            x = (index + 0.5) / len(row) * WIDTH
            place[key] = (x, top, heights[key])
            nodes.append(
                items[key]
                | {"left": x / WIDTH * 100, "top": top, "height": heights[key]}
                | {"width": width, "hosted": hosted if key == topology.HOST else []}
                | {"hint_above": last, "tall": _tall(items[key], compact)}
            )
        top += max(heights.values()) + TIER_GAP
    return nodes, place, max(top - TIER_GAP, 0)


def _across(
    items: dict[str, dict[str, Any]], found: topology.Shape, compact: bool
) -> Placed:
    """Each tier a column, left to right, its nodes stacked and centred on
    the tallest column."""
    count = max(len(found.tiers), 1)
    placed = [key for tier in found.tiers for key in tier]
    heights = {k: _height(items[k], COMPACT_HEIGHT, compact) for k in placed}
    spans = [
        sum(heights[k] for k in tier) + ACROSS_GAP * (len(tier) - 1)
        for tier in found.tiers
    ]
    tallest = max(spans, default=0)
    nodes, place, width = [], {}, ACROSS_FILL * 100 / count
    for index, tier in enumerate(found.tiers):
        x, top = (index + 0.5) / count * WIDTH, (tallest - spans[index]) / 2
        for key in tier:
            place[key] = (x, top, heights[key])
            nodes.append(
                items[key]
                | {"left": x / WIDTH * 100, "top": top, "height": heights[key]}
                | {"width": width, "tall": _tall(items[key], compact)}
            )
            top += heights[key] + ACROSS_GAP
    return nodes, place, tallest + HINT_ROOM


def _tall(item: dict[str, Any], compact: bool) -> bool:
    return compact and item.get("role") in TALL


def _height(item: dict[str, Any], base: int, compact: bool) -> int:
    return SHAPE_HEIGHT if _tall(item, compact) else base


def _line(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    source: str,
    target: dict[str, Any],
    half: float | None = None,
) -> dict[str, Any]:
    """A curve from the bottom of one node to the top of the next or, given
    ``half`` a node's width (across), from one's right side to the next's
    left, at their middles; in the tone of what it leads to: a call fails
    when what it calls does, so a failing part's lines into healthy ones stay
    plain. Dashed either side of the queue, dotted from where the keys live."""
    (x1, y1, h1), (x2, y2, h2) = start, end
    if half is None:
        y1 += h1
        middle = (y1 + y2) / 2
        bends = f"{x1:.0f} {middle:.0f}, {x2:.0f} {middle:.0f}"
    else:
        x1, y1, x2, y2 = x1 + half, y1 + h1 / 2, x2 - half, y2 + h2 / 2
        middle = (x1 + x2) / 2
        bends = f"{middle:.0f} {y1:.0f}, {middle:.0f} {y2:.0f}"
    return {
        "d": f"M {x1:.0f} {y1:.0f} C {bends}, {x2:.0f} {y2:.0f}",
        "tone": target["tone"],
        "start": source,
        "end": target["key"],
        "queued": topology.queued(source, target["key"]),
        "key": source == topology.KEYS,
    }
