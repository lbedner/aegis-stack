"""Slow & locked's search (``ActivitySearch``) over what
``app.core.db_activity`` kept, shown by ``ui_database``. Ships with the
database, as what it reads does; the page that asks ships with every
stack."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from app.core import db_activity, frames, runtime, series
from app.core.formatting import row_matches
from app.services.system import db_transactions, ui_database
from app.services.system.ui_logs import Picked, listed


@dataclass(frozen=True)
class ActivitySearch:
    """Slow & locked's filters, read once (as Errors' ``Search``): how far
    back, the kinds, the sources picked (as on Logs), and the text."""

    window: int
    kinds: frozenset[str]
    picked: Picked
    text: str

    @classmethod
    def of(cls, query: Mapping[str, str]) -> Self:
        return cls(
            series.window_of(
                query.get("window"), db_activity.windows(), db_activity.SUMMARY_SECONDS
            ),
            frozenset(listed(query, "kind")),
            Picked.of(query),
            query.get("q", "").strip(),
        )

    def keeps(
        self,
        event: dict[str, Any],
        containers: Mapping[str, db_transactions.SampledContainer],
    ) -> bool:
        """``containers``: ``db_transactions.containers``, when sources are
        picked. Where it ran is its container's page; outside Docker, its
        program's name, which is a page's only by coincidence (taskiq's
        children are named for its ``worker`` subcommand)."""
        if self.kinds and event["kind"] not in self.kinds:
            return False
        if self.picked:
            found = db_transactions.container_of(containers, event["host"])
            page = (
                found.page
                if found
                else runtime.page_for(frames.role_of(event["process"])) or ""
            )
            if not self.picked.keeps(
                page,
                found.name if found else None,
                event["app_service"],
                event["app_component"],
            ):
                return False
        return not self.text or row_matches(
            self.text, (event["caller"], event["process"], ui_database.what(event))
        )


async def find_activity(search: ActivitySearch, shown: int) -> dict[str, Any]:
    """What ``search`` keeps of its window: the newest ``shown`` rows, how
    many more there are, and every one by code."""
    containers = await db_transactions.containers() if search.picked else {}
    kept = [
        event
        for event in await db_activity.recent(search.window)
        if search.keeps(event, containers)
    ]
    return {
        "rows": ui_database.activity(kept[:shown]),
        "more": max(len(kept) - shown, 0),
        "groups": ui_database.activity_groups(db_activity.grouped(kept)),
    }
