"""Who was heard in a call, as the pages show it: each speaker's color
(``voice``, ``voices``) and how long each was heard (``heard_rows``,
``heard_line``)."""

from collections.abc import Iterable
import zlib

from app.core.constants import CHART_RAMP
from app.core.formatting import format_span


def voice(name: str) -> int:
    """The theme's color a speaker's name points at, 1 to ``CHART_RAMP``: the
    same in every meeting, unless someone in it already has it
    (``voices``)."""
    return zlib.crc32(name.encode()) % CHART_RAMP + 1


def voices(names: Iterable[str]) -> dict[str, int]:
    """A color for each speaker in one meeting, none shared while the
    colors last: each keeps their name's (``voice``) unless someone already
    has it, then takes the next free one."""
    taken: dict[str, int] = {}
    for name in sorted(set(names)):
        color = voice(name)
        while color in taken.values() and len(taken) < CHART_RAMP:
            color = color % CHART_RAMP + 1
        taken[name] = color
    return taken


def heard_rows(heard: dict[str, float]) -> list[tuple[str, str, float]]:
    """How long each speaker was heard, most heard first: their name, the
    time ("4m 10s") and how it compares with the most heard (1.0)."""
    most = max(heard.values(), default=0) or 1
    ranked = sorted(heard.items(), key=lambda item: -item[1])
    return [
        (name, format_span(seconds) or "0s", seconds / most) for name, seconds in ranked
    ]


def heard_line(heard: dict[str, float]) -> str | None:
    """``heard_rows`` on one line: "Ada 4m 10s · Leonard 2m 30s"; None when
    nobody was heard."""
    rows = heard_rows(heard)
    return " · ".join(f"{name} {span}" for name, span, _ in rows) or None
