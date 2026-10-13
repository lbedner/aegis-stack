"""The Container section: every Overseer page with a container behind it
gets one (``overseer_sections`` adds it), a card per instance
(``ui_runtime.containers``) and charts over the chosen window. It renders
from the containers sampler's last reading, so it opens full, then an SSE
stream re-sends the cards and each chart every tick while it is open.

Also the glance above a page's Overview (a line per container, with its own
stream), and Overseer's home: every sidebar entry as cards or a map, kept
live by one stream for the whole stack."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from app.core import ownership, series
from app.core.constants import ComponentName
from app.core.ontology import EdgeKind, SystemModel, current
from app.core.ontology.model import parse_node_id
from app.core.ownership import HOST
from app.services.system import (
    topology,
    ui_resources,
    ui_runtime,
    ui_worker,
)
from app.services.system.models import ComponentStatusType
from app.services.system.ui import (
    get_component_label,
    get_component_title,
    is_service,
    registry_entry,
    registry_key,
)

from . import overseer_conformance, overseer_heat, overseer_map, overseer_zoom
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
HOME = "/overseer"
CARDS_VIEW, MAP_VIEW, FLOW_VIEW = "cards", "map", "flow"
VIEWS = (
    (CARDS_VIEW, "Cards", "squares-2x2"),
    (MAP_VIEW, "Map", "tiers"),
    (FLOW_VIEW, "Flow", "flow"),
)
TEMPLATES = {key: f"pages/overseer/_overview_{key}.html" for key, *_ in VIEWS}
# The window every card's lines cover, named once above them.
WINDOW = series.DEFAULT_WINDOW
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


class MapState(TypedDict):
    view: str
    zoom: str | None
    overlay: str | None
    lit: str | None  # the map keys a route's dry path crosses, kept lit


def map_state(query: Mapping[str, str]) -> MapState:
    """The home page's view, and on the Map its zoom (into the Server, or
    a service in it by its map key) and its overlay, each kept only where
    it means something: what every link and the stream carry."""
    view = query.get("view")
    view = view if view in TEMPLATES else VIEWS[0][0]
    zoom = query.get("zoom") if view == MAP_VIEW else None
    if zoom != HOST and not (zoom and _opens(zoom)):
        zoom = None
    overlay = query.get("overlay")
    return {
        "view": view,
        "zoom": zoom,
        "overlay": overlay if overlay in _overlays(view, zoom) else None,
        "lit": query.get("lit") if view == MAP_VIEW else None,
    }


def _opens(key: str) -> bool:
    """Whether ``key`` is a service the stack has: a level of its own (a
    sub-service, or one since removed, has none)."""
    return is_service(key) and ownership.installed(
        ownership.SERVICE, registry_entry(key)[1]
    )


def zoom_url(key: str, lit: str | None = None) -> str:
    """The Map opened up into ``key``: the Server, or a service in it;
    ``lit``, the map keys to keep lit there (``MapState``)."""
    return with_query(HOME, view=MAP_VIEW, zoom=key, lit=lit)


def _overlays(view: str, zoom: str | None) -> dict[str, tuple[str, str]]:
    """The overlays a view offers, by key: its label and what it shows.
    Traffic is counted by part, so a service opened up offers none."""
    if view != MAP_VIEW or zoom not in (None, HOST):
        return {}
    return {overseer_heat.TRAFFIC: ("Traffic", overseer_heat.SAYS)}


async def overview(
    navigation: dict[str, list[NavItem]],
    query: Mapping[str, str] | None = None,
    *,
    wait: bool = False,
) -> dict[str, Any]:
    """Every sidebar entry, in its order: as cards (a page with containers
    behind it with their glance and trend, anything else with its health
    check's line and a few figures; the default, and where an old link to
    the list it once had lands), or as a map, placed, or, zoomed into the
    Server, what runs inside it as its own map (``overseer_zoom``), toned
    by an overlay when one is asked for (``map_state``). One read of the
    containers and one of their trends, whatever the stack's size. A
    failing entry names the failing ones it depends on (``cause``)."""
    state = map_state(query or {})
    view = state["view"]
    entries = [
        (entry, ui_runtime.page_of(entry.name) if group == "components" else None)
        for group in ("components", "services")
        for entry in navigation[group]
    ]
    host = ui_runtime.page_of(HOST)
    pages = [page for _, page in entries if page]
    drawn = view in (MAP_VIEW, FLOW_VIEW)
    # Opened up or the Flow, a map shows no glance: no containers read.
    bare = state["zoom"] is not None or view == FLOW_VIEW
    found = (
        {}
        if bare
        else await ui_runtime.containers_of(
            [*pages, host] if host else pages, wait=wait
        )
    )
    trends = await ui_runtime.trends(pages, WINDOW) if view == CARDS_VIEW else {}
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
        if view == CARDS_VIEW:
            trend = trends[page] if page and rows else None
            item |= _card(trend, item["glance"], entry.details)
        stack.append(item)
    if drawn:
        placed = await _drawn(stack, [e for e, _ in entries], state)
    else:
        model = await asyncio.to_thread(current)
        _name_causes(stack, _cause_links(model, stack))
        placed = {"overview_stack": stack}
    server = found[host]["rows"] if host in found else []
    return placed | {
        # What has no container of its own runs in the webserver.
        "overview_host": server[0]["name"] if server else None,
        "overview_events": with_query(OVERVIEW_EVENTS, **state),
        "overview_lit": state["lit"],
        "overview_wide": drawn,
        "overview_cards": view == CARDS_VIEW,
        "overview_event": OVERVIEW_EVENT,
        "overview_view": view,
        "overview_views": VIEWS,
        "overview_window": series.phrase(WINDOW),
        "overview_template": TEMPLATES[view],
    }


async def _drawn(
    stack: list[dict[str, Any]], entries: list[NavItem], state: MapState
) -> dict[str, Any]:
    """The Map's or the Flow's entries placed (``overseer_map.layout``):
    with the worker's queue; opened up into the Server when zoomed (its
    own links, outside providers, unset keys) and toned by its overlay;
    each entry's role and cause; the Map's costs to load, the Flow's way
    of work and its key."""
    zoom, overlay = state["zoom"], state["overlay"]
    zoomed = zoom is not None
    service = zoom if zoom != HOST else None  # a service opened up, by its key
    worker = next((e for e in entries if e.name == ComponentName.WORKER), None)
    if worker:
        stack.append(_queue(worker))
    _inherit(stack)
    model = await asyncio.to_thread(current)
    shape, pieces, links, tones = None, [], [], {}
    if zoom == HOST:
        stack, shape = overseer_zoom.opened(stack, model)
        await overseer_zoom.name_unkeyed(stack)
        keys = await asyncio.to_thread(overseer_zoom.openable, stack, model)
        for item in stack:
            if item["key"] in keys:
                item["zoom"] = zoom_url(item["key"])
    # The parts report, read once opened up: what each part should fix.
    found = (
        await asyncio.to_thread(overseer_conformance.conformance)
        if zoomed
        else overseer_conformance.Conformance({}, {})
    )
    if service:
        subject = overseer_zoom.subject_of(service)
        pieces, lines = await asyncio.to_thread(overseer_zoom.pieces_of, subject, model)
        stack, links, tones = await asyncio.to_thread(
            overseer_zoom.service_opened, stack, model, pieces, lines
        )
        stack += overseer_zoom.missing(found.lacks.get(service, []))
    # A key line says why an outside provider cannot be used; no failure
    # follows it, so causes are named before it is drawn.
    drawn = links if service else shape.links if shape else None
    _name_causes(stack, drawn if drawn is not None else _cause_links(model, stack))
    if service:
        overseer_conformance.mark_pieces(stack, found, service, pieces)
    elif zoomed:
        overseer_conformance.mark(stack, found)
    if overlay:
        await overseer_heat.heat(stack)
    if zoom == HOST and shape is not None:
        shape = overseer_zoom.with_key_lines(stack, shape)
    flow = state["view"] == FLOW_VIEW
    if flow:
        shape = topology.flow([item["key"] for item in stack])
    else:
        await _name_loads(stack)
    for item in stack:
        item.setdefault("role", topology.ROLES.get(item["key"]))
        if item["key"] == HOST and not (zoomed or flow):
            item["zoom"] = zoom_url(HOST)
    placed = (
        overseer_map.lanes(stack, links, tones)
        if service
        else overseer_map.layout(
            stack, shape, compact=zoomed, across=flow, opened=zoomed
        )
    )
    return placed | {
        "overview_stack": stack,
        "map_line_key": overseer_zoom.LINE_KEY,
        # The way back up, a level at a time.
        "map_trail": _trail(zoom),
        "map_back": with_query(HOME, view=MAP_VIEW),
        # Each overlay the view offers, as a chip that switches it on or off.
        "map_overlays": [
            {
                "key": key,
                "label": label,
                "says": says,
                "on": key == overlay,
                "url": with_query(
                    HOME, **state | {"overlay": None if key == overlay else key}
                ),
            }
            for key, (label, says) in _overlays(state["view"], zoom).items()
        ],
        "map_legend": _legend(placed) if flow else [],
    }


def _trail(zoom: str | None) -> list[dict[str, Any]]:
    """The levels under the stack's own, the last the one shown: the
    Server, and a service opened up in it."""
    if zoom is None:
        return []
    server = {"title": get_component_title(HOST), "url": None}
    if zoom == HOST:
        return [server]
    opened = {"title": get_component_title(zoom), "url": None}
    return [server | {"url": zoom_url(HOST)}, opened]


def _queue(worker: NavItem) -> dict[str, Any]:
    """The worker's queue (``topology.QUEUE``) as a node, from the worker's
    own health check (``ui_worker.backlog``)."""
    found = ui_worker.backlog(worker.component)
    holder = topology.INSIDE[topology.QUEUE]
    return {
        "key": topology.QUEUE,
        "registry": topology.QUEUE,
        "title": get_component_title(topology.QUEUE),
        "url": worker.url,
        "status": found.status.value,
        "tone": health_tone(found.status.value),
        "message": found.message,
        "figure": f"{found.queued} queued",
        "note": f"In {get_component_label(holder)}, beside the "
        f"{get_component_title(holder)}",
        "glance": None,
    }


def _inherit(stack: list[dict[str, Any]]) -> None:
    """A part inside another (``topology.INSIDE``) is down when what holds
    it is."""
    found = {item["key"]: item for item in stack}
    down = ComponentStatusType.UNHEALTHY.value
    for part, holder in topology.INSIDE.items():
        if part in found and found.get(holder, {}).get("status") == down:
            found[part] |= {"status": down, "tone": health_tone(down)}


def _legend(placed: dict[str, Any]) -> list[tuple[str, str]]:
    """Each shape the map draws, and what it stands for."""
    drawn = {node["role"] for node in placed["map_nodes"]}
    return [
        (role, label) for role, label in topology.ROLE_LABELS.items() if role in drawn
    ]


async def _name_loads(stack: list[dict[str, Any]]) -> None:
    """Each entry's cost to load (``ui_resources.load_costs``), as its
    ``load``, for the map's chips in the Server's node; none while it is
    measured, or for what is not measured."""
    found = await ui_resources.load_costs()
    loads = {row["key"]: row["value"] for row in found["rows"]} if found else {}
    for item in stack:
        item["load"] = loads.get(item["registry"])


def _cause_links(
    model: SystemModel, stack: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """What a failing entry can fail because of: what it depends on and
    what its code calls (the model's edges), by the entries' own names."""
    names = {item["key"] for item in stack}
    pairs = (
        (parse_node_id(edge.source)[1], parse_node_id(edge.target)[1])
        for edge in model.edges
        if edge.kind in (EdgeKind.DEPENDS_ON, EdgeKind.CALLS)
    )
    return [(a, b) for a, b in pairs if {a, b} <= names]


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
    query: Mapping[str, str] | None = None, max_frames: int | None = None
):
    """The home page's stack over SSE, as its query asks (``map_state``),
    sent again only when it changes."""

    async def frame() -> dict[str, str]:
        found = await overview(current_navigation(), query, wait=True)
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
