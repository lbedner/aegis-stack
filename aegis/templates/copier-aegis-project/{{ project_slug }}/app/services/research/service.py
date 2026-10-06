"""Research service: an owner's watches, and reading back what they found.

What an owner may read: the items its watches found and, for a watch that
reads threads, the replies under them. Items are stored once per source, so
this is the one rule that keeps one owner's research from another's. A
service with no owner (``None``: no auth, the CLI, the health check) reads
every watch, as ``owner_filters`` has it everywhere.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, case, delete, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.research.models import ResearchItem, ResearchMatch, ResearchWatch
from app.services.research.refresh import refresh_watches
from app.services.research.registry import source_for, validated
from app.services.shared.queries import owner_filters

# The most one search returns.
MAX_RESULTS = 200


class WatchNotFoundError(Exception):
    pass


class SourceFailedError(Exception):
    """A watch's source is missing or did not answer this time."""


class ResearchService:
    def __init__(self, db: AsyncSession, owner_user_id: int | None) -> None:
        self.db = db
        self.owner_user_id = owner_user_id

    # -- watches -----------------------------------------------------------

    async def add_watch(
        self,
        source: str,
        name: str,
        query: dict[str, Any],
        with_threads: bool = False,
    ) -> ResearchWatch:
        """Save a search on ``source``; its query is the source's to check."""
        watch = ResearchWatch(
            owner_user_id=self.owner_user_id,
            source=source,
            name=name,
            query=validated(source_for(source).query, query, f"{source} query"),
            with_threads=with_threads,
        )
        self.db.add(watch)
        await self.db.commit()
        return watch

    async def list_watches(self) -> list[ResearchWatch]:
        return list(
            (
                await self.db.exec(
                    select(ResearchWatch)
                    .where(*self._owned())
                    .order_by(col(ResearchWatch.id))
                )
            ).all()
        )

    async def get_watch(self, watch_id: int) -> ResearchWatch:
        watch = (
            await self.db.exec(
                select(ResearchWatch).where(
                    ResearchWatch.id == watch_id, *self._owned()
                )
            )
        ).first()
        if watch is None:
            raise WatchNotFoundError(f"watch {watch_id}")
        return watch

    async def delete_watch(self, watch_id: int) -> None:
        """The watch, what it found, and the items no other watch found."""
        watch = await self.get_watch(watch_id)
        await self.db.execute(
            delete(ResearchMatch).where(col(ResearchMatch.watch_id) == watch.id)
        )
        await self.db.delete(watch)
        matched = select(ResearchMatch.item_id)
        await self.db.execute(
            delete(ResearchItem)
            .where(
                col(ResearchItem.id).not_in(matched),
                or_(
                    col(ResearchItem.root_id).is_(None),
                    col(ResearchItem.root_id).not_in(matched),
                ),
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()

    async def refresh_watch(self, watch_id: int) -> int:
        """Run the watch's search now. Returns how many items it found."""
        watch = await self.get_watch(watch_id)
        found = await refresh_watches(self.db, [watch])
        if watch.id not in found:
            raise SourceFailedError(
                f"the {watch.source} source failed or is not installed; "
                "try again shortly"
            )
        return found[watch.id]  # type: ignore[index]

    # -- reading -----------------------------------------------------------

    async def search(
        self,
        text: str | None = None,
        *,
        source: str | None = None,
        watch_id: int | None = None,
        kind: str | None = None,
        current_only: bool = False,
        limit: int = 50,
    ) -> list[ResearchItem]:
        """What the owner may read, newest first. ``current_only`` keeps what
        the last refresh still found; otherwise history counts too."""
        query = select(ResearchItem).where(self._visible(watch_id, current_only))
        if text:
            pattern = f"%{text}%"
            query = query.where(
                or_(
                    col(ResearchItem.title).ilike(pattern),
                    col(ResearchItem.text).ilike(pattern),
                )
            )
        if source:
            query = query.where(ResearchItem.source == source)
        if kind:
            query = query.where(ResearchItem.kind == kind)
        # ponytail: a scan with ILIKE; past ~100k items, a trigram index on
        # Postgres and a UNION for the visibility test.
        query = query.order_by(
            col(ResearchItem.published_at).desc().nulls_last(), col(ResearchItem.id)
        ).limit(max(1, min(limit, MAX_RESULTS)))
        return list((await self.db.exec(query)).all())

    async def thread(self, item_id: int) -> list[ResearchItem]:
        """The thread ``item_id`` belongs to, its top first, if the owner may
        read it; else nothing."""
        item = await self.db.get(ResearchItem, item_id)
        if item is None:
            return []
        root = item.root_id or item.id
        return list(
            (
                await self.db.exec(
                    select(ResearchItem)
                    .where(
                        or_(ResearchItem.id == root, ResearchItem.root_id == root),
                        self._visible(),
                    )
                    .order_by(
                        case((ResearchItem.id == root, 0), else_=1),
                        col(ResearchItem.id),
                    )
                )
            ).all()
        )

    # -- the rule ------------------------------------------------------------

    def _owned(self) -> list[Any]:
        return owner_filters(ResearchWatch.owner_user_id, self.owner_user_id)

    def _visible(
        self, watch_id: int | None = None, current_only: bool = False
    ) -> ColumnElement[bool]:
        """An item one of the owner's watches found, or anything in the thread
        of one a thread-reading watch of theirs found (the find may itself
        be a reply: its thread is its root's)."""

        def found(threads_only: bool) -> Any:
            target = (
                func.coalesce(ResearchItem.root_id, ResearchMatch.item_id)
                if threads_only
                else ResearchMatch.item_id
            )
            matches = (
                select(target)
                .select_from(ResearchMatch)
                .join(ResearchWatch, col(ResearchWatch.id) == ResearchMatch.watch_id)
                .where(*self._owned())
            )
            if threads_only:
                matches = matches.join(
                    ResearchItem, col(ResearchItem.id) == ResearchMatch.item_id
                )
            if watch_id is not None:
                matches = matches.where(ResearchMatch.watch_id == watch_id)
            if current_only:
                matches = matches.where(
                    col(ResearchMatch.last_matched_at)
                    >= col(ResearchWatch.refreshed_at)
                )
            if threads_only:
                matches = matches.where(col(ResearchWatch.with_threads).is_(True))
            return matches

        return or_(
            col(ResearchItem.id).in_(found(threads_only=False)),
            col(ResearchItem.root_id).in_(found(threads_only=True)),
        )


async def research_counts(db: AsyncSession) -> dict[str, Any]:
    """Across every owner, for the health check: watches, items, last run."""
    watches, last = (
        await db.exec(
            select(func.count(), func.max(ResearchWatch.refreshed_at)).select_from(
                ResearchWatch
            )
        )
    ).one()
    items = (await db.exec(select(func.count()).select_from(ResearchItem))).one()
    return {
        "watches": watches,
        "items": items,
        "last_refresh": last.isoformat() if last else None,
    }
