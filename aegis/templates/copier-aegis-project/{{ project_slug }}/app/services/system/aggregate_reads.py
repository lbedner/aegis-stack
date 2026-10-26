"""The ``aggregate`` tool: what each part of the app holds, as figures
(``app.core.aggregates``), and the lines naming them in an agent's map of
the app (``listed``), since an agent reads what its map names. The
figures are an operator's: the tool, and the map's lines, an admin's."""

from typing import Any

from app.core import aggregates, ranges


async def aggregate(name: str | None = None, days: int | None = None) -> dict[str, Any]:
    """What each part of the app holds, as figures: counts and sums grouped
    by label, never a row. No ``name``: the aggregates there are
    (``<part>.<name>``), the question each answers, and the windows
    ``days`` takes (none: all of it). A ``name`` (``scheduler.runs``): its
    figures over the last ``days``. Sort, join or chart them in the script;
    only the answer need reach the model."""
    if name is None:
        return {
            "aggregates": [
                {"name": key, "about": one.about}
                for key, one in sorted(aggregates.declared().items())
            ],
            "windows": list(ranges.DAYS),
        }
    return (await aggregates.read(name, days)).model_dump(mode="json")


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
