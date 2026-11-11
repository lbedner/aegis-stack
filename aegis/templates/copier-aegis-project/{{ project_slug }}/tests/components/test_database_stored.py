"""The storage catalog (``app.components.database.stored``)."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Table
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.database.models import StoredObject
from app.components.database.stored import purge, release, store
from app.core.db import get_async_session
from app.core.storage import FilesystemStorage, content_key

# Each test stores and releases more than once; the repeats are the scenario.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)


async def test_an_object_is_catalogued_once(
    async_db_session: AsyncSession, files: FilesystemStorage
) -> None:
    key = await store(async_db_session, b"a clip", content_type="video/mp4")
    assert await store(async_db_session, b"a clip", content_type="video/mp4") == key

    rows = (await async_db_session.exec(select(StoredObject))).all()
    assert [(r.key, r.bytes, r.content_type) for r in rows] == [
        (content_key(b"a clip"), 6, "video/mp4")
    ]
    assert await files.exists(key)


@pytest.mark.parametrize(
    "row",
    [
        lambda key: {"file_key": key},
        lambda key: {"meta_data": {"attachments": [{"key": key}]}},
    ],
    ids=["column", "json"],
)
async def test_an_object_a_row_names_is_kept(
    async_db_session: AsyncSession,
    files: FilesystemStorage,
    key_holder: Table,
    row: Callable[[str], dict[str, Any]],
) -> None:
    """Keys are content hashes, so deleting a file for one owner must not
    take it from another that stored the same bytes."""
    key = await store(async_db_session, b"shared")
    await async_db_session.execute(key_holder.insert(), [row(key)])

    await release(async_db_session, key)
    assert await purge(async_db_session) == []
    assert await files.exists(key)
    kept = await async_db_session.get(StoredObject, key)
    assert kept is not None and kept.released_at is None


async def test_an_object_nothing_names_goes_once_purged(
    async_db_session: AsyncSession, files: FilesystemStorage, key_holder: Table
) -> None:
    """Released, it is still there: the caller may yet roll back. The purge
    after its commit deletes it."""
    key = await store(async_db_session, b"alone")
    other = await store(async_db_session, b"held")
    await async_db_session.execute(key_holder.insert(), [{"file_key": other}])

    await release(async_db_session, key)
    assert await files.exists(key)

    assert await purge(async_db_session) == [key]
    assert not await files.exists(key)
    assert await async_db_session.get(StoredObject, key) is None


async def test_storing_a_released_object_again_keeps_it(
    async_db_session: AsyncSession, files: FilesystemStorage
) -> None:
    """The same bytes stored between a release and its purge are wanted
    again: the purge leaves them."""
    key = await store(async_db_session, b"again")
    await release(async_db_session, key)
    await store(async_db_session, b"again")

    assert await purge(async_db_session) == []
    assert await files.exists(key)


async def test_a_session_that_commits_a_release_purges_it(
    files: FilesystemStorage,
) -> None:
    """The session helpers purge after their commit, so no caller has to
    remember to; a release rolled back leaves the object. These sessions
    commit to the worker's shared database, where a row another test left
    may name the same content (a document of ``b"gone"``), so the bytes are
    this test's alone."""
    async with get_async_session() as session:
        kept = await store(session, f"kept {uuid4()}".encode())
        gone = await store(session, f"gone {uuid4()}".encode())
    async with get_async_session() as session:
        await release(session, kept)
        await session.rollback()
    async with get_async_session() as session:
        await release(session, gone)

    assert await files.exists(kept)
    assert not await files.exists(gone)
    async with get_async_session() as session:
        assert await session.get(StoredObject, gone) is None
        await purge(session)  # the next test's catalog starts empty
        await session.delete(await session.get(StoredObject, kept))
