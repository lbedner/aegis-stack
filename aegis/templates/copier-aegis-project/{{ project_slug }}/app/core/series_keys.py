"""What the live charts (``app.core.series``) keep in the shared cache, as
key families for Overseer's keyspace map (``redis_keys``): each series'
points, its history tiers, and the samplers' own keys."""

from typing import Any

from app.core import series
from app.core.formatting import counted
from app.core.key_family import KeyFamily


def _ours(pattern: str, kind: str, name: str, purpose: str, **more: Any) -> KeyFamily:
    return KeyFamily(
        pattern, kind, name, purpose, "Live charts", db="CACHE_REDIS_DB", **more
    )


REDIS_KEYS = (
    _ours(
        series.PREFIX + "*",
        "zset",
        "Chart history",
        "Each chart series' points for the last hour, one sorted set a series",
        columns=("Point", "Time"),
        holds="point",
    ),
    *(
        _ours(
            series.tier(step)[0] + "*",
            "list",
            f"Chart history, {step // 60} min",
            f"Each series' highest point every {step // 60} minutes, kept "
            f"{counted(keep // series.DAY, 'day')}",
            columns=("Position", "Bucket:highest"),
            holds="point",
        )
        for step, keep in series.TIERS
    ),
    _ours(
        series.INDEX.rstrip(":") + "*",  # the tiers' indexes too
        "set",
        "Chart series lists",
        "Each sampler's series, so a chart's read never scans the keyspace",
    ),
    _ours(
        series.LATEST + "*",
        "string",
        "Last readings",
        "Each sampler's latest reading, whole",
    ),
    _ours(
        series.WATCH + "*",
        "string",
        "Watched samplers",
        "Set while a view looks: full pace",
    ),
    _ours(
        series.CLAIM + "*",
        "string",
        "Sampler claims",
        "Held by the process reading this tick, or folding a bucket into history",
    ),
)
