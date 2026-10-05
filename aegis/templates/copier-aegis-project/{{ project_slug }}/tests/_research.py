"""A source the research tests control: what a search finds and what a
thread holds are the test's to write."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.services.research import registry
from app.services.research.registry import Source, SourceItem


class FakeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str


class FakeData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flair: str | None = None


class FakeSite:
    """A source whose world the test writes: what a search finds and what
    a thread holds."""

    def __init__(self) -> None:
        self.results: dict[str, list[SourceItem]] = {}
        self.threads: dict[str, list[SourceItem]] = {}
        self.searched: list[str] = []
        # Queries whose search fails, the way a timed-out request does.
        self.failing: set[str] = set()

    async def search(self, query: FakeQuery) -> list[SourceItem]:
        self.searched.append(query.q)
        if query.q in self.failing:
            raise TimeoutError(f"search for {query.q!r} timed out")
        return self.results.get(query.q, [])

    async def thread(self, external_id: str) -> list[SourceItem]:
        return self.threads.get(external_id, [])


def story(external_id: str, title: str, score: int = 10, **data: Any) -> SourceItem:
    return SourceItem(
        external_id=external_id,
        kind="story",
        title=title,
        url=f"https://example.com/{external_id}",
        author="ada",
        published_at=datetime(2026, 9, 1, tzinfo=UTC),
        score=score,
        comment_count=0,
        data=data,
    )


def comment(external_id: str, parent: str, text: str) -> SourceItem:
    return SourceItem(
        external_id=external_id, kind="comment", parent_external_id=parent, text=text
    )


@contextmanager
def fake_source() -> Iterator[FakeSite]:
    """``fake`` registered as a research source for the block."""
    fake = FakeSite()
    registry.register_source(
        Source(
            name="fake",
            title="Fake",
            query=FakeQuery,
            data=FakeData,
            search=fake.search,  # type: ignore[arg-type]
            thread=fake.thread,
        )
    )
    try:
        yield fake
    finally:
        registry.unregister_source("fake")
