"""A run's log on the Overseer (``run_log``): under the row that started
it (a worker task, a scheduled run, a job), the lines written so far and,
while the run is on, the lines again over SSE whenever they grow. Any
page with a run id loads ``{PARTIALS}/{run_id}/log`` into its row
(``?live=1`` while the run is on); a row that keeps its own copy renders
the same box through ``box``.
"""

from collections.abc import AsyncIterator

from app.core import run_log

from .overseer_live import fragments_events
from .rendering import fragment

PARTIALS = "/partials/overseer/runs"
BOX = "pages/overseer/_run_log.html"
LINES = "pages/overseer/_run_log_lines.html"
EVENT = "run-log"
INTERVAL_SECONDS = 1.0


def log_url(run_id: str, live: bool) -> str:
    return f"{PARTIALS}/{run_id}/log" + ("?live=1" if live else "")


def box(run_id: str, lines: list[str], live: bool) -> str:
    """The box for these lines, following the run's while it is on."""
    return fragment(
        BOX,
        lines=lines,
        events=f"{PARTIALS}/{run_id}/log/events" if live else None,
        event=EVENT,
    )


def render_box(run_id: str, live: bool) -> str:
    return box(run_id, run_log.sink().read(run_id), live)


def events(run_id: str, max_frames: int | None = None) -> AsyncIterator[str]:
    """The lines over SSE, read and sent again only when more were written.

    ponytail: every line each time, under ``run_log.MAX_LINES``; the new
    ones only when a log that long is watched often.
    """
    seen = -1

    async def lines() -> dict[str, str]:
        nonlocal seen
        count = run_log.sink().count(run_id)
        if count == seen:
            return {}
        seen = count
        return {EVENT: fragment(LINES, lines=run_log.sink().read(run_id))}

    return fragments_events(lines, INTERVAL_SECONDS, max_frames)
