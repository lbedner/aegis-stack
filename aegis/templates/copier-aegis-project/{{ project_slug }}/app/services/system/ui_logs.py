"""Container logs, as Overseer shows them in htmx and Flet alike: one
page's (its Logs section) or several pages' (Overseer > Logs).

``recent(pages, query)`` reads the last lines of every container behind
``pages`` (named by the containers sampler's reading, ``ui_runtime``),
merged by time, newest first. ``follow(pages, query)`` yields new lines in
batches as the containers write them; Docker pushes them, so following
polls nothing. Both fold a traceback into the line it belongs to and
apply the filters a query carries: ``window`` (one of ``WINDOWS``),
``level`` (the levels picked), ``q`` (text), ``from`` and ``to`` (a
time range in ms, a volume bar's) and ``order`` (one of ``ORDERS``).
``recent`` also counts the window's lines by tone (``volume``). No UI
framework imports.
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import os
import re
from typing import Any, Self

from app.core import runtime, series
from app.core.formatting import format_relative_time, format_timestamp
from app.core.log import logger
from app.core.runtime import LogLine, RuntimeUnavailableError
from app.core.time import utcnow
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
# The level filter's pick for a line with no level (Redis's, a plain print).
NO_LEVEL = "none"
# What the level filter offers, in both UIs.
LEVEL_CHOICES = (
    *((level, level.capitalize()) for level in LEVELS),
    (NO_LEVEL, "No level"),
)
# A level's tone (badge, edge, volume stack); info and none stay plain.
TONES = {"debug": "muted", "warning": "warn", "error": "error", "critical": "error"}
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
# A plain line's lead that the time cell and level tag already show: a date
# and time (an optional zone after it), a bare time, or a level tag, then
# any bracketed groups (logger, process) up to the message.
_LEAD = re.compile(
    r"^(?:\[?\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?(?-i:Z| ?[A-Z]{2,4}\b)?\]?"
    r"|\[\d\d:\d\d:\d\d\]"
    r"|(?:debug|info|warn|warning|error|critical)\s*:)"
    r"\s*(?:\[[^\]]*\]\s*)*",
    re.IGNORECASE,
)
# The volume above the lines: the window in this many bars, each line
# counted in its tone's stack.
VOLUME_BARS = 60
VOLUME_TONES = ("error", "warn", "other")
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
    # Which of its page's containers, when it has several (``_sources``).
    source: str = ""
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
            "ms": _ms(when) if when else None,
            "page": self.page,
            "color": color_of(self.page),
            "instance": self.instance,
            "source": self.source,
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


def _rows(
    page: str, instance: str, lines: list[LogLine], source: str = ""
) -> list[_Row]:
    rows: list[_Row] = []
    for line in lines:
        if rows and _continues(line, rows[-1]):
            rows[-1].fold(line.text)
        elif line.text.strip():
            rows.append(_Row(page, instance, line, source))
    return rows


def _sources(names: list[tuple[str, str]]) -> dict[str, str]:
    """Each container by what its name does not share with its page's other
    containers (``system`` of ``app-worker-system-1``), none when alone."""
    by_page: dict[str, list[str]] = defaultdict(list)
    for page, name in names:
        by_page[page].append(name)
    found: dict[str, str] = {}
    for kept in by_page.values():
        if len(kept) == 1:
            found[kept[0]] = ""
            continue
        head = len(os.path.commonprefix(kept))
        tail = len(os.path.commonprefix([name[::-1] for name in kept]))
        for name in kept:
            found[name] = name[head : max(head, len(name) - tail)].strip("-_") or name
    return found


def _ms(at: datetime) -> int:
    """A log time (naive UTC, as ``runtime`` reads it) in epoch ms."""
    return round(at.replace(tzinfo=UTC).timestamp() * 1000)


def _bound(query: Mapping[str, str], key: str) -> int | None:
    value = query.get(key, "")
    return int(value) if value.isdigit() else None


def levels_of(query: Mapping[str, str]) -> list[str]:
    """The levels a query picks that the filter knows (``LEVEL_CHOICES``)."""
    known = dict(LEVEL_CHOICES)
    return [level for level in listed(query, "level") if level in known]


@dataclass(frozen=True)
class _Filter:
    """A query's filters, read once: exactly the levels picked (``NO_LEVEL``
    for a line with none), the text (any of what the row shows), and the
    ``from``/``to`` range (ms, ``to`` excluded) a volume bar picks."""

    levels: frozenset[str]
    text: str
    start: int | None
    end: int | None

    @classmethod
    def of(cls, query: Mapping[str, str]) -> Self:
        return cls(
            frozenset(levels_of(query)),
            query.get("q", "").strip().lower(),
            _bound(query, "from"),
            _bound(query, "to"),
        )

    def keeps(self, row: _Row) -> bool:
        """The level and text filters."""
        if self.levels and (row.line.level or NO_LEVEL) not in self.levels:
            return False
        if not self.text:
            return True
        return self.text in " ".join([row.line.text, row.trace or ""]).lower()

    def in_range(self, row: _Row) -> bool:
        if self.start is None and self.end is None:
            return True
        if row.line.timestamp is None:
            return False
        at = _ms(row.line.timestamp)
        return (self.start is None or at >= self.start) and (
            self.end is None or at < self.end
        )


def order_of(query: Mapping[str, str]) -> str:
    """The order a query asks for, the newest first unless it names another."""
    order = query.get("order", "")
    return order if order in dict(ORDERS) else DEFAULT_ORDER


def _ordered(rows: list[_Row], order: str) -> list[dict[str, Any]]:
    """``rows`` as shown, in ``order``."""
    rows = sorted(rows, key=lambda row: row.line.timestamp or datetime.min)
    if order == "desc":
        rows.reverse()
    return [row.view() for row in rows]


def _volume(
    kept: list[_Row], since: datetime | None, picked: _Filter
) -> list[dict[str, Any]]:
    """The window in ``VOLUME_BARS`` bars (``from`` and ``to`` in ms), each
    counting the lines the level and text filters keep, by tone, whatever
    range a bar narrowed the lines to; a bar inside that range is
    ``picked``."""
    end = utcnow()
    first = min((r.line.timestamp for r in kept if r.line.timestamp), default=end)
    start = (
        since.replace(tzinfo=None)
        if since
        else min(first, end - timedelta(seconds=DEFAULT_WINDOW))
    )
    step = max((end - start) / VOLUME_BARS, timedelta(milliseconds=1))
    lo, hi = picked.start, picked.end
    bars = []
    for i in range(VOLUME_BARS):
        frm, to = _ms(start + i * step), _ms(start + (i + 1) * step)
        middle = (frm + to) // 2
        bars.append(
            {
                "from": frm,
                "to": to,
                # How long ago it starts (a day or more back, its date).
                "at": format_relative_time(
                    start + i * step, now=end.replace(tzinfo=UTC)
                ),
                "picked": lo is not None and hi is not None and lo <= middle < hi,
                **dict.fromkeys(VOLUME_TONES, 0),
            }
        )
    for row in kept:
        at = row.line.timestamp
        if at is None or at < start:
            continue
        tone = TONES.get(row.line.level or "")
        bar = bars[min(int((at - start) / step), VOLUME_BARS - 1)]
        bar[tone if tone in ("warn", "error") else "other"] += 1
    for bar in bars:
        bar["total"] = sum(bar[tone] for tone in VOLUME_TONES)
    return bars


def listed(query: Mapping[str, str], key: str) -> list[str]:
    """Every value ``query`` gives ``key`` (a multi-select's picks)."""
    getlist = getattr(query, "getlist", None)
    if getlist is not None:
        return list(getlist(key))
    return [query[key]] if query.get(key) else []


async def _names(pages: Sequence[str]) -> tuple[list[tuple[str, str]], str | None]:
    """Each page's containers as ``(page, container)``, or why there are
    none (the first page's reason)."""
    views = await ui_runtime.containers_of(list(pages))
    names = [(page, row["name"]) for page in pages for row in views[page]["rows"]]
    return names, None if names else next((v["note"] for v in views.values()), None)


def _narrowed(
    names: list[tuple[str, str]], query: Mapping[str, str]
) -> list[tuple[str, str]]:
    """``names`` with a page that has a ``container`` picked keeping only the
    picked ones."""
    picked = set(listed(query, "container"))
    narrowed = {page for page, name in names if name in picked}
    return [(p, n) for p, n in names if p not in narrowed or n in picked]


async def sources(pages: Sequence[str] = ()) -> list[dict[str, Any]]:
    """The pages (``pages``, every page by default) with a container behind
    them, each with its title and, for a page with several, each container
    and what tells it apart: what a Logs view can pick from."""
    pages = sorted(pages or runtime.PAGES)
    names, _note = await _names(pages)
    short = _sources(names)
    found = [
        {
            "page": page,
            "title": get_component_title(ui_runtime.component_of(page)),
            "containers": [
                {"name": name, "label": short[name]}
                for p, name in names
                if p == page and short[name]
            ],
        }
        for page in pages
        if any(p == page for p, _ in names)
    ]
    return sorted(found, key=lambda source: source["title"])


async def recent(
    pages: Sequence[str], query: Mapping[str, str], *, volume: bool = False
) -> dict[str, Any]:
    """``{"lines": [...], "volume": [...], "note": str | None}``: the
    window's lines from every container behind ``pages`` that pass the
    filters, in the query's order, and, asked for, their ``volume``."""
    every, note = await _names(pages)
    source = _sources(every)  # what tells a container apart, picked or not
    names = _narrowed(every, query)
    if not names:
        return {"lines": [], "volume": [], "note": note}
    window = series.window_of(query.get("window"), WINDOWS, DEFAULT_WINDOW)
    since = None if window == ALL else datetime.now(UTC) - timedelta(seconds=window)
    try:
        read = await asyncio.gather(
            *(runtime.logs(name, tail=TAIL, since=since) for _, name in names)
        )
    except RuntimeUnavailableError as exc:
        return {"lines": [], "volume": [], "note": f"The runtime did not answer: {exc}"}
    rows = [
        row
        for (page, name), lines in zip(names, read, strict=True)
        for row in _rows(page, name, lines, source[name])
    ]
    picked = _Filter.of(query)
    kept = [row for row in rows if picked.keeps(row)]
    return {
        "lines": _ordered([r for r in kept if picked.in_range(r)], order_of(query)),
        "volume": _volume(kept, since, picked) if volume else [],
        "note": None,
    }


async def follow(
    pages: Sequence[str], query: Mapping[str, str]
) -> AsyncIterator[list[dict[str, Any]]]:
    """New lines from every container behind ``pages`` as they are written,
    in batches in the query's order, each line once its traceback (if any)
    has arrived."""
    every, _note = await _names(pages)
    source = _sources(every)
    names = _narrowed(every, query)
    if not names:
        return
    page_by_name = {name: page for page, name in names}
    picked, order = _Filter.of(query), order_of(query)

    def shown(rows: list[_Row]) -> list[dict[str, Any]]:
        return _ordered(
            [r for r in rows if picked.keeps(r) and picked.in_range(r)], order
        )

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
                        waiting[name] = _Row(
                            page_by_name[name], name, line, source[name]
                        )
            if batch := shown(ready):
                yield batch
        if batch := shown(list(waiting.values())):
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
