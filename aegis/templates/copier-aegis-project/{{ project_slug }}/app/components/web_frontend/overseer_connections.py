"""Server > Connections: every WebSocket and event stream, open and
recently closed, from ``middleware.connections.history()``.

Filtered by state (open, which counts a connection inside its reconnect
window, or closed) and kind; a row opens its timeline in the drawer. The
table refreshes over SSE while the page is open, filters and all; the
drawer marker sits outside the refreshed part so a refresh never reloads
the drawer.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.components.backend.middleware.connections import find, history
from app.core.formatting import format_span
from app.core.log import logger

from .overseer_live import fragment_events
from .overseer_nav import page_url
from .rendering import drawer_state, status_cell, templates, with_query

PAGE = page_url("components", "backend") + "/connections"
PARTIALS = "/partials/overseer/server/connections"
EVENTS = "/overseer/events/server-connections"
EVENT = "server-connections"
TABLE = "pages/overseer/server/_connections_table.html"
INTERVAL_SECONDS = 2.0
DRAWER_PARAM = "connection"

KINDS = {"websocket": ("WebSocket", "accent"), "sse": ("Event stream", "ok")}
STATES = {
    "up": ("Up", "ok"),
    "reconnecting": ("Reconnecting", "warn"),
    "closed": ("Closed", "muted"),
}
STATE_CHIPS = (("open", "Open"), ("closed", "Closed"), ("all", "All"))
KIND_CHIPS = (
    (None, "All kinds"),
    ("websocket", "WebSockets"),
    ("sse", "Event streams"),
)


def _filters(query: dict[str, str]) -> dict[str, str | None]:
    state = query.get("state")
    kind = query.get("kind")
    return {
        "state": state if state in {s for s, _ in STATE_CHIPS} else "open",
        "kind": kind if kind in KINDS else None,
    }


def _shown(record: dict[str, Any], filters: dict[str, str | None]) -> bool:
    if filters["kind"] and record["kind"] != filters["kind"]:
        return False
    if filters["state"] == "open":
        return record["state"] != "closed"
    return filters["state"] == "all" or record["state"] == "closed"


def _lasted(record: dict[str, Any], now: datetime) -> str | None:
    """How long the current socket has been up, or how long the last one
    lasted; unknown for one a dead server left open (it never closed)."""
    if record["state"] != "up" and record["closed_at"] is None:
        return None
    end = record["closed_at"] or now
    return format_span((end - record["opened_at"]).total_seconds())


def _row(
    record: dict[str, Any], filters: dict[str, str | None], now: datetime
) -> dict[str, Any]:
    return {
        "kind": status_cell(*KINDS[record["kind"]]),
        "path": {
            "label": record["path"],
            "url": with_query(PAGE, **filters, **{DRAWER_PARAM: record["id"]}),
        },
        "client": record["client"],
        "state": status_cell(*STATES[record["state"]]),
        "reconnects": record["reconnects"],
        "lasted": _lasted(record, now),
        "sent": record["sent"],
        "received": record["received"],
    }


def _chips(filters: dict[str, str | None]) -> dict[str, list[dict[str, Any]]]:
    return {
        "state_chips": [
            {
                "label": label,
                "url": with_query(PAGE, state=key, kind=filters["kind"]),
                "active": key == filters["state"],
            }
            for key, label in STATE_CHIPS
        ],
        "kind_chips": [
            {
                "label": label,
                "url": with_query(PAGE, state=filters["state"], kind=key),
                "active": key == filters["kind"],
            }
            for key, label in KIND_CHIPS
        ],
    }


async def table_context(query: dict[str, str]) -> dict[str, Any]:
    """The refreshed part: figures and the filtered table."""
    filters = _filters(query)
    records = await history()
    now = datetime.now(UTC)
    states = [r["state"] for r in records]
    return {
        "figures": [
            {"label": "Up", "value": states.count("up")},
            {"label": "Reconnecting", "value": states.count("reconnecting")},
            {"label": "Closed", "value": states.count("closed")},
            {"label": "Reconnects", "value": sum(r["reconnects"] for r in records)},
        ],
        "rows": [_row(r, filters, now) for r in records if _shown(r, filters)],
    }


async def section_context(query: dict[str, str]) -> dict[str, Any]:
    filters = _filters(query)
    wanted = query.get(DRAWER_PARAM) or ""
    return (
        drawer_state(DRAWER_PARAM, f"{PARTIALS}/{wanted}/drawer" if wanted else None)
        | _chips(filters)
        | await table_context(query)
        | {"events_url": with_query(EVENTS, **filters)}
    )


async def drawer_context(record_id: str) -> dict[str, Any] | None:
    """One connection's timeline, or None when it is no longer remembered."""
    record = await find(record_id)
    if record is None:
        return None
    return {
        "record": record,
        "kind": status_cell(*KINDS[record["kind"]]),
        "state": status_cell(*STATES[record["state"]]),
        "facts": [
            ("Path", record["path"]),
            ("Client", record["client"]),
            ("Browser", record["agent"]),
            ("First opened", record["first_opened"].strftime("%b %d %H:%M:%S")),
            ("Reconnects", record["reconnects"]),
            ("Sent", f"{record['sent']:,}"),
            ("Received", f"{record['received']:,}"),
            ("Ended", record["ended"]),
        ],
        "timeline": [
            {"when": when.strftime("%H:%M:%S"), "what": what, "detail": detail}
            for when, what, detail in record["events"]
        ],
    }


def connections_events(
    query: dict[str, str], max_frames: int | None = None
) -> AsyncIterator[str]:
    """The filtered table over SSE, sent again only when it changes."""

    async def render() -> str:
        try:
            return templates.env.get_template(TABLE).render(
                **await table_context(query)
            )
        except Exception as exc:  # noqa: BLE001 - keep the stream, show nothing new
            logger.warning("Connections read failed", error=str(exc))
            return ""

    return fragment_events(EVENT, render, INTERVAL_SECONDS, max_frames)
