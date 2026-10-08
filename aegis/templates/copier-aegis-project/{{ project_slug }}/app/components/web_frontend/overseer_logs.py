"""Logs in Overseer: the Logs section every page with a container behind it
gets after Container (``overseer_sections`` adds both), and Overseer > Logs,
every such page's lines in one view with a link to each line's page. Both
show the window's lines (``ui_logs``), newest first, filtered by window,
level and text (and, for every page, by service), then follow new lines over
SSE while open: Docker pushes them, so nothing polls."""

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from starlette.datastructures import QueryParams

from app.core import series
from app.services.system import ui_logs
from app.services.system.models import ComponentStatus

from .overseer_live import frame, heartbeat
from .overseer_nav import (
    NavItem,
    SectionRequest,
    current_navigation,
    runtime_page_url,
)
from .rendering import fragment, with_query

SECTION = {"logs": "Logs"}
EVENTS = "/overseer/events/logs/{page}"
EVERY_EVENTS = "/overseer/events/logs"
EVENT = "logs-lines"
ROWS = "pages/overseer/_logs_rows.html"
ORDERS = [{"id": order, "name": name} for order, name in ui_logs.ORDERS]

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
    """One page's Logs section, with a container picker when it has several."""
    found = await ui_logs.containers([page])
    sources = ui_logs.sources(found)
    _pages, _ticked, picked = _reading(query, sources)
    shown = await _context(
        [page], found, query, EVENTS.format(page=page), container=picked
    )
    return shown | {
        "logs_containers": [
            _option(c["name"], c["label"], c["name"] in picked)
            for s in sources
            for c in s["containers"]
        ]
    }


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """Overseer > Logs: the services ticked, every one when none is."""
    found = await ui_logs.containers()
    sources = ui_logs.sources(found)
    pages, ticked, picked = _reading(req.query, sources)
    every = await _context(
        pages,
        found,
        req.query,
        EVERY_EVENTS,
        service=ticked,
        container=picked,
        app_service=ui_logs.listed(req.query, "app_service"),
    )
    return every | {
        "section_subtitle": "Every service's lines in one place.",
        "logs_services": picker(sources, req.query),
        "logs_links": _links(sources),
    }


def picker(
    sources: list[dict[str, Any]], query: Mapping[str, str]
) -> list[dict[str, Any]]:
    """The Services checklist Logs and Errors share: each page with a
    container, its containers when it has several, then the application
    services (``ui_logs.Picked`` reads what it ticks)."""
    picked = ui_logs.Picked.of(query)
    options: list[dict[str, Any]] = []
    for s in sources:
        options.append(
            _option(s["page"], s["title"], s["page"] in picked.services, name=None)
        )
        options += [
            _option(
                c["name"],
                f"{s['title']} · {c['label']}",
                c["name"] in picked.containers,
            )
            | {"indent": True}
            for c in s["containers"]
        ]
    return options + [
        _option(
            item.name, item.title, item.name in picked.app_services, name="app_service"
        )
        for item in current_navigation().get("services", [])
    ]


def _reading(
    query: Mapping[str, str], sources: list[dict[str, Any]]
) -> tuple[list[str], list[str], list[str]]:
    """The pages to read, and the services and containers a query ticks that
    this stack has: those pages, or every one when nothing is ticked."""
    asked = set(ui_logs.listed(query, "service"))
    wanted = set(ui_logs.listed(query, "container"))
    ticked = [s["page"] for s in sources if s["page"] in asked]
    picked = [
        c["name"] for s in sources for c in s["containers"] if c["name"] in wanted
    ]
    pages = [
        s["page"]
        for s in sources
        if s["page"] in asked or any(c["name"] in wanted for c in s["containers"])
    ]
    if ui_logs.listed(query, "app_service"):
        pages = [s["page"] for s in sources]
    return pages or [s["page"] for s in sources], ticked, picked


def _option(
    value: str, label: str, checked: bool, name: str | None = "container"
) -> dict[str, Any]:
    """One ``checklist`` option; a container's names its own field."""
    return {"value": value, "label": label, "checked": checked, "name": name}


def _links(sources: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Each page's title and Overseer URL, for a line's service cell."""
    return {
        s["page"]: {
            "title": s["title"],
            "url": runtime_page_url(s["page"]),
        }
        for s in sources
    } | {
        item.name: {"title": item.title, "url": item.url}
        for item in current_navigation().get("services", [])
    }


async def _context(
    pages: Sequence[str],
    found: ui_logs.Containers,
    query: Mapping[str, str],
    events: str,
    **more: Any,
) -> dict[str, Any]:
    """The window's lines and the filters that chose them, and the stream
    that follows them (with the same level, order and ``more``). The search
    (``q``) is the page's own (``filter_input``): every line comes, and the
    text only fills the box."""
    levels = ui_logs.levels_of(query)
    order = ui_logs.order_of(query)
    # A picked range narrows the stream too: a line after it is not added.
    span = {key: query.get(key) for key in ("from", "to")}
    return {
        "logs": await ui_logs.recent(
            pages, _unsearched(query), volume=True, found=found
        ),
        "logs_tones": ui_logs.TONES,
        "logs_volume_tones": ui_logs.VOLUME_TONES,
        "logs_events": with_query(events, level=levels, order=order, **span, **more),
        "logs_windows": ui_logs.WINDOWS,
        "logs_window": series.window_of(
            query.get("window"), ui_logs.WINDOWS, ui_logs.DEFAULT_WINDOW
        ),
        "logs_levels": [
            {"value": value, "label": label, "checked": value in levels}
            for value, label in ui_logs.LEVEL_CHOICES
        ],
        "logs_q": query.get("q", ""),
        "logs_orders": ORDERS,
        "logs_order": order,
    }


def _unsearched(query: Mapping[str, str]) -> QueryParams:
    """``query`` without its search, which the page applies itself."""
    items = getattr(query, "multi_items", None)
    pairs = items() if items else list(query.items())
    return QueryParams([(key, value) for key, value in pairs if key != "q"])


def render(
    rows: list[dict[str, Any]], links: dict[str, dict[str, str]] | None = None
) -> str:
    return fragment(ROWS, rows=rows, tones=ui_logs.TONES, links=links)


def events(page: str, query: Mapping[str, str]) -> AsyncIterator[str]:
    """One page's new lines as rows to add, over SSE, while it is open."""
    return _stream([page], query)


async def everything_events(query: Mapping[str, str]) -> AsyncIterator[str]:
    """Overseer > Logs' new lines, each with its service, over SSE."""
    found = await ui_logs.containers()
    sources = ui_logs.sources(found)
    pages, _ticked, _picked = _reading(query, sources)
    async for sent in _stream(pages, query, _links(sources), found):
        yield sent


def _stream(
    pages: Sequence[str],
    query: Mapping[str, str],
    links: dict[str, dict[str, str]] | None = None,
    found: ui_logs.Containers | None = None,
) -> AsyncIterator[str]:
    async def lines() -> AsyncIterator[str]:
        async for batch in ui_logs.follow(pages, query, found=found):
            yield frame(EVENT, render(batch, links))

    return heartbeat(lines())
