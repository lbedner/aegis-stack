"""Logs in Overseer: the Logs section every page with a container behind it
gets after Container (``overseer_sections`` adds both), and Overseer > Logs,
every such page's lines in one view with a link to each line's page. Both
read the window's lines (``ui_logs``) once, newest first, then follow new
lines over SSE while open: Docker pushes them, so nothing polls. Only the
window reads the containers again; levels, services, containers, order, a
range and the search filter on the page (app.js ``data-facets``), so every
line comes, carrying what each filter matches."""

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

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
from .rendering import fragment

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
    picked = set(ui_logs.listed(query, "container"))
    shown = await _context([page], found, query, EVENTS.format(page=page))
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
    every = await _context(_pages(sources), found, req.query, EVERY_EVENTS)
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


def _pages(sources: list[dict[str, Any]]) -> list[str]:
    """Every page with a container: Overseer > Logs reads them all, and the
    Services picker narrows on the page."""
    return [s["page"] for s in sources]


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
) -> dict[str, Any]:
    """Every line in the window, in the order asked for, the filters' state
    for the page to apply, and the stream that follows every new line."""
    levels = ui_logs.levels_of(query)
    order = ui_logs.order_of(query)
    window = series.window_of(
        query.get("window"), ui_logs.WINDOWS, ui_logs.DEFAULT_WINDOW
    )
    read = {"window": str(window), "order": order}
    return {
        "logs": await ui_logs.recent(pages, read, volume=True, found=found),
        "logs_tones": ui_logs.TONES,
        "logs_volume_tones": ui_logs.VOLUME_TONES,
        "logs_range": _range(query),
        "logs_events": events,
        "logs_windows": ui_logs.WINDOWS,
        "logs_window": window,
        "logs_levels": [
            {"value": value, "label": label, "checked": value in levels}
            for value, label in ui_logs.LEVEL_CHOICES
        ],
        "logs_q": query.get("q", ""),
        "logs_orders": ORDERS,
        "logs_order": order,
    }


def _range(query: Mapping[str, str]) -> tuple[int, int] | None:
    """The range a query picks (``from`` and ``to``, in ms), for the strip
    to mark; the page narrows the lines to it."""
    lo, hi = ui_logs.number_of(query, "from"), ui_logs.number_of(query, "to")
    return (lo, hi) if lo is not None and hi is not None else None


def render(
    rows: list[dict[str, Any]], links: dict[str, dict[str, str]] | None = None
) -> str:
    return fragment(ROWS, rows=rows, tones=ui_logs.TONES, links=links)


def events(page: str) -> AsyncIterator[str]:
    """One page's new lines as rows to add, over SSE, while it is open:
    every one, which the page filters."""
    return _stream([page])


async def everything_events() -> AsyncIterator[str]:
    """Overseer > Logs' new lines, each with its service, over SSE: every
    one, which the page filters."""
    found = await ui_logs.containers()
    sources = ui_logs.sources(found)
    async for sent in _stream(_pages(sources), _links(sources), found):
        yield sent


def _stream(
    pages: Sequence[str],
    links: dict[str, dict[str, str]] | None = None,
    found: ui_logs.Containers | None = None,
) -> AsyncIterator[str]:
    async def lines() -> AsyncIterator[str]:
        async for batch in ui_logs.follow(pages, {}, found=found):
            yield frame(EVENT, render(batch, links))

    return heartbeat(lines())
