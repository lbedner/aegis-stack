"""Overseer > Resources, what ``ui_resources`` reads, its figures charted
over the chosen window. It opens on the samplers' last readings, then an
SSE stream re-sends the snapshot and each chart's new points every tick
while it is open."""

import asyncio
from typing import Any

from markupsafe import Markup

from app.core import series
from app.core.parts import Category
from app.services.system import container_health, ui_resources
from app.services.system.models import ComponentStatus

from .filters import health_tone
from .overseer_live import Drawn, chart_panel, live_events
from .overseer_nav import NavItem, SectionRequest, runtime_page_url
from .rendering import chart, fragment

SECTIONS = ((None, {"overview": "Overview"}),)
ITEM = NavItem(
    group="resources",
    name="resources",
    title="Resources",
    url="/overseer/resources",
    status="",
    component=ComponentStatus(name="resources", message=""),
    concern=Category.STACK,
)
EVENTS = "/overseer/events/resources"
EVENT = "resources"
BODY = "pages/overseer/resources/_body.html"
# Each resource's split in its chart's header, sent apart from the rest
# of the snapshot, an event a resource (``-cpu``).
SPLIT_EVENT = "resources-split"
SPLIT = "pages/overseer/resources/_split.html"


def _split_event(split: dict[str, Any]) -> str:
    return f"{SPLIT_EVENT}-{split['key']}"


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    window = series.window_of(req.query.get("window"), ui_resources.WINDOWS)
    charts, view, load = await asyncio.gather(
        ui_resources.charts(window), _view(wait=False), ui_resources.load_costs()
    )
    panel = chart_panel(EVENT, charts, window, EVENTS, ui_resources.WINDOWS)
    splits = {split["key"]: split for split in view["resources"]["split"]}
    for drawn in panel["charts"]:
        if split := splits.get(drawn["key"]):
            event = _split_event(split)
            drawn["subtitle"] = Markup(fragment(SPLIT, split=split, event=event))
    return {
        "section_subtitle": "What this stack uses of the host, and what the rest of it does.",
        "resources_event": EVENT,
        "resources_charts": panel,
        "resources_load": _load(load),
    } | view


def _load(load: dict[str, Any] | None) -> dict[str, Any]:
    """What each service costs the server to load, a bar a service laid
    flat so the names read; no bars, and no core, while it is measured."""
    rows = load["rows"] if load else []
    data = chart([r["label"] for r in rows], "To load", [r["bytes"] for r in rows])
    return {
        "core": load["core"] if load else None,
        "chart": data | {"format": "bytes", "horizontal": True, "points": len(rows)},
    }


async def _view(*, wait: bool) -> dict[str, Any]:
    """The overview, and the containers not well (stopped, starting, or
    raising their part by ``container_health``'s rule), each with its
    state's tone, what is wrong and the way to its page."""
    view = await ui_resources.overview(wait=wait)
    unwell = [
        row
        | {
            "tone": health_tone(row["state_status"]),
            "troubles": why,
            "url": runtime_page_url(row["page"]),
        }
        for row in view["rows"]
        if (why := [reason for _, reason in container_health.troubles(row)])
        or row["state_status"] != "healthy"
    ]
    rest = {key: value for key, value in view.items() if key != "rows"}
    return {"resources": rest | {"unwell": unwell}}


def events(  # noqa: ANN201 - async iterator
    window: int = series.DEFAULT_WINDOW, max_frames: int | None = None
):
    """The snapshot and each chart over SSE (``overseer_live.live_events``)."""

    async def read(draw: bool) -> tuple[dict[str, str], Drawn]:
        if draw:
            view, drawn = await asyncio.gather(
                _view(wait=True), ui_resources.charts(window)
            )
        else:
            view, drawn = await _view(wait=True), None
        sent = {EVENT: fragment(BODY, **view)} | {
            _split_event(split): fragment(SPLIT, split=split)
            for split in view["resources"]["split"]
        }
        return sent, drawn

    return live_events(EVENT, read, window, max_frames)
