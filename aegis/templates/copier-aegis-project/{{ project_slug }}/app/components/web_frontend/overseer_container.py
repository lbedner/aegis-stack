"""The Container section: every Overseer page with a container behind it
gets one (``overseer_sections`` adds it), listing the page's instances
(``ui_runtime.containers``) and charting them over the chosen window. It
renders from the containers sampler's last reading, so it opens full, then
an SSE stream re-sends the table and each chart every tick while it is
open."""

import asyncio
from collections.abc import Mapping
from typing import Any

from app.core import series
from app.services.system import ui_runtime

from .overseer_live import fragments_events
from .rendering import fragment, templates, with_query

SECTION = {"container": "Container"}
EVENTS = "/overseer/events/container/{page}"
EVENT = "container"
TABLE = "pages/overseer/_container_table.html"
# The table's columns (``ui_runtime.COLUMNS``) as ``data_table`` draws them.
COLUMNS = [
    {"key": key, "label": label, "kind": "code" if key in ("name", "image") else "text"}
    for key, label in ui_runtime.COLUMNS
]
MACROS = "components/macros/layout.html"


async def context(page: str, query: Mapping[str, str]) -> dict[str, Any]:
    """The section's table and its charts over the chosen ``window`` as last
    sampled, so it opens full and never waits on the runtime (``PENDING``
    before the first sample), the range chips, and where it all refreshes
    from."""
    seconds = series.window_of(query.get("window"))
    table, charts = await asyncio.gather(
        ui_runtime.containers(page, wait=False), ui_runtime.charts(page, seconds)
    )
    return {
        "container": table,
        "container_columns": COLUMNS,
        "container_charts": [
            chart | {"id": chart_event(chart["key"])} for chart in charts
        ],
        "container_events": with_query(EVENTS.format(page=page), window=str(seconds)),
        "container_windows": series.WINDOWS,
        "container_window": seconds,
    }


def render(view: dict[str, Any]) -> str:
    return fragment(TABLE, container=view, container_columns=COLUMNS)


def chart_event(key: str) -> str:
    """The SSE event (and chart id) for one of the section's charts."""
    return f"{EVENT}-{key}"


def events(  # noqa: ANN201 - async iterator
    page: str, window: int = series.DEFAULT_WINDOW, max_frames: int | None = None
):
    """The table and each chart over SSE, each sent again only when it
    changes."""
    chart_data = templates.env.get_template(MACROS).module.chart_data  # type: ignore[attr-defined]

    async def frame() -> dict[str, str]:
        table, charts = await asyncio.gather(
            ui_runtime.containers(page), ui_runtime.charts(page, window)
        )
        sent = {EVENT: render(table)}
        for chart in charts:
            event = chart_event(chart["key"])
            sent[event] = str(chart_data(event, chart["data"]))
        return sent

    return fragments_events(frame, series.TICK_SECONDS, max_frames)
