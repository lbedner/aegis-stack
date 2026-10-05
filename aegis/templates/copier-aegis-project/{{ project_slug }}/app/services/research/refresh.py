"""Running watches: ask each source, then save what came back in one pass.

Every watch's source is asked first, with no transaction open; each thread
is read once however many watches found it. Then each source's items are
upserted together, threads linked, replies a re-read thread no longer holds
marked, and every watch's finds stamped: a handful of statements per
source, in bounded batches, whatever the number of items or watches. A
watch whose source fails sits that run out; the others still refresh.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.research.models import ResearchItem, ResearchMatch, ResearchWatch
from app.services.research.registry import SourceItem, source_for, validated

logger = logging.getLogger(__name__)

# Rows per statement: far under the ~32k bind parameters Postgres and
# SQLite allow, at a dozen parameters a row.
BATCH = 1_000
# Thread reads in flight at once, per refresh: quick, and polite to a site.
CONCURRENT_THREADS = 4


@dataclass
class _Fetched:
    """What one source returned this run, across every watch on it."""

    items: dict[str, SourceItem] = field(default_factory=dict)
    # external id -> the external id of the top of its thread.
    roots: dict[str, str] = field(default_factory=dict)
    # Tops whose thread was read whole this run.
    threads: set[str] = field(default_factory=set)


async def refresh_every_watch(db: AsyncSession) -> dict[int, int]:
    """Every owner's watches, for the nightly job."""
    return await refresh_watches(db, list((await db.exec(select(ResearchWatch))).all()))


async def refresh_watches(
    db: AsyncSession, watches: list[ResearchWatch]
) -> dict[int, int]:
    """Search for each watch, read the threads it wants, save everything.
    Returns how many items each watch that ran found; a watch whose source
    failed is left out and keeps its last refresh."""
    # Nothing is written until every source has answered; a transaction held
    # open across those calls would pin a pooled connection for all of them.
    await db.commit()
    now = utcnow()
    threads: dict[tuple[str, str], list[SourceItem]] = {}
    gate = asyncio.Semaphore(CONCURRENT_THREADS)
    ran = [
        (watch, items)
        for watch in watches
        if (items := await _fetch(watch, threads, gate)) is not None
    ]
    by_source: dict[str, _Fetched] = {}
    for watch, items in ran:
        fetched = by_source.setdefault(watch.source, _Fetched())
        for item in items:
            fetched.items[item.external_id] = item
            fetched.roots.setdefault(
                item.external_id, item.root_external_id or item.external_id
            )
    for (source, top), replies in threads.items():
        fetched = by_source.setdefault(source, _Fetched())
        fetched.threads.add(top)
        for item in replies:
            fetched.items[item.external_id] = item
            fetched.roots[item.external_id] = top

    ids: dict[str, dict[str, int]] = {}
    for source, fetched in by_source.items():
        ids[source] = await _save(db, source, fetched, now)
        tops = [ids[source][t] for t in fetched.threads if t in ids[source]]
        await _mark_vanished(db, tops, now)
    await _match(
        db,
        {
            (watch.id, ids[watch.source][item.external_id])  # type: ignore[misc]
            for watch, items in ran
            for item in items
        },
        now,
    )
    for watch, _ in ran:
        watch.refreshed_at = now
    await db.commit()
    return {watch.id: len(items) for watch, items in ran}  # type: ignore[misc]


async def _fetch(
    watch: ResearchWatch,
    threads: dict[tuple[str, str], list[SourceItem]],
    gate: asyncio.Semaphore,
) -> list[SourceItem] | None:
    """One watch's search, its items checked by the source, and the threads
    it wants added to ``threads`` (each read once a run). None when the
    source is missing or fails: nothing of this watch's is saved."""
    try:
        source = source_for(watch.source)
        items = await source.search(source.query.model_validate(watch.query))
        for item in items:
            item.data = validated(source.data, item.data, f"{source.name} item data")
        if watch.with_threads:
            tops = {item.root_external_id or item.external_id for item in items} - {
                top for (name, top) in threads if name == source.name
            }

            async def read(top: str) -> tuple[str, list[SourceItem]]:
                async with gate:
                    return top, await source.thread(top)

            for top, replies in await asyncio.gather(*(read(top) for top in tops)):
                for item in replies:
                    item.data = validated(
                        source.data, item.data, f"{source.name} item data"
                    )
                threads[(source.name, top)] = replies
    except Exception:
        logger.warning(
            "Research: watch %s (%s) failed", watch.id, watch.source, exc_info=True
        )
        return None
    return items


def _insert(db: AsyncSession, model: Any) -> Any:
    """The upsert-capable INSERT for the session's database."""
    name = db.sync_session.get_bind().dialect.name
    dialect = postgresql if name == "postgresql" else sqlite
    return dialect.insert(model)


def _chunks(rows: Sequence[Any]) -> Iterator[Sequence[Any]]:
    for start in range(0, len(rows), BATCH):
        yield rows[start : start + BATCH]


async def _save(
    db: AsyncSession, source: str, fetched: _Fetched, now: datetime
) -> dict[str, int]:
    """Upsert one source's items, then link each to its parent and the top
    of its thread. Returns external id -> row id."""
    rows = [
        item.model_dump(exclude={"parent_external_id", "root_external_id"})
        | {"source": source, "fetched_at": now, "deleted_at": None}
        for item in fetched.items.values()
    ]
    ids: dict[str, int] = {}
    for chunk in _chunks(rows):
        upsert = _insert(db, ResearchItem).values(list(chunk))
        upsert = upsert.on_conflict_do_update(
            index_elements=["source", "external_id"],
            set_={
                name: upsert.excluded[name]
                for name in chunk[0]
                if name not in ("source", "external_id")
            },
        ).returning(col(ResearchItem.external_id), col(ResearchItem.id))
        ids |= dict((await db.execute(upsert)).tuples().all())
    # A reply found by search whose parent or top is not in this run.
    wanted = sorted(
        {
            linked
            for item in fetched.items.values()
            for linked in (item.parent_external_id, fetched.roots[item.external_id])
            if linked and linked not in ids
        }
    )
    for chunk in _chunks(wanted):
        ids |= dict(
            (
                await db.exec(
                    select(ResearchItem.external_id, ResearchItem.id).where(
                        ResearchItem.source == source,
                        col(ResearchItem.external_id).in_(chunk),
                    )
                )
            ).all()
        )
    links = [
        {
            "id": ids[item.external_id],
            "parent_id": ids.get(item.parent_external_id or ""),
            "root_id": ids.get(fetched.roots[item.external_id]),
        }
        for item in fetched.items.values()
    ]
    for chunk in _chunks(links):
        await db.execute(update(ResearchItem), list(chunk))
    return ids


async def _mark_vanished(db: AsyncSession, root_ids: list[int], now: datetime) -> None:
    """A stored reply its re-read thread no longer holds was deleted at the
    source: everything in those threads not fetched this run. The row and
    its numbers stay; its words and its author go."""
    for chunk in _chunks(root_ids):
        await db.execute(
            update(ResearchItem)
            .where(
                col(ResearchItem.root_id).in_(chunk),
                col(ResearchItem.fetched_at) < now,
                col(ResearchItem.deleted_at).is_(None),
            )
            .values(deleted_at=now, text=None, author=None)
            .execution_options(synchronize_session=False)
        )


async def _match(db: AsyncSession, pairs: set[tuple[int, int]], now: datetime) -> None:
    """Stamp what each watch found this time."""
    rows = [
        {"watch_id": watch_id, "item_id": item_id, "last_matched_at": now}
        for watch_id, item_id in sorted(pairs)
    ]
    for chunk in _chunks(rows):
        upsert = _insert(db, ResearchMatch).values(list(chunk))
        await db.execute(
            upsert.on_conflict_do_update(
                index_elements=["watch_id", "item_id"],
                set_={"last_matched_at": upsert.excluded.last_matched_at},
            )
        )
