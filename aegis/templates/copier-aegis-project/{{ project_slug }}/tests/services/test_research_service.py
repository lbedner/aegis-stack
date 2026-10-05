"""The research service (#1422): outside posts and threads, collected by
saved searches (watches) into one store, whatever the source.

A source is a plugin's business: it searches, reads a thread, refreshes
numbers. Everything else is here, tested through a fake source.
"""

from typing import Any

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.research import registry
from app.services.research.models import ResearchItem
from app.services.research.refresh import refresh_every_watch
from app.services.research.registry import UnknownSourceError
from app.services.research.service import (
    ResearchService,
    SourceFailedError,
    WatchNotFoundError,
)
from tests._research import FakeSite, comment, story

# Most tests refresh a watch twice to see what changes between runs, so the
# same reads repeat by construction. The nightly pass, the one that must not
# grow with the number of watches, runs under the strict gate below.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)


async def _items(session: AsyncSession) -> dict[str, ResearchItem]:
    rows = (await session.exec(select(ResearchItem))).all()
    return {row.external_id: row for row in rows}


async def test_a_watch_finds_items_and_a_refresh_updates_them_in_place(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    svc = ResearchService(async_db_session, owner_user_id=None)
    watch = await svc.add_watch("fake", "Templates", {"q": "fastapi template"})
    site.results["fastapi template"] = [story("1", "Show: a template", score=12)]

    found = await svc.refresh_watch(watch.id)  # type: ignore[arg-type]
    site.results["fastapi template"] = [story("1", "Show: a template", score=90)]
    await svc.refresh_watch(watch.id)  # type: ignore[arg-type]

    assert found == 1
    items = await _items(async_db_session)
    assert list(items) == ["1"]
    assert items["1"].score == 90


async def test_a_watch_query_is_the_sources_to_check(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    svc = ResearchService(async_db_session, owner_user_id=None)

    with pytest.raises(ValueError, match="q"):
        await svc.add_watch("fake", "Typo", {"query": "x"})
    with pytest.raises(UnknownSourceError):
        await svc.add_watch("nowhere", "Lost", {"q": "x"})


async def test_an_items_extras_are_the_sources_to_check(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    svc = ResearchService(async_db_session, owner_user_id=None)
    watch = await svc.add_watch("fake", "Flair", {"q": "x"})
    site.results["x"] = [story("1", "One", nonsense=True)]

    with pytest.raises(SourceFailedError):
        await svc.refresh_watch(watch.id)  # type: ignore[arg-type]
    assert await _items(async_db_session) == {}


async def test_an_item_that_stops_matching_keeps_its_history(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    svc = ResearchService(async_db_session, owner_user_id=None)
    watch = await svc.add_watch("fake", "Templates", {"q": "t"})
    site.results["t"] = [story("1", "Old"), story("2", "Both")]
    await svc.refresh_watch(watch.id)  # type: ignore[arg-type]
    site.results["t"] = [story("2", "Both"), story("3", "New")]
    await svc.refresh_watch(watch.id)  # type: ignore[arg-type]

    every = {item.external_id for item in await svc.search(watch_id=watch.id)}
    current = {
        item.external_id
        for item in await svc.search(watch_id=watch.id, current_only=True)
    }

    assert every == {"1", "2", "3"}
    assert current == {"2", "3"}


async def test_a_thread_comes_back_whole_and_a_vanished_comment_is_marked(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    svc = ResearchService(async_db_session, owner_user_id=None)
    watch = await svc.add_watch("fake", "Threads", {"q": "t"}, with_threads=True)
    site.results["t"] = [story("1", "Launch")]
    site.threads["1"] = [
        story("1", "Launch"),
        comment("2", "1", "Nice."),
        comment("3", "2", "Agreed."),
    ]
    await svc.refresh_watch(watch.id)  # type: ignore[arg-type]
    site.threads["1"] = [story("1", "Launch"), comment("2", "1", "Nice.")]
    await svc.refresh_watch(watch.id)  # type: ignore[arg-type]

    root = (await _items(async_db_session))["1"]
    thread = {item.external_id: item for item in await svc.thread(root.id)}  # type: ignore[arg-type]

    assert set(thread) == {"1", "2", "3"}
    assert thread["3"].parent_id == thread["2"].id
    assert thread["3"].deleted_at is not None and thread["3"].text is None
    assert thread["2"].deleted_at is None


async def test_search_finds_text_across_what_the_watches_found(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    svc = ResearchService(async_db_session, owner_user_id=None)
    watch = await svc.add_watch("fake", "All", {"q": "t"})
    site.results["t"] = [story("1", "A FastAPI template"), story("2", "Unrelated")]
    await svc.refresh_watch(watch.id)  # type: ignore[arg-type]

    hits = await svc.search("fastapi")

    assert [item.external_id for item in hits] == ["1"]


async def test_one_owner_never_sees_anothers_watches_or_their_finds(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    mine = ResearchService(async_db_session, owner_user_id=1)
    theirs = ResearchService(async_db_session, owner_user_id=2)
    watch = await theirs.add_watch("fake", "Secret plan", {"q": "t"})
    site.results["t"] = [story("1", "Their find")]
    await theirs.refresh_watch(watch.id)  # type: ignore[arg-type]

    assert await mine.list_watches() == []
    assert await mine.search("find") == []
    with pytest.raises(WatchNotFoundError):
        await mine.refresh_watch(watch.id)  # type: ignore[arg-type]
    root = (await _items(async_db_session))["1"]
    assert await mine.thread(root.id) == []  # type: ignore[arg-type]


async def test_one_failing_watch_does_not_stop_the_others(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    """A source is a network call; one that times out skips its watch for
    this run, and every other watch still refreshes."""
    svc = ResearchService(async_db_session, owner_user_id=None)
    broken = await svc.add_watch("fake", "Broken", {"q": "boom"})
    fine = await svc.add_watch("fake", "Fine", {"q": "ok"})
    site.results["ok"] = [story("1", "Fine")]
    site.failing.add("boom")

    found = await refresh_every_watch(async_db_session)

    assert found == {fine.id: 1}
    assert set(await _items(async_db_session)) == {"1"}
    assert (await svc.get_watch(broken.id)).refreshed_at is None  # type: ignore[arg-type]


async def test_a_reply_found_by_search_reads_its_whole_thread(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    """A search can hit a comment; with threads, its thread is read from
    the top, and the comment sits under that top."""
    svc = ResearchService(async_db_session, owner_user_id=None)
    watch = await svc.add_watch("fake", "Replies", {"q": "r"}, with_threads=True)
    hit = comment("2", "1", "A template, nice.")
    hit.root_external_id = "1"
    site.results["r"] = [hit]
    site.threads["1"] = [story("1", "Launch"), comment("2", "1", "A template, nice.")]
    await svc.refresh_watch(watch.id)  # type: ignore[arg-type]

    reply = (await _items(async_db_session))["2"]
    thread = await svc.thread(reply.id)  # type: ignore[arg-type]

    assert [item.external_id for item in thread] == ["1", "2"]


async def test_replies_are_read_through_a_watch_that_reads_threads(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    """Owner 1 found the story without threads; owner 2's watch read its
    thread. Owner 1 sees the story, not the replies owner 2 collected."""
    site.results["t"] = [story("1", "Launch")]
    site.threads["1"] = [story("1", "Launch"), comment("2", "1", "Nice.")]
    mine = ResearchService(async_db_session, owner_user_id=1)
    theirs = ResearchService(async_db_session, owner_user_id=2)
    await mine.add_watch("fake", "Mine", {"q": "t"})
    await theirs.add_watch("fake", "Theirs", {"q": "t"}, with_threads=True)
    await refresh_every_watch(async_db_session)

    assert {i.external_id for i in await mine.search()} == {"1"}
    assert {i.external_id for i in await theirs.search()} == {"1", "2"}


async def test_deleting_a_watch_drops_what_only_it_found(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    svc = ResearchService(async_db_session, owner_user_id=None)
    gone = await svc.add_watch("fake", "Gone", {"q": "a"}, with_threads=True)
    kept = await svc.add_watch("fake", "Kept", {"q": "b"})
    site.results = {
        "a": [story("1", "Only A"), story("3", "Both")],
        "b": [story("3", "Both")],
    }
    site.threads["1"] = [story("1", "Only A"), comment("2", "1", "Reply")]
    await refresh_every_watch(async_db_session)

    await svc.delete_watch(gone.id)  # type: ignore[arg-type]

    assert set(await _items(async_db_session)) == {"3"}
    assert [w.id for w in await svc.list_watches()] == [kept.id]


async def test_a_watch_on_an_uninstalled_source_sits_out(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    """A plugin removed while its watches remain: those watches skip the
    run, and every other watch still refreshes."""
    from app.services.research.models import ResearchWatch

    async_db_session.add(ResearchWatch(source="gone", name="Orphan", query={}))
    svc = ResearchService(async_db_session, owner_user_id=None)
    fine = await svc.add_watch("fake", "Fine", {"q": "ok"})
    site.results["ok"] = [story("1", "Fine")]

    assert await refresh_every_watch(async_db_session) == {fine.id: 1}


@pytest.fixture
async def two_owners_watching(async_db_session: AsyncSession, site: FakeSite) -> None:
    """Two owners, a watch each, set up before the test so its own queries
    are the refresh's."""
    site.results = {"a": [story("1", "A")], "b": [story("2", "B")]}
    for owner, q in ((1, "a"), (2, "b")):
        await ResearchService(async_db_session, owner_user_id=owner).add_watch(
            "fake", q, {"q": q}
        )


@pytest.mark.queryspy(allow_n_plus_one=False)
@pytest.mark.usefixtures("two_owners_watching")
async def test_refreshing_every_watch_saves_in_one_pass(
    async_db_session: AsyncSession, site: FakeSite
) -> None:
    """The nightly job refreshes every watch of every owner. Each source is
    asked once per watch; the database is written once per source, not once
    per watch."""
    await refresh_every_watch(async_db_session)

    assert sorted(site.searched) == ["a", "b"]
    assert set(await _items(async_db_session)) == {"1", "2"}


def test_a_services_sources_module_registers_its_source(
    fake_service: Any,
) -> None:
    """A plugin keeps its source in its own ``sources.py``; the research
    service finds it on disk, so nothing else lists it."""
    fake_service(
        "demo_source",
        sources=(
            "from pydantic import BaseModel\n"
            "from app.services.research.registry import Source, register_source\n"
            "class Q(BaseModel):\n"
            "    q: str\n"
            "async def nothing(*_):\n"
            "    return []\n"
            "register_source(Source(name='demo', title='Demo', query=Q,"
            " search=nothing, thread=nothing))\n"
        ),
    )
    try:
        registry.load_sources()

        assert "demo" in [s.name for s in registry.installed_sources()]
    finally:
        registry.unregister_source("demo")


def test_a_sources_aware_time_is_stored_as_naive_utc() -> None:
    """Every timestamp column is naive UTC; Postgres refuses an aware value
    for one, so a source's times are converted as the item is built."""
    from datetime import datetime, timedelta, timezone

    from app.services.research.registry import SourceItem

    item = SourceItem(
        external_id="1",
        kind="story",
        published_at=datetime(2026, 9, 1, 2, 0, tzinfo=timezone(timedelta(hours=2))),
    )

    assert item.published_at == datetime(2026, 9, 1, 0, 0)
