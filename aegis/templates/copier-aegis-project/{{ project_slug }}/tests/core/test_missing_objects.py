"""``missing_objects``: the stored objects rows name and the store lacks."""

from pathlib import Path

from sqlalchemy import JSON, Column, Integer, String, Table
from sqlmodel import AutoString, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import (
    FilesystemStorage,
    content_key,
    missing_objects,
    set_storage,
)


async def test_missing_objects_are_the_ones_rows_name_and_the_store_lacks(
    async_db_session: AsyncSession, tmp_path: Path
) -> None:
    """A copy that brought the database and not the store (a first deploy,
    a restore) leaves rows naming files that are not there: a broken page
    that nothing finds until someone opens it. ``AutoString`` is what a
    SQLModel ``str`` field is; a check that saw only ``String`` found none.
    A chat attachment or a paste is named inside JSON, not in a column."""
    table = Table(
        "stored_probe",
        SQLModel.metadata,
        Column("id", Integer, primary_key=True),
        Column("file_key", AutoString),
        Column("payee_key", String),
        Column("meta_data", JSON),
    )
    store = FilesystemStorage(tmp_path)
    set_storage(store)
    try:
        await async_db_session.run_sync(lambda s: table.create(s.connection()))
        kept = await store.put(b"kept")
        gone = content_key(b"gone")
        attached = content_key(b"an attachment")
        await async_db_session.execute(
            table.insert(),
            [
                {"file_key": kept, "payee_key": "acme", "meta_data": {"a": 1}},
                {"file_key": gone, "payee_key": None, "meta_data": None},
                {
                    "file_key": None,
                    "payee_key": None,
                    "meta_data": {"attachments": [{"key": attached}, {"key": kept}]},
                },
            ],
        )
        assert await missing_objects(async_db_session) == sorted([gone, attached])
    finally:
        SQLModel.metadata.remove(table)
        set_storage(None)
