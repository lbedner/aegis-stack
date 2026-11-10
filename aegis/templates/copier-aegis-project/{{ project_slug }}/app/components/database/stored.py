"""The storage catalog: a row per object put in the store
(``app.core.storage``) through ``store``. Keys are content hashes, so
owners storing the same file share one object, and one goes only once no
row names it (``held``).

Deleting is two steps, because bytes cannot be rolled back. ``release``
marks the row, in the caller's transaction; ``purge`` deletes what is
marked and no row names once that commits, run by the session helpers in
``app.core.db``. A rollback leaves the object as it was, and the same bytes
stored again in between clear the mark. Each step locks the row, so a
purge and a store of the same bytes never interleave (on SQLite every
transaction begins IMMEDIATE, which serializes them anyway).
"""

from sqlalchemy import delete, select, update
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import insert
from app.core.storage import content_key, get_storage, held
from app.core.time import utcnow

from .models import StoredObject


async def store(
    session: AsyncSession, data: bytes, *, content_type: str | None = None
) -> str:
    """Catalog ``data`` and put it in the store: the key it lives under.
    Stored again, a released object is wanted again."""
    storage = get_storage()
    # Put first, outside the row's lock (on SQLite, the database's): an
    # upload can take a while.
    await storage.put(data, content_type=content_type)
    key = content_key(data)
    row = insert(session, StoredObject).values(
        key=key, bytes=len(data), content_type=content_type, created_at=utcnow()
    )
    await session.execute(
        row.on_conflict_do_update(
            index_elements=["key"],
            set_={"released_at": None},
            where=col(StoredObject.released_at).is_not(None),
        )
    )
    # Again under the lock: a purge that finished in between deleted the
    # bytes. Otherwise this finds them there and writes nothing.
    await storage.put(data, content_type=content_type)
    return key


async def release(session: AsyncSession, key: str) -> None:
    """Mark ``key``'s object for ``purge``."""
    await session.execute(
        update(StoredObject)
        .where(col(StoredObject.key) == key)
        .values(released_at=utcnow())
    )
    session.info["released"] = True


async def purge(session: AsyncSession) -> list[str]:
    """Delete every released object nothing names, row then bytes, and keep
    the rest (their mark cleared): the keys gone.

    ponytail: one ``held`` per released key; purges are one or two
    objects, batch the check if a sweep ever purges thousands.
    """
    released = (
        await session.execute(
            select(StoredObject.key)
            .where(col(StoredObject.released_at).is_not(None))
            .order_by(StoredObject.key)
            .with_for_update()
        )
    ).scalars()
    gone, kept = [], []
    for key in released:
        (kept if await held(session, key) else gone).append(key)
    if kept:
        await session.execute(
            update(StoredObject)
            .where(col(StoredObject.key).in_(kept))
            .values(released_at=None)
        )
    if gone:
        # The row first: a key it did not see refuses the delete before
        # any bytes go.
        await session.execute(
            delete(StoredObject).where(col(StoredObject.key).in_(gone))
        )
        await session.flush()
        for key in gone:
            await get_storage().delete(key)
    return gone
