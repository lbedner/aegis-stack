"""Container logs, as Overseer shows them in htmx and Flet alike: one
page's (its Logs section) or several pages' (Overseer > Logs).

``recent(pages, query)`` reads the last lines of every container behind
``pages`` (named by the containers sampler's reading, ``ui_runtime``),
merged by time, newest first. ``follow(pages, query)`` yields new lines in
batches as the containers write them; Docker pushes them, so following
polls nothing. Both fold a traceback into the line it belongs to and
apply the filters a query carries: ``window`` (one of ``WINDOWS``),
``level`` (that level and worse), ``q`` (text) and ``order`` (one of
``ORDERS``). No UI framework imports.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import re
from typing import Any

from app.core import runtime, series
from app.core.formatting import format_timestamp
from app.core.log import logger
from app.core.runtime import LogLine, RuntimeUnavailableError
from app.services.system import ui_runtime
from app.services.system.ui import get_component_title

# The windows the logs offer, in seconds, labelled as every range chip row
# labels them; "All" reads each container from its start.
ALL = 0
WINDOWS: tuple[tuple[int, str], ...] = (
    (900, "15m"),
    (3600, "1h"),
    (21600, "6h"),
    (86400, "1d"),
    (ALL, "All"),
)
DEFAULT_WINDOW = 900
ORDERS = (("desc", "Newest first"), ("asc", "Oldest first"))
DEFAULT_ORDER = "desc"
LEVELS = ("debug", "info", "warning", "error", "critical")
TAIL = 500  # the most lines read from each container
# How long a followed line waits for the traceback that may follow it.
FLUSH_SECONDS = 0.5
# Lines that continue a traceback above them, besides indented ones.
_TRACEBACK = (
    "Traceback (most recent call last)",
    "During handling of the above exception",
    "The above exception was the direct cause",
)
_RAISED = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Warning|Exit|Interrupt)\b")
# A plain line's lead that the time and level columns already show: a date
# and time (an optional zone after it), a bare time, or a level tag, then
# any bracketed groups (logger, process) up to the message.
_LEAD = re.compile(
    r"^(?:\[?\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?(?-i:Z| ?[A-Z]{2,4}\b)?\]?"
    r"|\[\d\d:\d\d:\d\d\]"
    r"|(?:debug|info|warn|warning|error|critical)\s*:)"
    r"\s*(?:\[[^\]]*\]\s*)*",
    re.IGNORECASE,
)
# The chart ramp both UIs draw with (--aegis-chart-1..8, ChartColors.RAMP):
# a service's lines take one of its colors.
RAMP = 8
_PAGES = sorted(runtime.PAGES)


def color_of(page: str) -> int:
    """A page's color, an index into the chart ramp: the same on every page
    and in both UIs, and (with no more pages than colors) no two alike."""
    return _PAGES.index(page) % RAMP if page in _PAGES else 0


def _split_lead(text: str) -> tuple[str, str]:
    """``(lead, message)``: the lead the columns repeat, or none when it
    would leave no message."""
    lead = _LEAD.match(text)
    if lead is None or not text[lead.end() :].strip():
        return "", text
    return lead.group(), text[lead.end() :]


@dataclass
class _Row:
    """One line as shown, with the traceback lines folded under it."""

    page: str
    instance: str
    line: LogLine
    folded: list[str] = field(default_factory=list)

    def fold(self, text: str) -> None:
        self.folded.append(text)

    @property
    def trace(self) -> str | None:
        """A JSON line's own traceback, then any folded under it."""
        parts = [part for part in (self.line.trace, *self.folded) if part]
        return "\n".join(parts) or None

    def view(self) -> dict[str, Any]:
        when = self.line.timestamp
        lead, message = (
            ("", self.line.event) if self.line.event else _split_lead(self.line.text)
        )
        return {
            "at": format_timestamp(when.isoformat()) if when else "-",
            "page": self.page,
            "color": color_of(self.page),
            "instance": self.instance,
            "level": self.line.level,
            "prefix": lead,
            "message": message,
            "fields": list(self.line.fields),
            "trace": self.trace,
        }


def _continues(line: LogLine, last: _Row) -> bool:
    """Whether ``line`` is the traceback (or more of it) under ``last``."""
    text = line.text
    if not text.strip():
        return last.trace is not None
    return (
        text[0].isspace()
        or text.startswith(_TRACEBACK)
        or (last.trace is not None and _RAISED.match(text) is not None)
    )


def _rows(page: str, instance: str, lines: list[LogLine]) -> list[_Row]:
    rows: list[_Row] = []
    for line in lines:
        if rows and _continues(line, rows[-1]):
            rows[-1].fold(line.text)
        elif line.text.strip():
            rows.append(_Row(page, instance, line))
    return rows


def _passes(row: _Row, query: Mapping[str, str]) -> bool:
    """The level filter (that level and worse; a line with none is left out)
    and the text filter (any of what the row shows)."""
    level = query.get("level", "")
    if level in LEVELS and (
        row.line.level not in LEVELS
        or LEVELS.index(row.line.level) < LEVELS.index(level)
    ):
        return False
    text = query.get("q", "").strip().lower()
    shown = " ".join([row.line.text, row.trace or ""]).lower()
    return not text or text in shown


def order_of(query: Mapping[str, str]) -> str:
    """The order a query asks for, the newest first unless it names another."""
    order = query.get("order", "")
    return order if order in dict(ORDERS) else DEFAULT_ORDER


def _shown(rows: list[_Row], query: Mapping[str, str]) -> list[dict[str, Any]]:
    """The rows that pass the filters, in the order the query asks for."""
    rows = sorted(rows, key=lambda row: row.line.timestamp or datetime.min)
    if order_of(query) == "desc":
        rows.reverse()
    return [row.view() for row in rows if _passes(row, query)]


async def _names(pages: Sequence[str]) -> tuple[list[tuple[str, str]], str | None]:
    """Each page's containers as ``(page, container)``, or why there are
    none (the first page's reason)."""
    # One at a time: the first read takes the sampler's first sample, and the
    # rest are served from it (read together, all but one would find none).
    views = [await ui_runtime.containers(page) for page in pages]
    names = [
        (page, row["name"])
        for page, view in zip(pages, views, strict=True)
        for row in view["rows"]
    ]
    return names, None if names else next((v["note"] for v in views), None)


async def sources() -> list[dict[str, str]]:
    """The pages with a container behind them, each with its title: what
    Overseer > Logs can show."""
    pages = sorted(runtime.PAGES)
    names, _note = await _names(pages)
    shown = {page for page, _ in names}
    found = [
        {"page": page, "title": get_component_title(ui_runtime.component_of(page))}
        for page in pages
        if page in shown
    ]
    return sorted(found, key=lambda source: source["title"])


async def recent(pages: Sequence[str], query: Mapping[str, str]) -> dict[str, Any]:
    """``{"lines": [...], "note": str | None}``: the window's lines from every
    container behind ``pages`` that pass the filters, in the query's order."""
    names, note = await _names(pages)
    if not names:
        return {"lines": [], "note": note}
    window = series.window_of(query.get("window"), WINDOWS, DEFAULT_WINDOW)
    since = None if window == ALL else datetime.now(UTC) - timedelta(seconds=window)
    try:
        read = await asyncio.gather(
            *(runtime.logs(name, tail=TAIL, since=since) for _, name in names)
        )
    except RuntimeUnavailableError as exc:
        return {"lines": [], "note": f"The runtime did not answer: {exc}"}
    rows = [
        row
        for (page, name), lines in zip(names, read, strict=True)
        for row in _rows(page, name, lines)
    ]
    return {"lines": _shown(rows, query), "note": None}


async def follow(
    pages: Sequence[str], query: Mapping[str, str]
) -> AsyncIterator[list[dict[str, Any]]]:
    """New lines from every container behind ``pages`` as they are written,
    in batches in the query's order, each line once its traceback (if any)
    has arrived."""
    names, _note = await _names(pages)
    if not names:
        return
    page_by_name = {name: page for page, name in names}
    arrived: asyncio.Queue[tuple[str, LogLine | None]] = asyncio.Queue()
    pumps = [asyncio.create_task(_pump(name, arrived)) for _, name in names]
    waiting: dict[str, _Row] = {}
    open_streams = len(names)
    try:
        while open_streams:
            try:
                name, line = await asyncio.wait_for(arrived.get(), FLUSH_SECONDS)
            except TimeoutError:
                ready, waiting = list(waiting.values()), {}
            else:
                last = waiting.get(name)
                if line is None:
                    open_streams -= 1
                    ready = [waiting.pop(name)] if last else []
                elif last is not None and _continues(line, last):
                    last.fold(line.text)
                    continue
                else:
                    ready = [waiting.pop(name)] if last else []
                    if line.text.strip():
                        waiting[name] = _Row(page_by_name[name], name, line)
            if batch := _shown(ready, query):
                yield batch
        if batch := _shown(list(waiting.values()), query):
            yield batch
    finally:
        for pump in pumps:
            pump.cancel()


async def _pump(name: str, arrived: asyncio.Queue[tuple[str, LogLine | None]]) -> None:
    """One container's followed lines onto the shared queue, then its end."""
    try:
        async for line in runtime.follow(name):
            await arrived.put((name, line))
    except RuntimeUnavailableError as exc:
        logger.warning("ui_logs.follow_failed", container=name, error=str(exc))
    finally:
        await arrived.put((name, None))
