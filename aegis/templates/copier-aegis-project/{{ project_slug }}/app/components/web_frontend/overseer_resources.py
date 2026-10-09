"""Overseer > Resources, what ``ui_resources`` reads, its figures charted
over the chosen window. It opens on the samplers' last readings, then an
SSE stream re-sends the snapshot and each chart's new points every tick
while it is open."""

import asyncio
from typing import Any

from app.core import series
from app.services.system import ui_resources
from app.services.system.models import ComponentStatus

from . import overseer_container
from .overseer_live import chart_frames, chart_panel, fragments_events
from .overseer_nav import NavItem, SectionRequest, runtime_page_url
from .rendering import fragment, ranked, status_cell

SECTIONS = ((None, {"overview": "Overview"}),)
ITEM = NavItem(
    group="resources",
    name="resources",
    title="Resources",
    url="/overseer/resources",
    status="",
    component=ComponentStatus(name="resources", message=""),
)
EVENTS = "/overseer/events/resources"
EVENT = "resources"
BODY = "pages/overseer/resources/_body.html"
# The split above the charts, sent apart from the rest of the snapshot.
TOTALS_EVENT = "resources-totals"
TOTALS = "pages/overseer/resources/_totals.html"


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    window = series.window_of(req.query.get("window"))
    charts, view = await asyncio.gather(ui_resources.charts(window), _view(wait=False))
    return {
        "section_subtitle": "What this stack uses of the host, and what the rest of it does.",
        "resources_event": EVENT,
        "resources_totals_event": TOTALS_EVENT,
        "resources_charts": chart_panel(EVENT, charts, window, EVENTS),
    } | view


async def _view(*, wait: bool) -> dict[str, Any]:
    """The overview, each row with its state's tone and the way to its page,
    as the table's cells want them."""
    view, load = await asyncio.gather(
        ui_resources.overview(wait=wait), ui_resources.load_costs()
    )
    if load is not None:  # each row's bar, scaled to the largest
        load = load | {"rows": ranked(load["rows"], by="bytes")}
    found: dict[str, Any] = overseer_container.toned(view) | {"load": load}
    for row in found["rows"]:
        row["id"] = row["name"]
        row["status"] = status_cell(row["state"], row["tone"])
        row["service"] = {"label": row["title"], "url": runtime_page_url(row["page"])}
    return {"resources": found}


def events(  # noqa: ANN201 - async iterator
    window: int = series.DEFAULT_WINDOW, max_frames: int | None = None
):
    """The snapshot and each chart over SSE, each sent again only when it
    changes (``overseer_live.chart_frames``)."""
    held: dict[str, tuple[list[str], int]] = {}

    async def frame() -> dict[str, str]:
        charts, view = await asyncio.gather(
            ui_resources.charts(window), _view(wait=True)
        )
        return {
            EVENT: fragment(BODY, **view),
            TOTALS_EVENT: fragment(TOTALS, **view),
        } | chart_frames(EVENT, charts, held)

    return fragments_events(frame, series.TICK_SECONDS, max_frames)
