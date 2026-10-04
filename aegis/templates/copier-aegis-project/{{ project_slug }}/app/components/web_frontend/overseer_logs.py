"""Logs in Overseer: the Logs section every page with a container behind it
gets after Container (``overseer_sections`` adds both), and Overseer > Logs,
every such page's lines in one view with a link to each line's page. Both
show the window's lines (``ui_logs``), newest first, filtered by window,
level and text (and, for every page, by service), then follow new lines over
SSE while open: Docker pushes them, so nothing polls."""

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from app.core import series
from app.services.system import ui_logs
from app.services.system.models import ComponentStatus

from .overseer_live import frame, heartbeat
from .overseer_nav import NavItem, SectionRequest, runtime_page_url
from .rendering import fragment, with_query

SECTION = {"logs": "Logs"}
EVENTS = "/overseer/events/logs/{page}"
EVERY_EVENTS = "/overseer/events/logs"
EVENT = "logs-lines"
ROWS = "pages/overseer/_logs_rows.html"
LEVELS = [{"id": level, "name": level.capitalize()} for level in ui_logs.LEVELS]
ORDERS = [{"id": order, "name": name} for order, name in ui_logs.ORDERS]
# A level's badge tone; info and an unlevelled line stay plain.
TONES = {"debug": "muted", "warning": "warn", "error": "error", "critical": "error"}

# Overseer > Logs: its sidebar entry (no health check behind it) and its one
# section, the shared ``_logs.html``.
SECTIONS = ((None, {"overview": "Logs"}),)
ITEM = NavItem(
    group="logs",
    name="logs",
    title="Logs",
    url="/overseer/logs",
    status="",
    component=ComponentStatus(name="logs", message=""),
)


async def context(page: str, query: Mapping[str, str]) -> dict[str, Any]:
    """One page's Logs section."""
    return await _context([page], query, EVENTS.format(page=page))


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """Overseer > Logs: the services ticked, every one when none is."""
    sources = await ui_logs.sources()
    ticked = _ticked(req.query, sources)
    every = await _context(
        ticked or [s["page"] for s in sources], req.query, EVERY_EVENTS, service=ticked
    )
    return every | {
        "section_subtitle": "Every service's lines in one place.",
        "logs_services": [
            {"value": s["page"], "label": s["title"], "checked": s["page"] in ticked}
            for s in sources
        ],
        "logs_links": _links(sources),
    }


def _ticked(query: Mapping[str, str], sources: list[dict[str, str]]) -> list[str]:
    """The services a query ticks that this stack has."""
    getlist = getattr(query, "getlist", None)
    asked = set(getlist("service")) if getlist else set()
    return [s["page"] for s in sources if s["page"] in asked]


def _links(sources: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Each page's title and Overseer URL, for a line's service cell."""
    return {
        s["page"]: {
            "title": s["title"],
            "url": runtime_page_url(s["page"]),
        }
        for s in sources
    }


async def _context(
    pages: Sequence[str], query: Mapping[str, str], events: str, **more: Any
) -> dict[str, Any]:
    """The window's lines and the filters that chose them, and the stream
    that follows them (with the same level, text, order and ``more``)."""
    level = query.get("level", "") if query.get("level") in ui_logs.LEVELS else ""
    q = query.get("q", "")
    order = ui_logs.order_of(query)
    return {
        "logs": await ui_logs.recent(pages, query),
        "logs_tones": TONES,
        "logs_events": with_query(events, level=level, q=q, order=order, **more),
        "logs_windows": ui_logs.WINDOWS,
        "logs_window": series.window_of(
            query.get("window"), ui_logs.WINDOWS, ui_logs.DEFAULT_WINDOW
        ),
        "logs_levels": LEVELS,
        "logs_level": level,
        "logs_q": q,
        "logs_orders": ORDERS,
        "logs_order": order,
    }


def render(
    rows: list[dict[str, Any]],
    links: dict[str, dict[str, str]] | None = None,
    q: str = "",
) -> str:
    return fragment(ROWS, rows=rows, tones=TONES, links=links, q=q)


def events(page: str, query: Mapping[str, str]) -> AsyncIterator[str]:
    """One page's new lines as rows to add, over SSE, while it is open."""
    return _stream([page], query, None)


async def everything_events(query: Mapping[str, str]) -> AsyncIterator[str]:
    """Overseer > Logs' new lines, each with its service, over SSE."""
    sources = await ui_logs.sources()
    pages = _ticked(query, sources) or [s["page"] for s in sources]
    async for sent in _stream(pages, query, _links(sources)):
        yield sent


def _stream(
    pages: Sequence[str],
    query: Mapping[str, str],
    links: dict[str, dict[str, str]] | None,
) -> AsyncIterator[str]:
    async def lines() -> AsyncIterator[str]:
        async for batch in ui_logs.follow(pages, query):
            yield frame(EVENT, render(batch, links, query.get("q", "")))

    return heartbeat(lines())
