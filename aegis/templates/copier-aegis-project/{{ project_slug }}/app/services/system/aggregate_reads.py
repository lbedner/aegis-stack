"""The ``aggregate`` tool: what each part of the app holds, as figures
(``app.core.aggregates``), and the lines naming them in an agent's map of
the app (``listed``), since an agent reads what its map names. The
figures are an operator's: the tool, and the map's lines, an admin's."""

from pydantic import BaseModel

from app.core import aggregates, ranges
from app.core.figures import FIGURES
from app.core.tools import register_tool


class Named(BaseModel):
    """An aggregate there is, and the question it answers."""

    model_config = FIGURES

    name: str
    about: str


class Listed(BaseModel):
    """The aggregates there are, and the windows ``days`` takes."""

    model_config = FIGURES

    aggregates: list[Named]
    windows: list[int]


async def aggregate(
    name: str | None = None, days: int | None = None
) -> Listed | BaseModel:
    """What each part of the app holds, as figures: counts and sums grouped
    by label, never a row. No ``name``: the aggregates there are
    (``<part>.<name>``), the question each answers, and the windows
    ``days`` takes (none: all of it). A ``name`` (``scheduler.runs``): its
    figures over the last ``days``. Sort, join or chart them in the script;
    only the answer need reach the model."""
    if name is None:
        return Listed(
            aggregates=[
                Named(name=key, about=one.about)
                for key, one in sorted(aggregates.declared().items())
            ],
            windows=list(ranges.DAYS),
        )
    return await aggregates.read(name, days)



register_tool(
    "aggregate",
    aggregate,
    description="What each part holds: counts and sums by label, never rows",
    effect="read",
    doing="Counting what each part holds",
    admin=True,
)

def listed() -> str:
    """The aggregates there are, as an agent's map names them; empty where
    there are none."""
    names = [
        f"- {key}: {one.about}" for key, one in sorted(aggregates.declared().items())
    ]
    if not names:
        return ""
    days = ", ".join(map(str, ranges.DAYS))
    head = f"Aggregates (the aggregate tool reads each; days {days} or all):"
    return "\n".join([head, *names])
