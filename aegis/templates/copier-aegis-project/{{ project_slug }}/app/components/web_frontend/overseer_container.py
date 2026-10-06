"""The Container section: every Overseer page with a container behind it
gets one (``overseer_sections`` adds it), a card per instance
(``ui_runtime.containers``) and charts over the chosen window. It renders
from the containers sampler's last reading, so it opens full, then an SSE
stream re-sends the cards and each chart every tick while it is open.

Also the glance above a page's Overview (a line per container, with its own
stream), and Overseer's home: every sidebar entry as cards or a map, kept
live by one stream for the whole stack."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from app.core import secrets, series
from app.services.system import service_links, topology, ui_resources, ui_runtime
from app.services.system.ui import registry_key

from . import overseer_map, overseer_secrets
from .filters import health_tone, worst_tone
from .overseer_live import chart_frames, chart_panel, fragments_events
from .overseer_nav import NavItem, current_navigation, runtime_page_url
from .rendering import fragment, with_query

SECTION = {"container": "Container"}
EVENTS = "/overseer/events/container/{page}"
EVENT = "container"
CARDS = "pages/overseer/_container_cards.html"
# The glance above a page's Overview (``SectionedPage.glance``).
GLANCE = "pages/overseer/_glance_rows.html"
GLANCE_EVENTS = "/overseer/events/glance/{page}"
GLANCE_EVENT = "glance"
# Overseer's home, in the view its toggle chose (``?view=``, like every filter).
VIEWS = (
    ("cards", "Cards", "squares-2x2"),
    ("map", "Map", "tiers"),
)
TEMPLATES = {key: f"pages/overseer/_overview_{key}.html" for key, *_ in VIEWS}
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
        "container": toned(table),
        "container_charts": chart_panel(
            EVENT, charts, seconds, EVENTS.format(page=page)
        ),
    }


def render(view: dict[str, Any]) -> str:
    return fragment(CARDS, container=toned(view))


def toned(view: dict[str, Any]) -> dict[str, Any]:
    """Each row with its state's and its figures' tones, and the confirm its
    Restart opens."""
    rows = [
        r
        | {
            "tone": health_tone(r["state_status"]),
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
        "glance": toned(table),
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
    navigation: dict[str, list[NavItem]],
    view: str | None = None,
    zoom: str | None = None,
    *,
    wait: bool = False,
) -> dict[str, Any]:
    """Every sidebar entry, in its order: as cards (a page with containers
    behind it with their glance and trend, anything else with its health
    check's line and a few figures; the default, and where an old link to
    the list it once had lands), or as a map, placed, or, zoomed
    into the Server (``zoom``), what runs inside it as its own map
    (``_opened``). One read of the containers and one of their trends,
    whatever the stack's size. A failing entry names the failing ones it
    depends on (``cause``)."""
    view = view if view in TEMPLATES else VIEWS[0][0]
    entries = [
        (entry, ui_runtime.page_of(entry.name) if group == "components" else None)
        for group in ("components", "services")
        for entry in navigation[group]
    ]
    host = ui_runtime.page_of(topology.HOST)
    pages = [page for _, page in entries if page]
    zoomed = view == "map" and zoom == topology.HOST
    # The Server opened up shows no glance: no containers read for it.
    found = (
        {}
        if zoomed
        else await ui_runtime.containers_of([*pages, host] if host else pages, wait=wait)
    )
    trends = await ui_runtime.trends(pages) if view == "cards" else {}
    stack = []
    for entry, page in entries:
        rows = found[page]["rows"] if page in found else []
        item = {
            "key": entry.name,
            "registry": registry_key(entry.group, entry.name),
            "title": entry.title,
            "url": entry.url,
            "status": entry.status,
            "tone": health_tone(entry.status or ""),
            "message": entry.component.message,
            "glance": toned(found[page]) if page and rows else None,
        }
        if view == "cards":
            trend = trends[page] if page and rows else None
            item |= _card(trend, item["glance"], entry.details)
        stack.append(item)
    shape, map_zoom = None, None
    if zoomed:
        map_zoom = next(
            (item["title"] for item in stack if item["key"] == topology.HOST), "Server"
        )
        stack, shape = _opened(stack)
        await _name_unkeyed(stack)
        shape = _with_key_lines(stack, shape)
    _name_causes(stack, shape.links if shape else topology.LINKS)
    if view == "map":
        await _name_loads(stack)
    if view == "map" and not zoomed:
        for item in stack:
            if item["key"] == topology.HOST:
                item["zoom"] = with_query("/overseer", view="map", zoom=topology.HOST)
    server = found[host]["rows"] if host in found else []
    placed = overseer_map.layout(stack, shape, compact=zoomed) if view == "map" else {}
    return placed | {
        "overview_stack": stack,
        # What has no container of its own runs in the webserver.
        "overview_host": server[0]["name"] if server else None,
        "overview_events": with_query(
            OVERVIEW_EVENTS, view=view, zoom=topology.HOST if zoomed else None
        ),
        # The way back out of the Server opened up.
        "map_zoom": map_zoom,
        "map_back": with_query("/overseer", view="map"),
        "overview_event": OVERVIEW_EVENT,
        "overview_view": view,
        "overview_views": VIEWS,
        "overview_template": TEMPLATES[view],
    }


async def _name_loads(stack: list[dict[str, Any]]) -> None:
    """Each entry's cost to load (``ui_resources.load_costs``), as its
    ``load``, for the map's chips in the Server's node; none while it is
    measured, or for what is not measured."""
    found = await ui_resources.load_costs()
    loads = {row["key"]: row["value"] for row in found["rows"]} if found else {}
    for item in stack:
        item["load"] = loads.get(item["registry"])


def _opened(
    stack: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], topology.Shape]:
    """The Server opened up (``topology.zoomed``): what runs inside it, by
    its registry key (a service and a component may share a name), and what
    each reaches (``service_links``): an installed component as itself, an
    outside provider as a plain node."""
    hosted = set(topology.shape([item["key"] for item in stack]).hosted)
    inside = [
        item | {"key": item["registry"]} for item in stack if item["key"] in hosted
    ]
    components = {item["registry"]: item for item in stack if item["key"] not in hosted}
    keys = {item["key"] for item in inside}
    reach = service_links.links()
    links = {
        key: [
            t
            for t in reach.get(key, [])
            if t in components or t in keys or t.startswith(service_links.OUTSIDE)
        ]
        for key in keys
    }
    shape = topology.zoomed([item["key"] for item in inside], links)
    reached = [key for tier in shape.tiers for key in tier if key not in keys]
    return inside + [components.get(key) or _outside(key) for key in reached], shape


async def _name_unkeyed(stack: list[dict[str, Any]]) -> None:
    """An outside provider a service needs a key for that is not set: the
    connection cannot be used, so the node (and the line into it) warns,
    and offers each key's set dialog (``fix``), one click away."""
    wanted = service_links.provider_keys()
    if not any(item["key"] in wanted for item in stack):
        return
    # Whether each is set, not its value: nothing decrypted every frame.
    keyed = {row.name for row in await secrets.status() if row.is_set}
    for item in stack:
        unset = [n for n in wanted.get(item["key"], []) if n not in keyed]
        if item.get("outside") and unset:
            item |= {
                "tone": "warn",
                "message": "Not usable: a key it needs is not set.",
                "fix": [{"name": n, "url": overseer_secrets.set_url(n)} for n in unset],
            }


def _with_key_lines(
    stack: list[dict[str, Any]], shape: topology.Shape
) -> topology.Shape:
    """A line from where the keys live (``topology.KEYS``) to each outside
    provider whose key is not set (``_name_unkeyed``): the core of why it
    cannot be used, drawn."""
    keys = {item["key"] for item in stack}
    unkeyed = [item["key"] for item in stack if item.get("fix")]
    if topology.KEYS not in keys or not unkeyed:
        return shape
    lines = [(topology.KEYS, key) for key in unkeyed]
    return replace(shape, links=[*shape.links, *lines])


def _outside(key: str) -> dict[str, Any]:
    """An outside provider's node: no page, no health check of ours."""
    return {
        "key": key,
        "registry": key,
        "title": service_links.title(key),
        "url": None,
        "status": None,
        "tone": "muted",
        "message": "Outside the stack",
        "glance": None,
        "outside": True,
    }


def _name_causes(stack: list[dict[str, Any]], links: Sequence[tuple[str, str]]) -> None:
    """Each failing entry's failing dependencies along ``links``, at the
    root (``topology.causes``), by title, as its ``cause``."""
    titles = {item["key"]: item["title"] for item in stack}
    found = topology.causes({i["key"] for i in stack if i["tone"] == "error"}, links)
    for item in stack:
        item["cause"] = ", ".join(titles[key] for key in found.get(item["key"], []))


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


def overview_events(  # noqa: ANN201 - async iterator
    view: str | None = None, zoom: str | None = None, max_frames: int | None = None
):
    """The home page's stack over SSE, in its view (and zoom), sent again
    only when it changes."""

    async def frame() -> dict[str, str]:
        found = await overview(current_navigation(), view, zoom, wait=True)
        return {OVERVIEW_EVENT: fragment(found["overview_template"], **found)}

    return fragments_events(frame, series.TICK_SECONDS, max_frames)


def events(  # noqa: ANN201 - async iterator
    page: str, window: int = series.DEFAULT_WINDOW, max_frames: int | None = None
):
    """The cards and each chart over SSE, each sent again only when it
    changes (``overseer_live.chart_frames``)."""
    held: dict[str, tuple[list[str], int]] = {}

    async def frame() -> dict[str, str]:
        table, charts = await ui_runtime.section(page, window)
        return {EVENT: render(table)} | chart_frames(EVENT, charts, held)

    return fragments_events(frame, series.TICK_SECONDS, max_frames)
