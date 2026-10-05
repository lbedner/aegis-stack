"""Time series for live charts: anything the app polls or counts, kept for
an hour.

A ``Sampler`` names what it reads and how often; ``read`` returns a
``Sample``: numbers by series name (``"redis:app-redis-1:cpu"``), and the
reading as a whole (``latest``) for the views that show it. Each tick's
numbers are kept in the shared cache under ``series:<sampler>:<name>``
(Redis when the stack has it, so every process reads the same history;
this process's memory otherwise), listed in an index per sampler so reads
never scan the keyspace. One process samples each tick (``claim``).

Polling costs only while someone looks: a view that reads a sampler's
latest (``watch``) keeps it at ``interval``; unwatched, it reads every
``idle_interval``, enough to keep the charts' history. Something that
happens rather than something polled (an LLM call finishing) is a point
of its own: ``record``.

``read`` gets a window back and ``chart`` turns it into what
``chart_panel`` draws. Transient on purpose: an hour, then gone. Longer
history (downsampled, or in the database) can sit behind the same ``read``.
"""

import asyncio
from bisect import bisect_left
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
import math
import time
from typing import Any

from app.core.cache import get_cache
from app.core.log import logger

PREFIX = "series:"
INDEX = "series-index:"
LATEST = "series-latest:"
WATCH = "series-watch:"
CLAIM = "series-claim:"
KEEP_SECONDS = 3600
# Series named in more than one part of the app, each written in one place
# and charted in another: the inference sampler's (each loaded model's
# memory and VRAM) and each LLM call's (``record``), which the Inference
# page charts. Here because core is the one module both sides always have.
INFERENCE = "inference"
LLM = "llm"
MEMORY = "memory"
VRAM = "vram"
LATENCY = "latency"
TOKENS_PER_SECOND = "tokens_per_second"
# A sampler's pace while watched, and so a live view's.
TICK_SECONDS = 1.0
# How long a view's look keeps its sampler at full pace: longer than the
# slowest reader's pace (the Flet modal reads every 5 s), so it never lapses
# between two looks.
WATCH_SECONDS = 15
# The windows a live chart offers, in seconds, labelled as every range chip
# row labels them (``web_frontend/ranges.py``); none longer than is kept.
WINDOWS: tuple[tuple[int, str], ...] = ((900, "15m"), (1800, "30m"), (3600, "1h"))
DEFAULT_WINDOW = 900
# The most points a chart line carries: a longer window is averaged down.
MAX_POINTS = 900
# A chart's threshold shows once its data is within 1/GUIDE_REACH of it.
GUIDE_REACH = 2


def window_of(
    value: str | int | None,
    windows: tuple[tuple[int, str], ...] = WINDOWS,
    default: int = DEFAULT_WINDOW,
) -> int:
    """A window from a query string or a chip: one of ``windows`` (a chip
    row's ``(value, label)`` pairs, a live chart's by default), or
    ``default``."""
    number = int(value) if isinstance(value, int) or (value or "").isdigit() else None
    return number if number in dict(windows) else default


def phrase(seconds: int) -> str:
    """A window in words: "the last 15 minutes", "the last hour"."""
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "the last hour" if hours == 1 else f"the last {hours} hours"
    return f"the last {seconds // 60} minutes"


@dataclass(frozen=True)
class Sample:
    """One reading: numbers by series name, and the whole of it for views."""

    values: dict[str, float] = field(default_factory=dict)
    latest: Any = None


@dataclass(frozen=True)
class Sampler:
    """What to read, every ``interval`` while watched, every
    ``idle_interval`` otherwise."""

    name: str
    read: Callable[[], Awaitable[Sample]]
    interval: float = TICK_SECONDS
    idle_interval: float = 15.0


async def watch(name: str) -> None:
    """Someone is looking at what ``name`` samples: keep it at full pace."""
    await get_cache().set(WATCH + name, True, ttl=WATCH_SECONDS)


async def watched(name: str) -> bool:
    return await get_cache().get(WATCH + name) is not None


async def latest(name: str) -> Any:
    """The sampler's last reading as a whole, or None before its first."""
    return await get_cache().get(LATEST + name)


async def current(sampler: Sampler, *, fill: bool = True) -> Any:
    """What a view shows: the sampler's last reading, kept at full pace while
    the view looks (``watch``). Before the first, ``fill`` takes one sample
    through the claim (one process reads, every view is served from it);
    None when another process holds this tick, or with ``fill=False``."""
    await watch(sampler.name)
    found = await latest(sampler.name)
    if found is None and fill:
        await sample(sampler)
        found = await latest(sampler.name)
    return found


async def reading(sampler: Sampler) -> Any:
    """What a view of ``sampler`` shows: its kept reading (``current``), or,
    when another process holds this tick and nothing is kept yet, a read of
    its own."""
    found = await current(sampler)
    return found if found is not None else (await sampler.read()).latest


async def record(values: dict[str, float]) -> None:
    """Points for something that happened (``{"llm:qwen3:latency": 1.4}``),
    with no sampler behind them; each name's first part names the index it
    is listed in."""
    by_sampler: dict[str, dict[str, float]] = {}
    for name, value in values.items():
        sampler, rest = name.split(":", 1)
        by_sampler.setdefault(sampler, {})[rest] = value
    for sampler, kept in by_sampler.items():
        await _keep(sampler, kept)


async def _keep(sampler: str, values: dict[str, float]) -> None:
    """One sampler's points for this moment, in one write."""
    await get_cache().append_many(
        {f"{PREFIX}{sampler}:{name}": value for name, value in values.items()},
        at=time.time(),
        keep_seconds=KEEP_SECONDS,
        index=INDEX + sampler,
    )


async def sample(sampler: Sampler, cadence: float | None = None) -> None:
    """Read once and keep what came back, unless another process has this
    tick. The claim lapses a second before the next one is due, and each
    pace claims apart: a viewer arriving mid idle wait gets the next tick."""
    every = cadence or sampler.interval
    claim = f"{CLAIM}{sampler.name}:{every:g}"
    if not await get_cache().claim(claim, ttl=max(int(every) - 1, 1)):
        return
    reading = await sampler.read()
    if reading.latest is not None:
        ttl = int(sampler.idle_interval * 2)
        await get_cache().set(LATEST + sampler.name, reading.latest, ttl=ttl)
    await _keep(sampler.name, reading.values)


async def tick(sampler: Sampler, last: float, now: float) -> float:
    """Sample if someone is watching or the idle interval has passed; the
    time of the last sample after."""
    if await watched(sampler.name):
        await sample(sampler)
        return now
    if now - last < sampler.idle_interval:
        return last
    await sample(sampler, sampler.idle_interval)
    return now


async def run(samplers: Iterable[Sampler]) -> None:
    """Sample each at its pace until cancelled."""
    await asyncio.gather(*(_keep_sampling(s) for s in samplers))


async def _keep_sampling(sampler: Sampler) -> None:
    last = float("-inf")
    while True:
        try:
            last = await tick(sampler, last, time.monotonic())
        except Exception as exc:  # one bad read must not end the loop
            logger.warning("series.sample_failed", sampler=sampler.name, error=str(exc))
        await asyncio.sleep(sampler.interval)


async def read(
    prefix: str,
    window: float,
    *,
    viewed: bool = False,
    ending: tuple[str, ...] = (),
) -> dict[str, list[tuple[float, float]]]:
    """The last ``window`` seconds of every series under ``prefix``
    (``"containers:redis:"``), by the rest of its name; given ``ending``,
    only the names ending with one of those (``(":cpu",)``). ``viewed``: a
    view is drawing it, so its sampler keeps full pace (``watch``)."""
    if viewed:
        await watch(prefix.split(":", 1)[0])
    start = PREFIX + prefix
    found = await get_cache().points_with_prefix(
        start,
        since=time.time() - window,
        index=INDEX + prefix.split(":", 1)[0],
        ending=ending,
    )
    return {key.removeprefix(start): points for key, points in sorted(found.items())}


def chart(
    found: dict[str, list[tuple[float, float]]],
    label: Callable[[str], str],
    fmt: str | None = None,
    window: float | None = None,
    max_points: int = MAX_POINTS,
    style: str | None = None,
    thresholds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``chart_panel`` data (the one home of its shape): one line per series, on the times they share
    (ms, which the browser shows on its own clock); a gap where one has no
    point. With ``window``, the axis spans that many seconds up to now, so
    an empty chart reads right and a live one keeps moving. More than
    ``max_points`` across it are averaged into buckets on fixed boundaries,
    so a bucket keeps its place as the window moves. ``style="events"``:
    each point is a moment (a call), drawn as a dot rather than a line.
    ``thresholds`` (``app.core.thresholds.levels``): the dashed guides, the
    ones in reach of the data."""
    found = _bucketed(found, window, max_points)
    times = sorted({at for points in found.values() for at, _ in points})
    tables = {name: dict(points) for name, points in found.items()}
    lines = [
        {"label": label(name), "values": [table.get(at) for at in times]}
        for name, table in tables.items()
    ]
    drawn: dict[str, Any] = {
        "labels": [round(at * 1000) for at in times],
        "series": lines,
        "x": "time",
        "format": fmt,
        # How many values it has: what every view reads to say "nothing yet".
        "points": sum(v is not None for line in lines for v in line["values"]),
    }
    if style is not None:
        drawn["style"] = style
    if thresholds:
        drawn["thresholds"] = thresholds_in_reach(drawn["series"], thresholds)
    if window is not None:
        now = time.time()
        drawn["window"] = [round((now - window) * 1000), round(now * 1000)]
    return drawn


def thresholds_in_reach(
    lines: list[dict[str, Any]], thresholds: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The ``thresholds`` the ``lines``' values come within reach of: every
    one is drawn and the axis takes it in, so an alert at 640% (eight cores)
    would flatten a 5% line. Judged on the whole window, so a live frame
    (``since``) carries the ones its chart shows."""
    values = [v for line in lines for v in line["values"] if v is not None]
    top = max(values, default=0) * GUIDE_REACH
    return [t for t in thresholds if t["value"] <= top]


def since(drawn: dict[str, Any], after: int) -> dict[str, Any]:
    """``chart``'s ``drawn`` from ``after`` (ms) on: what a live chart lacks,
    given it holds everything up to ``after``, whose bucket may still be
    filling. ``points`` still counts the whole window."""
    start = bisect_left(drawn["labels"], after)  # the labels are in time order
    return drawn | {
        "labels": drawn["labels"][start:],
        "series": [
            line | {"values": line["values"][start:]} for line in drawn["series"]
        ],
    }


def _bucketed(
    found: dict[str, list[tuple[float, float]]],
    window: float | None,
    max_points: int,
) -> dict[str, list[tuple[float, float]]]:
    times = [at for points in found.values() for at, _ in points]
    span = window or (max(times) - min(times) if times else 0)
    if span <= max_points:
        return found
    step = math.ceil(span / max_points)
    bucketed = {}
    for name, points in found.items():
        buckets: dict[float, list[float]] = {}
        for at, value in points:
            buckets.setdefault(at // step * step, []).append(value)
        bucketed[name] = [(at, sum(vs) / len(vs)) for at, vs in sorted(buckets.items())]
    return bucketed


# Every sparkline's box (the ``sparkline`` macro's viewBox): drawn at any
# size, since its stroke does not scale.
SPARK_WIDTH, SPARK_HEIGHT = 100, 24


def sparkline(values: list[float]) -> str:
    """SVG polyline points for ``values`` across the sparkline box
    (``SPARK_WIDTH`` by ``SPARK_HEIGHT``, the macro's viewBox), highest at
    the top; a flat line sits on the floor. A line drawn small: a queue's
    waiting jobs, a card's CPU. At most a point a unit of width, each the
    highest of its stretch, so a spike still shows."""
    width, height = SPARK_WIDTH, SPARK_HEIGHT
    if not values:
        return ""
    if len(values) > width:
        size = len(values) / width
        values = [
            max(values[int(i * size) : int((i + 1) * size)]) for i in range(width)
        ]
    if len(set(values)) == 1:
        # Steady: one line, on the floor when empty, midway otherwise, so a
        # quiet queue draws the same however many samples it has.
        y = height if values[0] == 0 else height / 2
        return f"0.0,{y:.1f} {width:.1f},{y:.1f}"
    top = max(values)
    step = width / (len(values) - 1)
    return " ".join(
        f"{i * step:.1f},{height - v / top * height:.1f}" for i, v in enumerate(values)
    )
