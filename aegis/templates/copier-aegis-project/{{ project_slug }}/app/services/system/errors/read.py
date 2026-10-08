"""Retained issues for a query: the kept summaries when nothing narrows it,
else every occurrence's search projection, filtered and grouped once."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self

from app.core.formatting import row_matches
from app.services.system.errors.models import ErrorIssue, ErrorSearch
from app.services.system.errors.store import ErrorStore
from app.services.system.ui_logs import Picked, number_of


@dataclass(frozen=True)
class Search:
    """A query's filters, read once: the sources picked (as on Logs), the
    level, how far back (epoch seconds), and the text."""

    picked: Picked
    level: str
    since: float | None
    text: str

    @classmethod
    def of(cls, query: Mapping[str, str], now: datetime) -> Self:
        window = number_of(query, "window")
        return cls(
            Picked.of(query),
            query.get("level", ""),
            now.timestamp() - window if window else None,
            query.get("q", "").strip(),
        )

    def __bool__(self) -> bool:
        return bool(self.picked or self.level or self.since or self.text)

    def keeps(self, row: ErrorSearch) -> bool:
        return (
            self.picked.keeps(row.page, row.container_name, row.app_service)
            and (not self.level or row.level == self.level)
            and (self.since is None or row.timestamp.timestamp() >= self.since)
            and row_matches(self.text, (row.message, row.exception_type))
        )


async def search(
    store: ErrorStore, query: Mapping[str, str], *, offset: int, limit: int
) -> tuple[list[ErrorIssue], int]:
    """One page of the issues ``query`` keeps, the latest first, and how
    many there are."""
    wanted = Search.of(query, datetime.now(UTC))
    if not wanted:
        return await store.issues(offset=offset, limit=limit), await store.issue_count()
    groups: dict[str, list[Any]] = {}  # fingerprint: [latest, count, first seen]
    for row in await store.searched():
        if not wanted.keeps(row):
            continue
        group = groups.setdefault(row.fingerprint, [row, 0, row.timestamp])
        group[1] += 1
        group[2] = min(group[2], row.timestamp)
        if row.timestamp > group[0].timestamp:
            group[0] = row
    issues = sorted(
        (_issue(*group) for group in groups.values()),
        key=lambda issue: (issue.last_seen, issue.fingerprint),
        reverse=True,
    )
    return issues[offset : offset + limit], len(issues)


def _issue(latest: ErrorSearch, count: int, first: datetime) -> ErrorIssue:
    return ErrorIssue(
        **latest.model_dump(
            include={
                "fingerprint",
                "page",
                "service",
                "app_service",
                "container_name",
                "message",
                "exception_type",
            }
        ),
        count=count,
        first_seen=first,
        last_seen=latest.timestamp,
        latest_id=latest.id,
    )
