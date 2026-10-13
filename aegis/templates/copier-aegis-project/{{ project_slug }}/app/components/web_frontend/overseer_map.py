"""Overseer's home as a map (``?view=map``): the stack's shape
(``topology``) laid out in tiers, top to bottom, each process a node at a
fixed place (so it draws the same every time and nothing overlaps), the
connections as lines between them, and what runs in the webserver as chips
in the Server's node. Each row's nodes are as wide as the row leaves
room for: a busy row's slimmer, the rest wider, a small stack large. Positions are worked out here; the page
only draws."""

from typing import Any

from app.core.ownership import HOST
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
# A compact map (the Server opened up, the Flow): small nodes, a name and
# under it what it costs and carries. Opened up, ``COMPACT_ROW`` to a row,
# cards too, so it fits a screen. Data in a shape that would flatten to a
# slab (a cylinder, a bucket) stands taller, and narrower (input.css,
# ``[data-tall]``).
COMPACT_HEIGHT = 72
COMPACT_ROW = 8
SHAPE_HEIGHT = 96
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
    opened: bool = False,
) -> dict[str, Any]:
    """``overview()``'s entries as placed nodes, the lines between them,
    and the map's height; in ``shape`` (the stack's own by default: the
    Server opened up is ``topology.zoomed``), ``compact`` for small
    nodes, ``across`` for tiers left to right (compact), ``opened`` for
    the Server opened up (``COMPACT_ROW`` to a row, cards too)."""
    items = {item["key"]: item for item in stack}
    found = shape or topology.shape(list(items))
    nodes, place, height = (
        _across(items, found)
        if across
        else _down(items, found, compact, COMPACT_ROW if opened else ROW)
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
    items: dict[str, dict[str, Any]],
    found: topology.Shape,
    compact: bool,
    per_row: int,
) -> Placed:
    """Each tier a row (wrapping past ``per_row``), top to bottom; the Server's
    node grows a row of chips per two services inside it."""
    hosted = [items[key] for key in found.hosted]
    chips = -(-len(hosted) // CHIPS_PER_ROW) * CHIP_ROW
    node_height = COMPACT_HEIGHT if compact else NODE_HEIGHT
    rows = [
        tier[i : i + per_row]
        for tier in found.tiers
        for i in range(0, len(tier), per_row)
    ]
    nodes, place, top = [], {}, 0
    for number, row in enumerate(rows):
        extra = chips if HOST in row else 0
        heights = {k: _height(items[k], node_height, compact) + extra for k in row}
        # The map scrolls sideways, so it clips what runs past its bottom:
        # the last row's hints open above it.
        last = number == len(rows) - 1 and len(rows) > 1
        width = min(FILL * 100 / len(row), MAX_NODE_WIDTH)
        for index, key in enumerate(row):
            x = (index + 0.5) / len(row) * WIDTH
            place[key] = (x, top, heights[key])
            nodes.append(
                _placed(items[key], x, top, heights[key], width, compact)
                | {"hosted": hosted if key == HOST else [], "hint_above": last}
            )
        top += max(heights.values()) + TIER_GAP
    return nodes, place, max(top - TIER_GAP, 0)


def _across(items: dict[str, dict[str, Any]], found: topology.Shape) -> Placed:
    """Each tier a column, left to right, its nodes stacked and centred on
    the tallest column."""
    count = max(len(found.tiers), 1)
    placed = [key for tier in found.tiers for key in tier]
    heights = {k: _height(items[k], COMPACT_HEIGHT, True) for k in placed}
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
            nodes.append(_placed(items[key], x, top, heights[key], width, True))
            top += heights[key] + ACROSS_GAP
    return nodes, place, tallest + HINT_ROOM


# A service opened up (``lanes``): the same lanes for every service, left
# to right as a call goes through it; health and tests probes set apart
# under its ways in, watching the flow rather than in it.
LANES = (
    ("entry", "Entry"),
    ("wiring", "Wiring"),
    ("facade", "Facade"),
    ("domains", "Domains"),
    ("data", "Data"),
    ("outside", "Outside"),
)
LANE_TOP = 40  # room above the nodes for the lanes' names
ASIDE = 48  # how far an arrow within a lane bows out to the side
CLEAR = 4  # how far a line past a lane keeps off the nodes in it
LANE_GAP = 24
PROBE_GAP = 56


def lanes(
    stack: list[dict[str, Any]],
    links: list[tuple[str, str]],
    tones: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    """A service opened up: each entry stacked in its ``place``'s lane, its
    probes under its ways in, what rides the rail listed above it; its
    links as lines between (one side to the next; within a lane, an arrow
    out to the side), toned (and why) where ``tones`` says."""
    width = ACROSS_FILL * 100 / len(LANES)
    half = width / 100 * WIDTH / 2
    columns = {key: (i + 0.5) / len(LANES) * WIDTH for i, (key, _) in enumerate(LANES)}
    place: dict[str, tuple[float, float, float]] = {}
    tops = dict.fromkeys(columns, float(LANE_TOP))
    for item in stack:
        if (lane := item["place"]) in columns:
            height = float(_height(item, COMPACT_HEIGHT, True))
            place[item["key"]] = (columns[lane], tops[lane], height)
            tops[lane] += height + LANE_GAP
    tops["entry"] += PROBE_GAP - LANE_GAP
    for item in stack:
        if item.get("place") == "probe":
            place[item["key"]] = (columns["entry"], tops["entry"], COMPACT_HEIGHT)
            tops["entry"] += COMPACT_HEIGHT + LANE_GAP
    height = max((top + h for _, top, h in place.values()), default=0.0)
    items = {item["key"]: item for item in stack}
    placed = list(place.values())
    return {
        "map_nodes": [
            _placed(item, x, top, h, width, True)
            | {"hint_above": top + h > height * 0.6}
            for item in stack
            if item["key"] in place
            for x, top, h in [place[item["key"]]]
        ],
        "map_links": [
            _lane_line(place[a], place[b], a, items[b], half, placed)
            | tones.get((a, b), {})
            for a, b in links
            if a in place and b in place
        ],
        "map_height": height,
        "map_width": WIDTH,
        "map_compact": True,
        "map_across": False,
        "map_lanes": [
            {"label": label, "left": columns[key] / WIDTH * 100} for key, label in LANES
        ],
        "map_rail": [item for item in stack if item.get("place") == "rail"],
    }


def _lane_line(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    source: str,
    target: dict[str, Any],
    half: float,
    placed: list[tuple[float, float, float]],
) -> dict[str, Any]:
    """A line between lanes, side to side (a line back a lane from its
    node's left), past any lane between along a gap clear of its nodes;
    within one, an arrow from one node's right side out and back into the
    other's, so it reads as a use, not as the lane's stacking. Its middle
    (``mid``: left in percent, top in pixels) is where its hint opens."""
    (x1, y1, h1), (x2, y2, h2) = start, end
    way = 1 if x2 >= x1 else -1
    line = _line(start, end, source, target, way * half) | {"arrow": False}
    y1, y2 = y1 + h1 / 2, y2 + h2 / 2
    if x1 == x2:
        edge, out = x1 + half, x1 + half + ASIDE
        d = f"M {edge:.0f} {y1:.0f} C {out:.0f} {y1:.0f}, {out:.0f} {y2:.0f}, {edge:.0f} {y2:.0f}"
        return line | {"d": d, "arrow": True, "mid": _mid(out, (y1 + y2) / 2)}
    a, b = x1 + way * half, x2 - way * half
    lo, hi = sorted((x1, x2))
    blocks = [(top, top + h) for x, top, h in placed if lo < x < hi]
    if not blocks:  # side to side, as ``_line`` draws it
        return line | {"mid": _mid((a + b) / 2, (y1 + y2) / 2)}
    run = _gap(blocks, y1, y2)
    step = way * (WIDTH / len(LANES) - 2 * half)
    d = (
        f"M {a:.0f} {y1:.0f} C {a + step / 2:.0f} {y1:.0f}, {a + step / 2:.0f} {run:.0f}, {a + step:.0f} {run:.0f} "
        f"L {b - step:.0f} {run:.0f} "
        f"C {b - step / 2:.0f} {run:.0f}, {b - step / 2:.0f} {y2:.0f}, {b:.0f} {y2:.0f}"
    )
    return line | {"d": d, "mid": _mid((a + b) / 2, run)}


def _mid(x: float, y: float) -> dict[str, float]:
    return {"left": x / WIDTH * 100, "top": y}


def _gap(blocks: list[tuple[float, float]], y1: float, y2: float) -> float:
    """The height nearest a line's ends clear of every node in ``blocks``:
    its own, or a gap between the nodes' rows."""
    half_gap = LANE_GAP / 2
    tried = [
        y1,
        y2,
        *(y for top, bottom in blocks for y in (top - half_gap, bottom + half_gap)),
    ]
    clear = [
        y
        for y in tried
        if all(not top - CLEAR <= y <= bottom + CLEAR for top, bottom in blocks)
    ]
    return min(clear, key=lambda y: abs(y - y1) + abs(y - y2))


def _placed(
    item: dict[str, Any],
    x: float,
    top: float,
    height: float,
    width: float,
    compact: bool,
) -> dict[str, Any]:
    """``item`` at its place: across in percent, down in pixels, its size,
    and the side its hint opens from."""
    return item | {
        "left": x / WIDTH * 100,
        "top": top,
        "height": height,
        "width": width,
        "tall": _tall(item, compact),
        "hint_end": _right_half(x),
    }


def _right_half(x: float) -> bool:
    """The map clips what runs past its right edge too: a node right of the
    middle opens its hint from its own right edge, leftward."""
    return x > WIDTH / 2


def _tall(item: dict[str, Any], compact: bool) -> bool:
    return compact and item.get("role") in TALL


def _height(item: dict[str, Any], base: int, compact: bool) -> int:
    return SHAPE_HEIGHT if _tall(item, compact) else base


def overlaid(item: dict[str, Any], tone: str) -> dict[str, str]:
    """An overlay's tone (conformance, traffic) for ``item``: its node takes
    it, the lines into it keep the one they had, so a line's colour means
    only what its key says."""
    return {"tone": tone, "line_tone": item.get("line_tone", item["tone"])}


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
        "tone": target.get("line_tone", target["tone"]),
        "start": source,
        "end": target["key"],
        "queued": topology.queued(source, target["key"]),
        "key": source == topology.KEYS,
    }
