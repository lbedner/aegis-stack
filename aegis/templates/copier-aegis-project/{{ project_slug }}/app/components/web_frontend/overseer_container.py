"""The Container section: every Overseer page with a container behind it
gets one (``overseer_sections`` adds it), a card per instance
(``ui_runtime.containers``) and charts over the chosen window. It renders
from the containers sampler's last reading, so it opens full, then an SSE
stream re-sends the cards and each chart every tick while it is open.

Also the glance above a page's Overview (a line per container, with its own
stream), and Overseer's home: every sidebar entry as a list, cards or a map,
kept live by one stream for the whole stack."""

from collections.abc import Mapping
from typing import Any

from app.core import series
from app.services.system import topology, ui_runtime

from . import overseer_map
from .filters import health_tone, worst_tone
from .overseer_live import fragments_events
from .overseer_nav import NavItem, current_navigation, runtime_page_url
from .rendering import fragment, templates, with_query

SECTION = {"container": "Container"}
EVENTS = "/overseer/events/container/{page}"
EVENT = "container"
CARDS = "pages/overseer/_container_cards.html"
MACROS = "components/macros/layout.html"
# The glance above a page's Overview (``SectionedPage.glance``).
GLANCE = "pages/overseer/_glance_rows.html"
GLANCE_EVENTS = "/overseer/events/glance/{page}"
GLANCE_EVENT = "glance"
# Overseer's home, in the view its toggle chose (``?view=``, like every filter).
VIEWS = (("list", "List"), ("cards", "Cards"), ("map", "Map"))
TEMPLATES = {key: f"pages/overseer/_overview_{key}.html" for key, _ in VIEWS}
OVERVIEW_EVENTS = "/overseer/events/overview"
OVERVIEW_EVENT = "overview"
# A card's figures for what has no container: a few of its health check's
# own (``facts``), never anything that names a place or a credential.
FACTS = 3
_UNSHOWN = {
    "url",
    "uri",
    "key",
    "token",
    "secret",
    "password",
    "path",
    "host",
    "error",
    "id",
    "dsn",
}
# A row's Restart: the confirm (routes/partials/overseer_runtime.py), whose
# button calls the restart API (``ui_runtime.RESTART_API``).
RESTART = "/partials/overseer/runtime/restart/{name}"


async def context(page: str, query: Mapping[str, str]) -> dict[str, Any]:
    """The section's cards and its charts over the chosen ``window`` as last
    sampled, so it opens full and never waits on the runtime (``PENDING``
    before the first sample), the range chips, and where it all refreshes
    from."""
    seconds = series.window_of(query.get("window"))
    table, charts = await ui_runtime.section(page, seconds, wait=False)
    return {
        "container": _rows(table),
        "container_charts": [
            chart | {"id": chart_event(chart["key"])} for chart in charts
        ],
        "container_events": with_query(EVENTS.format(page=page), window=str(seconds)),
        "container_windows": series.WINDOWS,
        "container_window": seconds,
    }


def render(view: dict[str, Any]) -> str:
    return fragment(CARDS, container=_rows(view))


def _rows(view: dict[str, Any]) -> dict[str, Any]:
    """Each row with its state's and its memory's tone, and the confirm its
    Restart opens."""
    rows = [
        r
        | {
            "tone": _tone(r),
            "cpu_tone": _figure_tone(r["cpu_status"]),
            "memory_tone": _figure_tone(r["memory_status"]),
            "restart_url": RESTART.format(name=r["name"]),
        }
        for r in view["rows"]
    ]
    return view | {"rows": rows}


def _figure_tone(status: str | None) -> str:
    """A live figure's tone from its status (``ui_runtime``); unread is fine."""
    return health_tone(status) if status else "ok"


async def glance(page: str, *, wait: bool = False) -> dict[str, Any]:
    """The Overview's glance at ``page``'s containers (the page opens on
    the sampler's last reading, so it never waits on the runtime), and its
    stream."""
    table = await ui_runtime.containers(page, wait=wait)
    return {
        "glance": _rows(table),
        "glance_base": runtime_page_url(page),
        "glance_events": GLANCE_EVENTS.format(page=page),
        "glance_event": GLANCE_EVENT,
    }


def glance_events(page: str, max_frames: int | None = None):  # noqa: ANN201 - async iterator
    """The glance over SSE, sent again only when it changes."""

    async def frame() -> dict[str, str]:
        return {GLANCE_EVENT: fragment(GLANCE, **await glance(page, wait=True))}

    return fragments_events(frame, series.TICK_SECONDS, max_frames)


async def overview(
    navigation: dict[str, list[NavItem]], view: str | None = None, *, wait: bool = False
) -> dict[str, Any]:
    """Every sidebar entry, in its order: a page with containers behind it
    as their glance, anything else as its health check's line; as cards,
    with their trend or a few figures too; as a map, placed. One read of
    the containers and one of their trends, whatever the stack's size."""
    view = view if view in TEMPLATES else VIEWS[0][0]
    entries = [
        (entry, ui_runtime.page_of(entry.name) if group == "components" else None)
        for group in ("components", "services")
        for entry in navigation[group]
    ]
    host = ui_runtime.page_of(topology.HOST)
    pages = [page for _, page in entries if page]
    found = await ui_runtime.containers_of([*pages, host] if host else pages, wait=wait)
    trends = await ui_runtime.trends(pages) if view == "cards" else {}
    stack = []
    for entry, page in entries:
        rows = found[page]["rows"] if page else []
        item = {
            "key": entry.name,
            "title": entry.title,
            "url": entry.url,
            "status": entry.status,
            "tone": health_tone(entry.status or ""),
            "message": entry.component.message,
            "glance": _rows(found[page]) if page and rows else None,
        }
        if view == "cards":
            trend = trends[page] if page and rows else None
            item |= _card(trend, item["glance"], entry.details)
        stack.append(item)
    server = found[host]["rows"] if host else []
    return (overseer_map.layout(stack) if view == "map" else {}) | {
        "overview_stack": stack,
        # What has no container of its own runs in the webserver.
        "overview_host": server[0]["name"] if server else None,
        "overview_events": with_query(OVERVIEW_EVENTS, view=view),
        "overview_event": OVERVIEW_EVENT,
        "overview_view": view,
        "overview_views": VIEWS,
        "overview_template": TEMPLATES[view],
    }


def _card(
    trend: dict[str, list[float]] | None,
    glance: dict[str, Any] | None,
    details: list[tuple[str, str]],
) -> dict[str, Any]:
    """What a card adds: a page's CPU and memory lines, each in the worst
    of its containers' tones, or, with no container, a few of its health
    check's figures."""
    if trend and glance:
        return {
            "spark": {
                key: {
                    "points": series.sparkline(values),
                    "tone": worst_tone(row[f"{key}_tone"] for row in glance["rows"]),
                }
                for key, values in trend.items()
            }
        }
    return {"facts": facts(details)}


def facts(details: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The first few of a health check's figures (``NavItem.details``, what
    its generic page shows), leaving out anything that names a place or a
    credential (a URL, a key, a path) or runs long."""
    return [
        (label, value)
        for label, value in details
        if not _UNSHOWN & set(label.lower().split()) and len(value) <= 40
    ][:FACTS]


def overview_events(view: str | None = None, max_frames: int | None = None):  # noqa: ANN201 - async iterator
    """The home page's stack over SSE, in its view, sent again only when it
    changes."""

    async def frame() -> dict[str, str]:
        found = await overview(current_navigation(), view, wait=True)
        return {OVERVIEW_EVENT: fragment(found["overview_template"], **found)}

    return fragments_events(frame, series.TICK_SECONDS, max_frames)


def _tone(row: dict[str, Any]) -> str:
    """Running and not unhealthy is fine; stopped or unhealthy is not; the
    rest (starting, restarting) is on its way."""
    if row["health"] == "unhealthy" or row["phase"] in ("exited", "dead"):
        return "error"
    return "ok" if row["phase"] == "running" else "warn"


def chart_event(key: str) -> str:
    """The SSE event (and chart id) for one of the section's charts."""
    return f"{EVENT}-{key}"


def events(  # noqa: ANN201 - async iterator
    page: str, window: int = series.DEFAULT_WINDOW, max_frames: int | None = None
):
    """The cards and each chart over SSE, each sent again only when it
    changes: a chart whole at first and when its lines change, and after
    that only its new points (``series.since``)."""
    chart_data = templates.env.get_template(MACROS).module.chart_data  # type: ignore[attr-defined]
    # Each chart's lines and the newest time sent, which the page now has.
    held: dict[str, tuple[list[str], int]] = {}

    async def frame() -> dict[str, str]:
        table, charts = await ui_runtime.section(page, window)
        sent = {EVENT: render(table)}
        for chart in charts:
            event, data = chart_event(chart["key"]), chart["data"]
            lines = [line["label"] for line in data["series"]]
            if event in held and held[event][0] == lines:
                data = series.since(data, held[event][1])
            if data["labels"]:
                held[event] = (lines, data["labels"][-1])
            sent[event] = str(chart_data(event, data))
        return sent

    return fragments_events(frame, series.TICK_SECONDS, max_frames)
