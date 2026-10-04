"""Context for the Overseer Redis page's sections.

The Flet redis modal's Overview, Slow queries and Connections, with the
Overview led by a keyspace map: what each part of Redis is for, by the key
families their owners declare (``app.services.system.redis_keys``). The map
is pushed over its own SSE stream while the page is open.
"""

from collections.abc import AsyncIterator
from typing import Any

from app.core import series
from app.core.formatting import format_span
from app.services.system import redis_keys, ui_redis
from app.services.system.models import ComponentStatus
from app.services.system.ui_database import display_url

from .filters import color_tone
from .overseer_live import fragment_events
from .overseer_nav import SectionRequest
from .rendering import fragment, status_cell

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Activity", {"slow-queries": "Slow queries", "connections": "Connections"}),
)

PARTIALS = "/partials/overseer/redis"
KEYSPACE_EVENTS = "/overseer/events/redis-keyspace"
KEYSPACE_EVENT = "redis-keyspace"
KEYSPACE_TEMPLATE = "pages/overseer/redis/_keyspace.html"
KEYSPACE_INTERVAL_SECONDS = 3.0


async def load_keyspace() -> dict[str, Any]:
    """The keyspace map, or what went wrong reading it (the keyspace
    sampler's reading)."""
    return await series.reading(redis_keys.KEYSPACE)


async def load_peek(family: int) -> dict[str, Any] | None:
    """A family and its newest key's first entries; None if unknown."""
    return await redis_keys.peek(family)


def peek_view(peek: dict[str, Any] | None) -> dict[str, Any] | None:
    """A peek's two-column rows as ``data_table`` rows."""
    if peek is None:
        return None
    return peek | {"rows": [{"a": a, "b": b} for a, b in peek.get("rows", [])]}


def keyspace_view(keyspace: dict[str, Any]) -> dict[str, Any]:
    """The map with its times in words, for ``_keyspace.html``."""
    families = [
        f
        | {
            "ttl_label": format_span(f.get("ttl")),
            "idle_label": format_span(f.get("idle")),
        }
        for f in keyspace.get("families", [])
    ]
    return {"keyspace": keyspace | {"families": families}, "partials": PARTIALS}


def render_keyspace(keyspace: dict[str, Any]) -> str:
    return fragment(KEYSPACE_TEMPLATE, **keyspace_view(keyspace))


def keyspace_events(max_frames: int | None = None) -> AsyncIterator[str]:
    """The keyspace card over SSE, sent again only when it changes."""

    async def render() -> str:
        return render_keyspace(await load_keyspace())

    return fragment_events(
        KEYSPACE_EVENT, render, KEYSPACE_INTERVAL_SECONDS, max_frames
    )


def _figures(meta: dict[str, Any]) -> list[dict[str, Any]]:
    rate = float(meta.get("hit_rate_percent") or 0)
    return [
        {
            "label": "Memory",
            "value": meta.get("used_memory_human", "-"),
            "caption": f"peak {meta.get('used_memory_peak_human', '-')}",
        },
        {
            "label": "Ops / sec",
            "value": meta.get("instantaneous_ops_per_sec", 0),
            "caption": f"{meta.get('total_keys', 0)} keys",
        },
        {
            "label": "Hit rate",
            "value": f"{rate:.1f}%",
            "caption": f"up {ui_redis.uptime(meta.get('uptime_in_seconds', 0))}",
            "tone": color_tone(ui_redis.hit_rate_color(rate)),
        },
        {
            "label": "Clients",
            "value": meta.get("connected_clients", 0),
            "caption": f"Redis {meta.get('version', '')}".strip(),
        },
    ]


def _slow_rows(meta: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "command": q["command"],
            "full": q["full"],
            "when": q["when"],
            "duration": status_cell(
                f"{q['duration_ms']:,.2f}ms", color_tone(q["color"])
            ),
        }
        for q in ui_redis.slow_queries(meta)
    ]


def _connection(meta: dict[str, Any]) -> list[tuple[str, Any]]:
    return [
        ("URL", display_url(str(meta.get("url", "Not configured")))),
        ("Database", meta.get("db")),
        ("Version", meta.get("version")),
        ("Connected", meta.get("connected_clients", 0)),
        ("Blocked", meta.get("blocked_clients", 0)),
        ("Total connections", meta.get("total_connections_received", 0)),
    ]


async def section_context(
    section: str, cache: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs beyond the Redis status."""
    meta = cache.metadata or {}
    if section == "overview":
        return {
            "figures": _figures(meta),
            "keyspace_events": KEYSPACE_EVENTS,
            "keyspace_event": KEYSPACE_EVENT,
        } | keyspace_view(await load_keyspace())
    if section == "slow-queries":
        return {"slow": _slow_rows(meta)}
    if section == "connections":
        return {
            "connection": _connection(meta),
            "clients": list(meta.get("active_clients") or []),
        }
    return {}
