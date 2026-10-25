"""The map's heat (``?overlay=traffic``): each node toned by how much ran
through it (``edges``: what the running app did along the lines touching
it this build, Overseer's own reads included), the busiest the hottest.

Read at most every ``FRESH_SECONDS``, not every tick: the counts move no
faster, and the map's stream re-sends only what changed."""

from collections import Counter
import time
from typing import Any

from app.core import edges
from app.core.formatting import counted
from app.core.ontology.model import Kind
from app.services.system.staged_paths import registry_of

from .overseer_map import overlaid

TRAFFIC = "traffic"
# What the overlay shows, said under its chip while it is on.
SAYS = "Each part toned by the calls through it this build, the busiest red."
FRESH_SECONDS = 15.0
# ponytail: tones by share of the busiest node, not ``core.thresholds``'
# configured levels: traffic has no absolute alarm, only more and less.
WARM, HOT = 0.33, 0.66

Values = dict[str, int]  # by map key

_read: tuple[float, Values] = (0.0, {})


async def _traffic() -> Values:
    """Calls by node: the more of what came in and what went out, so a
    call passing through (served once, querying three times) is three,
    not four. A query is counted to the database and to its table: the
    table's is left out, so it is one call, not two; a call within a part
    (Auth to its users) is no call between nodes."""
    into: Counter[str] = Counter()
    out: Counter[str] = Counter()
    for (source, target), seen in (await edges.observed()).items():
        pair = (source, target)
        if edges.OTHER in pair or any(n.startswith(f"{Kind.OBJECT}:") for n in pair):
            continue
        if (key := registry_of(source)) == (into_key := registry_of(target)):
            continue
        out[key] += seen.count
        into[into_key] += seen.count
    return {key: max(into[key], out[key]) for key in into | out}


async def heat(stack: list[dict[str, Any]]) -> None:
    """Tone each entry of ``stack`` by its traffic, and say how much."""
    global _read
    at, values = _read
    if time.monotonic() - at > FRESH_SECONDS:
        values = await _traffic()
        _read = (time.monotonic(), values)
    top = max(values.values(), default=0)
    for item in stack:
        value = values.get(item["registry"])
        if value is None:
            continue
        share = value / top if top else 0
        tone = "error" if share >= HOT else "warn" if share >= WARM else "ok"
        item |= overlaid(item, tone) | {
            "heat": True,  # filled in its tone (``data-heat``)
            "figure": counted(value, "call"),
        }
